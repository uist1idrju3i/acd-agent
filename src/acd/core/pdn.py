"""Deterministic, non-authoritative PCB power-path resistance estimates."""

from __future__ import annotations

import hashlib
import heapq
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.core.copper import (
    copper_cross_section_mm2,
    copper_resistance_ohm,
    via_resistance_ohm,
)
from acd.core.electrical import extract_electrical_lane
from acd.core.sexpr import SExpr, parse_one
from acd.schema import (
    PdnAnalysisRequest,
    PdnPathRequest,
    PdnPathResult,
    PdnResult,
    PdnSegmentResult,
    PdnViaResult,
)
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph

SNAP_TOLERANCE_MM = 0.01
DEFAULT_VIA_PLATING_UM = 25.0


@dataclass(frozen=True)
class _Pad:
    refdes: str
    net: str
    point: tuple[float, float]
    layers: tuple[str, ...]


@dataclass(frozen=True)
class _Segment:
    net: str
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float


@dataclass(frozen=True)
class _Via:
    net: str
    point: tuple[float, float]
    drill_mm: float
    layers: tuple[str, ...]
    plating_um: float = DEFAULT_VIA_PLATING_UM


@dataclass(frozen=True)
class _Edge:
    target: tuple[str, float, float]
    resistance_ohm: float
    segment: _Segment | None = None
    via: _Via | None = None


@dataclass(frozen=True)
class _Board:
    pads: tuple[_Pad, ...]
    segments: tuple[_Segment, ...]
    vias: tuple[_Via, ...]
    zone_nets: frozenset[str]


def _tag(node: SExpr) -> str | None:
    return str(node[0]) if isinstance(node, list) and node else None


def _child(node: SExpr, tag: str) -> list[SExpr] | None:
    if not isinstance(node, list):
        return None
    return next(
        (
            child
            for child in node[1:]
            if isinstance(child, list) and child and str(child[0]) == tag
        ),
        None,
    )


def _number(value: SExpr) -> float:
    number = float(str(value))
    if not math.isfinite(number):
        raise ValueError("non-finite PCB coordinate")
    return number


def _at(node: SExpr) -> tuple[float, float, float]:
    values = _child(node, "at")
    if values is None or len(values) < 3:
        raise ValueError("PCB object is missing at coordinates")
    return _number(values[1]), _number(values[2]), (
        _number(values[3]) if len(values) > 3 else 0.0
    )


def _transform(
    local: tuple[float, float],
    origin: tuple[float, float, float],
) -> tuple[float, float]:
    radians = math.radians(origin[2])
    x = local[0] * math.cos(radians) + local[1] * math.sin(radians)
    y = -local[0] * math.sin(radians) + local[1] * math.cos(radians)
    return origin[0] + x, origin[1] + y


