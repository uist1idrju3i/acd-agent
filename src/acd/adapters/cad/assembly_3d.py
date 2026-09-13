"""Integrated 3D assembly projection (glTF 2.0 binary plus HTML viewer).

This is an L3 projection for human review only: it does not feed Evidence,
fabrication packages, or gate verdicts. The GLB writer canonicalizes vertex
and triangle order so sequential and parallel pipeline runs produce identical
bytes, and an independent GLB reader re-validates the written file before the
HTML viewer is emitted (fail-closed on any parse failure).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from acd.adapters.cad.assembly_viewer import three_version, write_assembly_viewer_html
from acd.adapters.cad.constants import (
    CAD_ANGULAR_DEFLECTION_DEG,
    CAD_LINEAR_DEFLECTION_MM,
)
from acd.adapters.cad.mechanical import (
    MechanicalGateReport,
    board_plane_z,
    build_component_body_shape,
)
from acd.adapters.cad.project import CadProjection
from acd.core.cad_normalize import normalize_step
from acd.core.mechanical import MechanicalLane
from acd.core.process import ExternalToolError, sha256_bytes


class Assembly3DProjectionError(ExternalToolError):
    """Raised when the integrated 3D assembly projection cannot be trusted."""


@dataclass(frozen=True)
class MeshNode:
    name: str
    layer: str
    source: str
    extras: dict[str, object]
    positions: tuple[float, ...]
    normals: tuple[float, ...]
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class AssemblyMesh:
    graph_id: str
    graph_revision: str
    nodes: tuple[MeshNode, ...]


@dataclass(frozen=True)
class Assembly3DRecord:
    glb_path: Path
    html_path: Path
    manifest_path: Path
    glb_sha256: str
    html_sha256: str
    node_count: int
    triangle_count: int
    interference_node_count: int


_BOARD_COLOR = (0.05, 0.45, 0.20, 1.0)
_COMPONENT_COLOR = (0.55, 0.55, 0.60, 1.0)
_SHELL_COLOR = (0.80, 0.80, 0.85, 1.0)
_LID_COLOR = (0.60, 0.70, 0.90, 1.0)
_INTERFERENCE_COLOR = (1.0, 0.10, 0.10, 1.0)

_GLB_MAGIC = 0x46546C67
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942
_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963
_COMPONENT_FLOAT = 5126
_COMPONENT_UINT = 5125
_COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_COUNTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def _load_build123d() -> Any:
    try:
        return importlib.import_module("build123d")
    except (ImportError, ModuleNotFoundError) as exc:
        raise Assembly3DProjectionError("build123d is unavailable") from exc


def _face_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if not math.isfinite(norm) or norm == 0.0:
        return None
    return (nx / norm, ny / norm, nz / norm)


def tessellate_shape(shape: Any, *, build123d: Any) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Tessellate a shape into canonical flat (unshared) vertices and normals.

    Coordinates are rounded to 6 decimals, degenerate triangles are dropped,
    each triangle's vertex tuple is rotated so the lexicographically smallest
    vertex is first (winding preserved), and triangles are sorted
    lexicographically. Normals are per-vertex face normals.
    """
    try:
        vertices, triangles = shape.tessellate(CAD_LINEAR_DEFLECTION_MM, CAD_ANGULAR_DEFLECTION_DEG)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise Assembly3DProjectionError("shape tessellation failed") from exc
    points = [(round(float(v.X), 6), round(float(v.Y), 6), round(float(v.Z), 6)) for v in vertices]
    canonical: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = []
    for triangle in triangles:
        try:
            i, j, k = (int(index) for index in triangle)
            a, b, c = points[i], points[j], points[k]
        except (IndexError, TypeError, ValueError) as exc:
            raise Assembly3DProjectionError(
                "shape tessellation returned an invalid triangle"
            ) from exc
        normal = _face_normal(a, b, c)
        if normal is None:
            continue
        face = (a, b, c)
        minimum = min(range(3), key=lambda index: face[index])
        rotated = face[minimum:] + face[:minimum]
        canonical.append((rotated[0], rotated[1], rotated[2], normal))
    canonical.sort(key=lambda item: (item[0], item[1], item[2]))
    positions: list[float] = []
    normals: list[float] = []
    for a, b, c, normal in canonical:
        positions.extend((*a, *b, *c))
        normals.extend((*normal, *normal, *normal))
    return tuple(positions), tuple(normals)


