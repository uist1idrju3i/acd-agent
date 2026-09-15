"""Tests for the integrated 3D assembly projection (GLB + HTML viewer)."""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest

from acd.adapters.cad.assembly_3d import (
    Assembly3DProjectionError,
    AssemblyMesh,
    MeshNode,
    generate_assembly_3d_projection,
    read_glb_format_check,
    write_glb,
)
from acd.adapters.cad.assembly_viewer import render_assembly_viewer_html
from acd.adapters.cad.component_3d import import_component_step
from acd.adapters.cad.mechanical import run_mechanical_gates
from acd.adapters.cad.project import project_enclosure
from acd.core.electrical import extract_electrical_lane
from acd.core.mechanical import extract_mechanical_lane
from acd.openhands.tools.probe import probe_cad_kernel
from acd.schema.design_graph import DesignGraph


def _tiny_mesh() -> AssemblyMesh:
    node = MeshNode(
        name="tri",
        layer="component",
        source="approximated",
        extras={"graph_revision": "r1", "layer": "component", "source": "approximated"},
        positions=(
            1.0,
            2.0,
            3.0,
            5.0,
            2.0,
            3.0,
            1.0,
            6.0,
            3.0,
            1.0,
            2.0,
            7.0,
            5.0,
            2.0,
            7.0,
            1.0,
            6.0,
            7.0,
        ),
        normals=(
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
        ),
        color=(0.5, 0.5, 0.5, 1.0),
    )
    return AssemblyMesh(graph_id="g", graph_revision="r1", nodes=(node,))


def test_write_glb_roundtrips_through_independent_reader(tmp_path: Path) -> None:
    glb_path = tmp_path / "assembly.glb"
    first = write_glb(_tiny_mesh(), glb_path)
    check = read_glb_format_check(glb_path, expected_node_count=1)
    assert check["status"] == "ok"
    assert check["triangle_count"] == 2
    assert check["node_count"] == 1
    assert check["byte_length"] == len(first)

    second_path = tmp_path / "second.glb"
    second = write_glb(_tiny_mesh(), second_path)
    assert first == second


def test_write_glb_converts_mm_cad_frame_to_meters_y_up(tmp_path: Path) -> None:
    glb_path = tmp_path / "assembly.glb"
    write_glb(_tiny_mesh(), glb_path)
    data = glb_path.read_bytes()
    json_length, _chunk_type = struct.unpack_from("<II", data, 12)
    document = json.loads(data[20 : 20 + json_length].decode("utf-8"))
    accessor = document["accessors"][0]
    assert accessor["type"] == "VEC3"
    # CAD (1, 2, 3) mm -> glTF (0.001, 0.003, -0.002) m.
    view = document["bufferViews"][accessor["bufferView"]]
    offset = 12 + 8 + json_length + 8 + view["byteOffset"] + accessor.get("byteOffset", 0)
    x, y, z = struct.unpack_from("<fff", data, offset)
    assert (x, y, z) == pytest.approx((0.001, 0.003, -0.002), abs=1e-7)
    assert accessor["min"][0] == pytest.approx(0.001, abs=1e-7)


def test_reader_rejects_corrupt_magic(tmp_path: Path) -> None:
    glb_path = tmp_path / "bad.glb"
    write_glb(_tiny_mesh(), glb_path)
    data = bytearray(glb_path.read_bytes())
    data[0:4] = b"XXXX"
    glb_path.write_bytes(bytes(data))
    with pytest.raises(Assembly3DProjectionError, match="bad magic"):
        read_glb_format_check(glb_path, expected_node_count=1)


def test_reader_rejects_truncated_file(tmp_path: Path) -> None:
    glb_path = tmp_path / "truncated.glb"
    write_glb(_tiny_mesh(), glb_path)
    glb_path.write_bytes(glb_path.read_bytes()[:-16])
    with pytest.raises(Assembly3DProjectionError, match="format check failed"):
        read_glb_format_check(glb_path, expected_node_count=1)


def test_reader_rejects_accessor_overrun(tmp_path: Path) -> None:
    glb_path = tmp_path / "overrun.glb"
    write_glb(_tiny_mesh(), glb_path)
    data = bytearray(glb_path.read_bytes())
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(bytes(data[20 : 20 + json_length]).decode("utf-8"))
    document["accessors"][0]["count"] = 10**9
    patched = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    patched += b" " * (-len(patched) % 4)
    if len(patched) != json_length:
        pytest.skip("patched JSON chunk length differs; skip byte-level mutation")
    data[12:16] = struct.pack("<I", len(patched))
    data[20 : 20 + json_length] = patched
    glb_path.write_bytes(bytes(data))
    with pytest.raises(Assembly3DProjectionError, match="overruns its bufferView"):
        read_glb_format_check(glb_path, expected_node_count=1)


def test_reader_rejects_wrong_node_count(tmp_path: Path) -> None:
    glb_path = tmp_path / "nodes.glb"
    write_glb(_tiny_mesh(), glb_path)
    with pytest.raises(Assembly3DProjectionError, match="node count"):
        read_glb_format_check(glb_path, expected_node_count=2)


def _fixture() -> tuple[DesignGraph, Path]:
    fixture_dir = Path("fixtures/golden-design-1")
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    return graph, fixture_dir / "graph.json"


def _generate(out_dir: Path):
    graph, graph_path = _fixture()
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=out_dir,
        target_revision=graph.revision,
    )
    gates = run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=probe_cad_kernel(),
    )
    refdes = {
        component.node_id: component.refdes
        for component in extract_electrical_lane(graph).components
    }
    record = generate_assembly_3d_projection(
        projection=projection,
        lane=lane,
        gate_report=gates,
        target_revision=graph.revision,
        graph_id=graph.graph_id,
        refdes_by_component_id=refdes,
        out_dir=out_dir,
    )
    return graph, lane, record