def _parse_kicad(path: Path) -> _Board:
    root = parse_one(path.read_text(encoding="utf-8"))
    if _tag(root) != "kicad_pcb":
        raise ValueError("source is not a kicad_pcb document")
    pads: list[_Pad] = []
    segments: list[_Segment] = []
    vias: list[_Via] = []
    zone_nets: set[str] = set()
    for item in cast(list[SExpr], root)[1:]:
        tag = _tag(item)
        if tag == "segment":
            start = _child(item, "start")
            end = _child(item, "end")
            width = _child(item, "width")
            layer = _child(item, "layer")
            net = _child(item, "net")
            if (
                start is None
                or end is None
                or width is None
                or layer is None
                or net is None
                or len(start) < 3
                or len(end) < 3
                or len(width) < 2
                or len(layer) < 2
                or len(net) < 2
            ):
                raise ValueError("malformed PCB segment")
            segments.append(
                _Segment(
                    str(net[1]),
                    str(layer[1]),
                    (_number(start[1]), _number(start[2])),
                    (_number(end[1]), _number(end[2])),
                    _number(width[1]),
                )
            )
        elif tag == "via":
            at = _child(item, "at")
            drill = _child(item, "drill")
            layers = _child(item, "layers")
            net = _child(item, "net")
            if (
                at is None
                or drill is None
                or layers is None
                or net is None
                or len(at) < 3
                or len(drill) < 2
                or len(layers) < 3
                or len(net) < 2
            ):
                raise ValueError("malformed PCB via")
            vias.append(
                _Via(
                    str(net[1]),
                    (_number(at[1]), _number(at[2])),
                    _number(drill[1]),
                    tuple(str(value) for value in layers[1:] if not isinstance(value, list)),
                )
            )
        elif tag == "zone":
            net = _child(item, "net")
            if net is not None and len(net) > 1:
                zone_nets.add(str(net[1]))
        elif tag == "footprint":
            footprint_at = _at(item)
            refdes = None
            for child in item[1:]:
                if (
                    isinstance(child, list)
                    and len(child) > 2
                    and str(child[0]) == "property"
                    and str(child[1]) == "Reference"
                ):
                    refdes = str(child[2])
                    break
            if refdes is None:
                for child in item[1:]:
                    if (
                        isinstance(child, list)
                        and len(child) > 2
                        and str(child[0]) == "fp_text"
                        and str(child[1]) == "reference"
                    ):
                        refdes = str(child[2])
                        break
            if refdes is None:
                continue
            for child in item[1:]:
                if not isinstance(child, list) or not child or str(child[0]) != "pad":
                    continue
                pad_at = _child(child, "at")
                size = _child(child, "size")
                net = _child(child, "net")
                layers = _child(child, "layers")
                if (
                    pad_at is None
                    or size is None
                    or net is None
                    or len(pad_at) < 3
                    or len(size) < 3
                    or len(net) < 2
                ):
                    continue
                pad_layers = (
                    tuple(str(value) for value in layers[1:] if not isinstance(value, list))
                    if layers is not None
                    else ("F.Cu", "B.Cu")
                )
                pads.append(
                    _Pad(
                        refdes,
                        str(net[1]),
                        _transform((_number(pad_at[1]), _number(pad_at[2])), footprint_at),
                        pad_layers,
                    )
                )
    return _Board(tuple(pads), tuple(segments), tuple(vias), frozenset(zone_nets))


def _parse_source(path: Path, kind: str) -> _Board | None:
    if kind == "kicad_pcb":
        return _parse_kicad(path)
    if not path.exists():
        raise ValueError(f"source path does not exist: {path}")
    files = sorted(path.glob("*")) if path.is_dir() else [path]
    if not files:
        raise ValueError("Gerber source directory is empty")
    # Gerber object attribution is format-specific.  The existing Gerber
    # adapter validates objects, while this estimate remains unknown unless
    # a deterministic X2 net attribution is available.
    for file in files:
        if file.is_file():
            file.read_bytes()
    return None


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_dir():
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(child.read_bytes())
    else:
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _node_for(
    nodes: set[tuple[str, float, float]],
    layer: str,
    point: tuple[float, float],
) -> tuple[str, float, float]:
    for existing in sorted(nodes):
        if existing[0] == layer and math.dist(existing[1:], point) <= SNAP_TOLERANCE_MM:
            return existing
    node = (layer, round(point[0], 6), round(point[1], 6))
    nodes.add(node)
    return node