def _extras(
    *, graph_revision: str, layer: str, source: str, extra: Mapping[str, object]
) -> dict[str, object]:
    merged: dict[str, object] = {
        "graph_revision": graph_revision,
        "layer": layer,
        "source": source,
    }
    merged.update(extra)
    return merged


def _tessellated_node(
    *,
    shape: Any,
    build123d: Any,
    name: str,
    layer: str,
    source: str,
    color: tuple[float, float, float, float],
    extras: dict[str, object],
) -> MeshNode:
    positions, normals = tessellate_shape(shape, build123d=build123d)
    if not positions:
        raise Assembly3DProjectionError(f"mesh node {name!r} has no triangles")
    return MeshNode(
        name=name,
        layer=layer,
        source=source,
        extras=extras,
        positions=positions,
        normals=normals,
        color=color,
    )


def _import_step_shape(path: Path, build123d: Any, *, role: str) -> Any:
    if not path.is_file():
        raise Assembly3DProjectionError(f"{role} STEP is missing: {path}")
    try:
        return build123d.import_step(path)
    except Exception as exc:
        raise Assembly3DProjectionError(f"{role} STEP cannot be loaded: {path}") from exc


def build_assembly_mesh(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    gate_report: MechanicalGateReport,
    target_revision: str,
    graph_id: str,
    refdes_by_component_id: Mapping[str, str],
) -> AssemblyMesh:
    build123d = _load_build123d()
    outline = lane.outline
    plane_z = board_plane_z(lane.enclosure)

    board = build123d.Pos(0, 0, plane_z + outline.thickness_mm / 2) * build123d.Box(
        outline.width_mm, outline.depth_mm, outline.thickness_mm
    )
    for hole in outline.mount_holes:
        board = board - build123d.Pos(
            hole.x_mm - outline.width_mm / 2,
            hole.y_mm - outline.depth_mm / 2,
            plane_z + outline.thickness_mm / 2,
        ) * build123d.Cylinder(hole.diameter_mm / 2, outline.thickness_mm)
    nodes: list[MeshNode] = [
        _tessellated_node(
            shape=board,
            build123d=build123d,
            name="board",
            layer="board",
            source="graph_outline",
            color=_BOARD_COLOR,
            extras=_extras(
                graph_revision=target_revision,
                layer="board",
                source="graph_outline",
                extra={
                    "outline_node_id": outline.node_id,
                    "thickness_mm": outline.thickness_mm,
                    "mount_hole_count": len(outline.mount_holes),
                },
            ),
        )
    ]

    def refdes(component_id: str) -> str:
        return refdes_by_component_id.get(component_id, component_id)

    bodies = sorted(
        (body for body in lane.component_bodies if body.body_type != "none"),
        key=lambda body: (refdes(body.component_id), body.component_id),
    )
    for body in bodies:
        shape = build_component_body_shape(body, plane_z, outline.width_mm, outline.depth_mm)
        nodes.append(
            _tessellated_node(
                shape=shape,
                build123d=build123d,
                name=refdes(body.component_id),
                layer="component",
                source="approximated",
                color=_COMPONENT_COLOR,
                extras=_extras(
                    graph_revision=target_revision,
                    layer="component",
                    source="approximated",
                    extra={
                        "component_id": body.component_id,
                        "refdes": refdes(body.component_id),
                        "body_type": body.body_type,
                        "mounting_side": body.mounting_side,
                        "dimensions_source": body.dimensions_source,
                        "dimensions_source_ref": body.dimensions_source_ref,
                        "note": (
                            "KiCad 3D model not bundled; box approximation from component_bodies"
                        ),
                    },
                ),
            )
        )

    for step_path, name, color in (
        (projection.shell_step_path, "enclosure-shell", _SHELL_COLOR),
        (projection.lid_step_path, "enclosure-lid", _LID_COLOR),
    ):
        shape = _import_step_shape(step_path, build123d, role=name)
        nodes.append(
            _tessellated_node(
                shape=shape,
                build123d=build123d,
                name=name,
                layer="enclosure",
                source="step",
                color=color,
                extras=_extras(
                    graph_revision=target_revision,
                    layer="enclosure",
                    source="step",
                    extra={
                        "step_path": step_path.name,
                        "sha256": _normalized_step_hash(step_path),
                    },
                ),
            )
        )

    assembly = _import_step_shape(projection.assembly_step_path, build123d, role="assembly")
    solids = list(assembly.solids())
    if not solids:
        raise Assembly3DProjectionError("assembly STEP contains no solids")
    interference_volumes: list[float] = []
    interference_nodes: list[tuple[str, MeshNode]] = []
    for body in bodies:
        fused: Any = None
        volume_mm3 = 0.0
        for solid in solids:
            intersection = solid & build_component_body_shape(
                body, plane_z, outline.width_mm, outline.depth_mm
            )
            volume = 0.0 if intersection is None else float(intersection.volume)
            interference_volumes.append(volume)
            if volume > 0:
                volume_mm3 += volume
                fused = intersection if fused is None else fused + intersection
        if fused is None:
            continue
        interference_nodes.append(
            (
                body.component_id,
                _tessellated_node(
                    shape=fused,
                    build123d=build123d,
                    name=f"interference-{refdes(body.component_id)}",
                    layer="interference",
                    source="computed",
                    color=_INTERFERENCE_COLOR,
                    extras=_extras(
                        graph_revision=target_revision,
                        layer="interference",
                        source="computed",
                        extra={
                            "component_id": body.component_id,
                            "refdes": refdes(body.component_id),
                            "interference_volume_mm3": volume_mm3,
                            "measured_max_interference_volume_mm3": (
                                gate_report.measured_max_interference_volume_mm3
                            ),
                        },
                    ),
                ),
            )
        )
    actual_max_volume = max(interference_volumes, default=0.0)
    if not math.isclose(
        actual_max_volume,
        gate_report.measured_max_interference_volume_mm3,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise Assembly3DProjectionError(
            "interference volume does not match mechanical gate measurement"
        )
    nodes.extend(node for _component_id, node in interference_nodes)

    return AssemblyMesh(
        graph_id=graph_id,
        graph_revision=target_revision,
        nodes=tuple(nodes),
    )


def _pad4(data: bytes, padding: bytes) -> bytes:
    remainder = len(data) % 4
    if remainder:
        data += padding * (4 - remainder)
    return data


def _to_gltf_frame(value: tuple[float, float, float]) -> tuple[float, float, float]:
    # CAD millimetres (x, y, z) -> glTF metres, right-handed Y-up (x, z, -y).
    return (value[0] / 1000.0, value[2] / 1000.0, -value[1] / 1000.0)


def _normalized_step_hash(path: Path) -> str:
    try:
        return sha256_bytes(normalize_step(path.read_bytes()))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Assembly3DProjectionError(f"assembly STEP cannot be normalized: {path}") from exc


def _to_gltf_normal(value: tuple[float, float, float]) -> tuple[float, float, float]:
    converted = (value[0], value[2], -value[1])
    norm = math.sqrt(sum(component * component for component in converted))
    if norm == 0.0:
        raise Assembly3DProjectionError("mesh normal is degenerate")
    return (
        converted[0] / norm,
        converted[1] / norm,
        converted[2] / norm,
    )


def write_glb(mesh: AssemblyMesh, path: Path) -> bytes:
    """Serialize ``mesh`` to a deterministic glTF 2.0 binary and write it."""
    if not mesh.nodes:
        raise Assembly3DProjectionError("assembly mesh has no nodes")
    bin_parts: list[bytes] = []
    bin_length = 0
    buffer_views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []

    def add_buffer_view(data: bytes, target: int) -> int:
        nonlocal bin_length
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": bin_length,
                "byteLength": len(data),
                "target": target,
            }
        )
        bin_parts.append(data)
        bin_length += len(data)
        return len(buffer_views) - 1

    for node in mesh.nodes:
        vertex_count = len(node.positions) // 3
        if len(node.positions) != len(node.normals) or vertex_count % 3:
            raise Assembly3DProjectionError(
                f"mesh node {node.name!r} has inconsistent position/normal data"
            )
        points = [
            _to_gltf_frame(
                (
                    node.positions[index * 3],
                    node.positions[index * 3 + 1],
                    node.positions[index * 3 + 2],
                )
            )
            for index in range(vertex_count)
        ]
        normal_values = [
            _to_gltf_normal(
                (
                    node.normals[index * 3],
                    node.normals[index * 3 + 1],
                    node.normals[index * 3 + 2],
                )
            )
            for index in range(vertex_count)
        ]
        position_view = add_buffer_view(
            struct.pack(f"<{vertex_count * 3}f", *(c for p in points for c in p)),
            _TARGET_ARRAY_BUFFER,
        )
        normal_view = add_buffer_view(
            struct.pack(f"<{vertex_count * 3}f", *(c for n in normal_values for c in n)),
            _TARGET_ARRAY_BUFFER,
        )
        index_view = add_buffer_view(
            struct.pack(f"<{vertex_count}I", *range(vertex_count)),
            _TARGET_ELEMENT_ARRAY_BUFFER,
        )
        mins = [min(p[axis] for p in points) for axis in range(3)]
        maxs = [max(p[axis] for p in points) for axis in range(3)]
        position_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": _COMPONENT_FLOAT,
                "count": vertex_count,
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view,
                "componentType": _COMPONENT_FLOAT,
                "count": vertex_count,
                "type": "VEC3",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view,
                "componentType": _COMPONENT_UINT,
                "count": vertex_count,
                "type": "SCALAR",
            }
        )
        materials.append(
            {
                "name": node.name,
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(node.color),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                },
            }
        )
        meshes.append(
            {
                "name": node.name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position_accessor,
                            "NORMAL": normal_accessor,
                        },
                        "indices": index_accessor,
                        "material": len(materials) - 1,
                        "mode": 4,
                    }
                ],
            }
        )
        nodes.append({"mesh": len(meshes) - 1, "name": node.name, "extras": node.extras})

    document = {
        "asset": {
            "version": "2.0",
            "generator": "acd-agent assembly_3d",
            "extras": {
                "graph_id": mesh.graph_id,
                "graph_revision": mesh.graph_revision,
                "source_units": "mm",
                "unit_scale": 0.001,
                "up_axis": "+Y",
                "tessellation": {
                    "linear_deflection_mm": CAD_LINEAR_DEFLECTION_MM,
                    "angular_deflection_deg": CAD_ANGULAR_DEFLECTION_DEG,
                    "tessellator": ("build123d Shape.tessellate (OCP BRepMesh_IncrementalMesh)"),
                },
            },
        },
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "bufferViews": buffer_views,
        "accessors": accessors,
        "buffers": [{"byteLength": bin_length}],
    }
    json_chunk = _pad4(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        b" ",
    )
    bin_chunk = _pad4(b"".join(bin_parts), b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    glb = b"".join(
        [
            struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total),
            struct.pack("<II", len(json_chunk), _CHUNK_JSON),
            json_chunk,
            struct.pack("<II", len(bin_chunk), _CHUNK_BIN),
            bin_chunk,
        ]
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(glb)
    except OSError as exc:
        raise Assembly3DProjectionError(f"GLB could not be written: {path}") from exc
    return glb


def _fail(message: str) -> NoReturn:
    raise Assembly3DProjectionError(f"GLB format check failed: {message}")


def _as_object(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{what} is not an object")
    return cast(dict[str, Any], value)


def _as_list(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{what} is missing or not an array")
    return cast(list[Any], value)


def read_glb_format_check(path: Path, *, expected_node_count: int) -> dict[str, object]:
    """Independently parse a GLB file and return a format check record.

    Uses only ``struct`` and ``json``; shares no data structures with the
    writer. Any structural failure raises :class:`Assembly3DProjectionError`
    (fail-closed).
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Assembly3DProjectionError(f"GLB could not be read: {path}") from exc
    if len(data) < 12:
        _fail("file is shorter than the GLB header")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        _fail("bad magic")
    if version != _GLB_VERSION:
        _fail(f"unsupported GLB version {version}")
    if total != len(data):
        _fail("header length does not match file size")
    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(data):
        if offset + 8 > len(data):
            _fail("truncated chunk header")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if chunk_length % 4:
            _fail("chunk length is not 4-byte aligned")
        if offset + chunk_length > len(data):
            _fail("truncated chunk payload")
        chunks.append((chunk_type, data[offset : offset + chunk_length]))
        offset += chunk_length
    if len(chunks) != 2 or chunks[0][0] != _CHUNK_JSON or chunks[1][0] != _CHUNK_BIN:
        _fail("expected exactly one JSON chunk followed by one BIN chunk")
    json_chunk, bin_chunk = chunks[0][1], chunks[1][1]
    try:
        parsed: Any = json.loads(json_chunk.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Assembly3DProjectionError(
            f"GLB format check failed: JSON chunk does not parse: {exc}"
        ) from exc
    document = _as_object(parsed, "JSON chunk")
    asset = _as_object(document.get("asset"), "asset")
    if asset.get("version") != "2.0":
        _fail("asset.version is not '2.0'")
    if "extensionsUsed" in document or "extensionsRequired" in document:
        _fail("glTF extensions are not allowed")
    buffers = _as_list(document.get("buffers"), "buffers")
    if len(buffers) != 1:
        _fail("expected exactly one buffer")
    buffer = _as_object(buffers[0], "buffer 0")
    if buffer.get("byteLength") != len(bin_chunk):
        _fail("buffer.byteLength does not match the BIN chunk length")
    buffer_views = _as_list(document.get("bufferViews"), "bufferViews")
    accessors = _as_list(document.get("accessors"), "accessors")
    meshes = _as_list(document.get("meshes"), "meshes")
    gltf_nodes = _as_list(document.get("nodes"), "nodes")
    for index, view in enumerate(buffer_views):
        view = _as_object(view, f"bufferView {index}")
        if view.get("buffer") != 0:
            _fail(f"bufferView {index} does not reference buffer 0")
        view_offset = view.get("byteOffset")
        view_length = view.get("byteLength")
        if (
            not isinstance(view_offset, int)
            or not isinstance(view_length, int)
            or view_offset < 0
            or view_length < 0
            or view_offset + view_length > len(bin_chunk)
        ):
            _fail(f"bufferView {index} is out of bounds")
    for index, accessor in enumerate(accessors):
        accessor = _as_object(accessor, f"accessor {index}")
        view_index = accessor.get("bufferView")
        component_type = accessor.get("componentType")
        accessor_type = accessor.get("type")
        count = accessor.get("count")
        if (
            not isinstance(view_index, int)
            or view_index >= len(buffer_views)
            or not isinstance(component_type, int)
            or component_type not in _COMPONENT_SIZES
            or not isinstance(accessor_type, str)
            or accessor_type not in _TYPE_COUNTS
            or not isinstance(count, int)
            or count < 0
        ):
            _fail(f"accessor {index} is malformed")
        byte_offset = accessor.get("byteOffset", 0)
        if not isinstance(byte_offset, int) or byte_offset < 0:
            _fail(f"accessor {index} has an invalid byteOffset")
        view = _as_object(buffer_views[view_index], f"bufferView {view_index}")
        required = (
            byte_offset + count * _COMPONENT_SIZES[component_type] * _TYPE_COUNTS[accessor_type]
        )
        view_length = view.get("byteLength")
        if not isinstance(view_length, int) or required > view_length:
            _fail(f"accessor {index} overruns its bufferView")

    def accessor_data(index: Any) -> tuple[dict[str, Any], bytes]:
        if not isinstance(index, int) or index >= len(accessors):
            _fail("primitive references a missing accessor")
        accessor = _as_object(accessors[index], f"accessor {index}")
        view = _as_object(
            buffer_views[accessor["bufferView"]],
            f"bufferView {accessor['bufferView']}",
        )
        start = int(view["byteOffset"]) + int(accessor.get("byteOffset", 0))
        length = (
            int(accessor["count"])
            * _COMPONENT_SIZES[accessor["componentType"]]
            * _TYPE_COUNTS[accessor["type"]]
        )
        return accessor, bin_chunk[start : start + length]

    triangle_count = 0
    for mesh_index, gltf_mesh in enumerate(meshes):
        gltf_mesh = _as_object(gltf_mesh, f"mesh {mesh_index}")
        primitives = _as_list(gltf_mesh.get("primitives"), f"mesh {mesh_index} primitives")
        if not primitives:
            _fail(f"mesh {mesh_index} has no primitives")
        for primitive in primitives:
            primitive = _as_object(primitive, f"mesh {mesh_index} primitive")
            attributes = _as_object(primitive.get("attributes"), f"mesh {mesh_index} attributes")
            position_accessor, _position_bytes = accessor_data(attributes.get("POSITION"))
            accessor_data(attributes.get("NORMAL"))
            index_accessor, index_bytes = accessor_data(primitive.get("indices"))
            index_component = index_accessor["componentType"]
            if index_component == 5121:
                fmt = "B"
            elif index_component == 5123:
                fmt = "H"
            elif index_component == 5125:
                fmt = "I"
            else:
                _fail("index accessor has an unsupported componentType")
            index_count = int(index_accessor["count"])
            if index_count % 3:
                _fail("index count is not a multiple of 3")
            values = struct.unpack(f"<{index_count}{fmt}", index_bytes)
            position_count = int(position_accessor["count"])
            if any(value >= position_count for value in values):
                _fail("primitive index exceeds the POSITION vertex count")
            triangle_count += index_count // 3
    if len(gltf_nodes) != expected_node_count:
        _fail(f"node count {len(gltf_nodes)} does not match expected {expected_node_count}")
    for index, gltf_node in enumerate(gltf_nodes):
        gltf_node = _as_object(gltf_node, f"node {index}")
        if not isinstance(gltf_node.get("mesh"), int) or not gltf_node.get("name"):
            _fail(f"node {index} lacks a mesh or a name")
    return {
        "checker": "acd.adapters.cad.assembly_3d.read_glb_format_check",
        "checker_version": "1",
        "status": "ok",
        "glb_version": version,
        "byte_length": len(data),
        "json_chunk_length": len(json_chunk),
        "bin_chunk_length": len(bin_chunk),
        "node_count": len(gltf_nodes),
        "mesh_count": len(meshes),
        "accessor_count": len(accessors),
        "triangle_count": triangle_count,
    }


def _relative_input(path: Path, out_dir: Path) -> str:
    try:
        return path.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def generate_assembly_3d_projection(
    *,
    projection: CadProjection,
    lane: MechanicalLane,
    gate_report: MechanicalGateReport,
    target_revision: str,
    graph_id: str,
    refdes_by_component_id: Mapping[str, str],
    out_dir: Path,
) -> Assembly3DRecord:
    """Generate the L3 integrated 3D assembly projection artifacts."""
    build_dir = out_dir / "3d"
    build_dir.mkdir(parents=True, exist_ok=True)
    mesh = build_assembly_mesh(
        projection=projection,
        lane=lane,
        gate_report=gate_report,
        target_revision=target_revision,
        graph_id=graph_id,
        refdes_by_component_id=refdes_by_component_id,
    )
    glb_path = build_dir / "assembly.glb"
    glb_bytes = write_glb(mesh, glb_path)
    format_check = read_glb_format_check(glb_path, expected_node_count=len(mesh.nodes))
    glb_sha256 = "sha256:" + hashlib.sha256(glb_bytes).hexdigest()

    node_summaries = [
        {
            "name": node.name,
            "layer": node.layer,
            "source": node.source,
            "triangle_count": len(node.positions) // 9,
        }
        for node in mesh.nodes
    ]
    approximated_count = sum(1 for node in mesh.nodes if node.source == "approximated")
    interference_count = sum(1 for node in mesh.nodes if node.layer == "interference")
    tessellation = {
        "linear_deflection_mm": CAD_LINEAR_DEFLECTION_MM,
        "angular_deflection_deg": CAD_ANGULAR_DEFLECTION_DEG,
        "tessellator": "build123d Shape.tessellate (OCP BRepMesh_IncrementalMesh)",
    }

    html_path = build_dir / "assembly.html"
    write_assembly_viewer_html(
        glb_bytes=glb_bytes,
        title=f"{graph_id} @ {target_revision} — assembly 3D projection",
        summary={
            "graph_id": graph_id,
            "target_revision": target_revision,
            "level": "L3",
            "tessellation": tessellation,
            "nodes": node_summaries,
            "approximated_component_count": approximated_count,
            "interference_node_count": interference_count,
        },
        output_path=html_path,
    )
    html_sha256 = sha256_bytes(html_path.read_bytes())

    manifest_path = build_dir / "assembly-3d.json"
    manifest = {
        "schema": "acd.assembly-3d/1",
        "level": "L3",
        "pass_authority": False,
        "graph_id": graph_id,
        "target_revision": target_revision,
        "artifacts": {
            "3d/assembly.glb": {
                "sha256": glb_sha256,
                "format_check": format_check,
            },
            "3d/assembly.html": {"sha256": html_sha256},
        },
        "tessellation": tessellation,
        "nodes": node_summaries,
        "viewer": {
            "library": "three.js",
            "version": three_version(),
            "license": "MIT",
        },
        "inputs": {
            _relative_input(step_path, out_dir): _normalized_step_hash(step_path)
            for step_path in (
                projection.shell_step_path,
                projection.lid_step_path,
                projection.assembly_step_path,
            )
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return Assembly3DRecord(
        glb_path=glb_path,
        html_path=html_path,
        manifest_path=manifest_path,
        glb_sha256=glb_sha256,
        html_sha256=html_sha256,
        node_count=len(mesh.nodes),
        triangle_count=cast(int, format_check["triangle_count"]),
        interference_node_count=interference_count,
    )