def test_assembly_3d_projection_on_golden_fixture(tmp_path: Path) -> None:
    graph, lane, record = _generate(tmp_path / "out")
    manifest = json.loads((tmp_path / "out/3d/assembly-3d.json").read_text(encoding="utf-8"))
    names = [node["name"] for node in manifest["nodes"]]
    assert names[0] == "board"
    assert "enclosure-shell" in names
    assert "enclosure-lid" in names
    expected_refdes = {
        component.refdes
        for component in extract_electrical_lane(graph).components
        if lane.body_for_component(component.node_id).body_type != "none"
    }
    assert expected_refdes <= set(names)
    sources = {node["name"]: node["source"] for node in manifest["nodes"]}
    assert sources["board"] == "graph_outline"
    assert sources["enclosure-shell"] == "step"
    for refdes in expected_refdes:
        assert sources[refdes] == "approximated"
    check = manifest["artifacts"]["3d/assembly.glb"]["format_check"]
    assert check["status"] == "ok"
    assert manifest["level"] == "L3"
    assert manifest["pass_authority"] is False

    html = (tmp_path / "out/3d/assembly.html").read_text(encoding="utf-8")
    assert 'type="importmap"' in html
    embedded_b64 = html.split('id="assembly-glb"', 1)[1].split(">", 1)[1].split("<", 1)[0]
    assert base64.b64decode(embedded_b64) == (tmp_path / "out/3d/assembly.glb").read_bytes()
    assert record.glb_sha256 == manifest["artifacts"]["3d/assembly.glb"]["sha256"]


def test_assembly_3d_projection_uses_real_component_solids(tmp_path: Path) -> None:
    graph, graph_path = _fixture()
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=tmp_path / "out",
        target_revision=graph.revision,
    )
    gates = run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=probe_cad_kernel(),
    )
    refdes = {
        component.node_id: component.refdes
        for component in extract_electrical_lane(graph).components
    }
    imported = import_component_step(
        Path("fixtures/component-3d/gd1-components.step"),
        lane,
        refdes_by_component_id=refdes,
    )
    record = generate_assembly_3d_projection(
        projection=projection,
        lane=lane,
        gate_report=gates,
        target_revision=graph.revision,
        graph_id=graph.graph_id,
        refdes_by_component_id=refdes,
        out_dir=tmp_path / "out",
        component_solids=imported.component_solids,
    )
    manifest = json.loads((tmp_path / "out/3d/assembly-3d.json").read_text(encoding="utf-8"))
    sources = {node["name"]: node["source"] for node in manifest["nodes"]}
    assert sources["U1"] == "kicad_step"
    assert sources["J1"] == "kicad_step"
    assert record.glb_sha256.startswith("sha256:")


def test_assembly_3d_projection_is_deterministic(tmp_path: Path) -> None:
    _graph, _lane, first = _generate(tmp_path / "first")
    _graph, _lane, second = _generate(tmp_path / "second")
    assert first.glb_sha256 == second.glb_sha256
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert first_manifest == second_manifest


def test_viewer_import_map_embeds_all_vendored_modules() -> None:
    html = render_assembly_viewer_html(glb_bytes=b"x", title="t", summary={"k": "v"})
    import_map_json = html.split('type="importmap">', 1)[1].split("</script>", 1)[0]
    imports = json.loads(import_map_json)["imports"]
    expected_specifiers = {
        "three",
        "three-core",
        "three-orbit-controls",
        "three-gltf-loader",
        "three-buffer-geometry-utils",
        "three-skeleton-utils",
    }
    assert set(imports) == expected_specifiers
    assert len(imports) == 6
    for url in imports.values():
        prefix = "data:text/javascript;base64,"
        assert url.startswith(prefix)
        source = base64.b64decode(url[len(prefix) :]).decode("utf-8")
        assert "from './" not in source
        assert "from '../" not in source
        assert 'import "./' not in source
    three_module = base64.b64decode(imports["three"][len("data:text/javascript;base64,") :]).decode(
        "utf-8"
    )
    assert "from 'three-core'" in three_module
    assert "three.core.js" not in three_module


def test_generate_fails_closed_on_corrupt_glb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, graph_path = _fixture()
    lane = extract_mechanical_lane(graph)
    projection = project_enclosure(
        lane,
        graph_path=graph_path,
        out_dir=tmp_path / "out",
        target_revision=graph.revision,
    )
    gates = run_mechanical_gates(
        step_path=projection.assembly_step_path,
        lane=lane,
        kernel_probe=probe_cad_kernel(),
    )
    refdes = {
        component.node_id: component.refdes
        for component in extract_electrical_lane(graph).components
    }
    from acd.adapters.cad import assembly_3d

    def corrupt_write(mesh: AssemblyMesh, path: Path) -> bytes:
        data = bytearray(_write_glb(mesh, path))
        data[0:4] = b"XXXX"
        path.write_bytes(bytes(data))
        return bytes(data)

    _write_glb = assembly_3d.write_glb
    monkeypatch.setattr(assembly_3d, "write_glb", corrupt_write)
    with pytest.raises(Assembly3DProjectionError):
        generate_assembly_3d_projection(
            projection=projection,
            lane=lane,
            gate_report=gates,
            target_revision=graph.revision,
            graph_id=graph.graph_id,
            refdes_by_component_id=refdes,
            out_dir=tmp_path / "out",
        )
    assert not (tmp_path / "out/3d/assembly.html").exists()