def _path_for(
    board: _Board,
    path: PdnPathRequest,
    thickness_um: float,
    request: PdnAnalysisRequest,
) -> PdnPathResult:
    relevant_segments = [segment for segment in board.segments if segment.net == path.net]
    relevant_vias = [via for via in board.vias if via.net == path.net]
    nodes: set[tuple[str, float, float]] = set()
    edges: dict[tuple[str, float, float], list[_Edge]] = {}

    def add_edge(source: tuple[str, float, float], edge: _Edge) -> None:
        edges.setdefault(source, []).append(edge)

    for segment in relevant_segments:
        start = _node_for(nodes, segment.layer, segment.start)
        end = _node_for(nodes, segment.layer, segment.end)
        resistance = copper_resistance_ohm(
            math.dist(segment.start, segment.end),
            segment.width_mm,
            thickness_um,
            request.copper.resistivity_ohm_mm,
            request.copper.temperature_c,
            request.copper.temp_coeff_per_c,
        )
        add_edge(start, _Edge(end, resistance, segment=segment))
        add_edge(end, _Edge(start, resistance, segment=segment))
    for via in relevant_vias:
        via_nodes = [
            _node_for(nodes, layer, via.point)
            for layer in via.layers
        ]
        resistance = via_resistance_ohm(
            via.drill_mm,
            via.plating_um,
            request.copper.resistivity_ohm_mm,
            request.copper.temperature_c,
            request.copper.temp_coeff_per_c,
        )
        for source in via_nodes:
            for target in via_nodes:
                if source != target:
                    add_edge(source, _Edge(target, resistance, via=via))

    source_pads = [
        pad for pad in board.pads if pad.net == path.net and pad.refdes == path.source_refdes
    ]
    sink_pads = [
        pad for pad in board.pads if pad.net == path.net and pad.refdes == path.sink_refdes
    ]
    source_nodes = {
        _node_for(nodes, layer, pad.point)
        for pad in source_pads
        for layer in pad.layers
        if any(
            math.dist(node[1:], pad.point) <= SNAP_TOLERANCE_MM
            and node[0] == layer
            for node in nodes
        )
    }
    sink_nodes = {
        _node_for(nodes, layer, pad.point)
        for pad in sink_pads
        for layer in pad.layers
        if any(
            math.dist(node[1:], pad.point) <= SNAP_TOLERANCE_MM
            and node[0] == layer
            for node in nodes
        )
    }
    queue: list[
        tuple[float, tuple[str, float, float], int, tuple[_Edge, ...]]
    ] = [(0.0, node, index, ()) for index, node in enumerate(sorted(source_nodes))]
    sequence = len(queue)
    distances: dict[tuple[str, float, float], float] = {
        node: 0.0 for node in source_nodes
    }
    found: tuple[_Edge, ...] | None = None
    while queue:
        distance, node, _, history = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node in sink_nodes:
            found = history
            break
        for edge in sorted(
            edges.get(node, []),
            key=lambda item: (
                item.target,
                item.resistance_ohm,
                item.segment.layer if item.segment else "",
            ),
        ):
            candidate = distance + edge.resistance_ohm
            if candidate < distances.get(edge.target, math.inf):
                distances[edge.target] = candidate
                heapq.heappush(
                    queue,
                    (candidate, edge.target, sequence, (*history, edge)),
                )
                sequence += 1

    findings: list[str] = []
    if found is None:
        findings.append("open path in copper")
        return PdnPathResult(
            path_id=path.path_id,
            net=path.net,
            status="fail",
            findings=findings,
        )
    segment_results: list[PdnSegmentResult] = []
    via_results: list[PdnViaResult] = []
    for edge in found:
        if edge.segment is not None:
            length = math.dist(edge.segment.start, edge.segment.end)
            cross_section = copper_cross_section_mm2(
                edge.segment.width_mm,
                thickness_um,
            )
            density = path.current_a / cross_section
            segment_results.append(
                PdnSegmentResult(
                    layer=edge.segment.layer,
                    length_mm=length,
                    width_mm=edge.segment.width_mm,
                    cross_section_mm2=cross_section,
                    resistance_mohm=edge.resistance_ohm * 1000.0,
                    current_density=density,
                )
            )
        elif edge.via is not None:
            via_results.append(
                PdnViaResult(
                    drill_mm=edge.via.drill_mm,
                    plating_um=edge.via.plating_um,
                    resistance_mohm=edge.resistance_ohm * 1000.0,
                )
            )
    total_ohm = sum(edge.resistance_ohm for edge in found)
    ir_drop_mv = path.current_a * total_ohm * 1000.0
    worst_density = max(
        (segment.current_density for segment in segment_results),
        default=None,
    )
    status = "pass"
    if ir_drop_mv > path.max_ir_drop_mv:
        status = "fail"
        findings.append("maximum IR drop exceeded")
    if (
        worst_density is not None
        and worst_density > path.max_current_density_a_per_mm2
    ):
        status = "fail"
        findings.append("maximum current density exceeded")
    zone_on_path = path.net in board.zone_nets
    if zone_on_path:
        findings.append("copper pour on path; deterministic width estimate not available")
        if status == "pass":
            status = "unknown"
    return PdnPathResult(
        path_id=path.path_id,
        net=path.net,
        segments=segment_results,
        vias=via_results,
        total_resistance_mohm=total_ohm * 1000.0,
        ir_drop_mv=ir_drop_mv,
        worst_current_density=worst_density,
        status=status,
        findings=findings,
        zone_on_path=zone_on_path,
    )


def analyze_pdn(
    graph: DesignGraph,
    request: PdnAnalysisRequest,
    board_source_path: Path,
) -> PdnResult:
    """Estimate requested copper paths without mutating the design graph."""
    if graph.graph_id != request.graph_id or graph.revision != request.revision:
        raise ValueError("graph and request identity/revision mismatch")
    lane = extract_electrical_lane(graph)
    known_nets = {net.name for net in lane.nets}
    unknown_nets = sorted({path.net for path in request.paths} - known_nets)
    if unknown_nets:
        raise ValueError(f"unknown net(s): {unknown_nets}")
    thickness_um = request.copper.thickness_um
    if thickness_um is None:
        thickness_um = lane.board.outer_copper_thickness_um
    input_hashes = {
        "board": _source_hash(board_source_path),
        "graph": canonical_sha256(graph),
        "request": canonical_sha256(request),
    }
    board = _parse_source(board_source_path, request.source.kind)
    if board is None:
        paths = [
            PdnPathResult(
                path_id=path.path_id,
                net=path.net,
                status="unknown",
                findings=[
                    "Gerber net attribution is unavailable; deterministic X2 attribution required"
                ],
            )
            for path in sorted(request.paths, key=lambda item: item.path_id)
        ]
    elif thickness_um is None:
        paths = [
            PdnPathResult(
                path_id=path.path_id,
                net=path.net,
                status="unknown",
                findings=["copper thickness is unavailable"],
            )
            for path in sorted(request.paths, key=lambda item: item.path_id)
        ]
    else:
        paths = [
            _path_for(board, path, thickness_um, request)
            for path in sorted(request.paths, key=lambda item: item.path_id)
        ]
    statuses = {path.status for path in paths}
    status = (
        "fail"
        if "fail" in statuses
        else "unknown"
        if "unknown" in statuses
        else "pass"
    )
    return PdnResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        paths=paths,
        input_hashes=input_hashes,
        tool_versions={"acd-pdn": "0.1"},
    )


def pdn_markdown(result: PdnResult) -> str:
    lines = [
        "# PDN/IR drop estimate",
        "",
        "権限: `estimate`（L2停止側所見、authoritative Evidenceではない）",
        "",
        "| Path | Net | Status | Resistance (mΩ) | IR drop (mV) | Worst J (A/mm²) | Findings |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for path in result.paths:
        lines.append(
            "| "
            + " | ".join(
                [
                    path.path_id,
                    path.net,
                    path.status,
                    ""
                    if path.total_resistance_mohm is None
                    else f"{path.total_resistance_mohm:.9f}",
                    "" if path.ir_drop_mv is None else f"{path.ir_drop_mv:.9f}",
                    ""
                    if path.worst_current_density is None
                    else f"{path.worst_current_density:.9f}",
                    "; ".join(path.findings),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


__all__ = ["analyze_pdn", "pdn_markdown"]
