"""Tests for deterministic system and power-tree SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Literal, get_args

import pytest

import acd.adapters.svg.system as system_module
from acd.adapters.svg.system import (
    SvgSystemRenderer,
    SvgVisualProjectionError,
    generate_system_visual_projections,
)
from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.visual_projection import measure_svg_resolution
from acd.schema.design_graph import DesignGraph, GraphNode, NodeKind

ROOT = Path(__file__).parents[3]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )


def _lane(graph: DesignGraph) -> ElectricalLane:
    return extract_electrical_lane(graph)


def _generate(
    tmp_path: Path,
    *,
    graph: DesignGraph | None = None,
    lane: ElectricalLane | None = None,
    renderer: SvgSystemRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "graph.json"
    source.write_text('{"revision":"golden-design-1-r1"}\n', encoding="utf-8")
    graph = graph or _graph()
    return generate_system_visual_projections(
        project_name="gd1",
        out_dir=tmp_path / "out",
        source_revision=graph.revision,
        graph=graph,
        lane=lane or _lane(graph),
        authoritative_inputs=(source,),
        input_base_dir=tmp_path,
        renderer=renderer,
        projection_ids=projection_ids,
    )


def test_generates_block_and_power_tree_with_shared_provenance(tmp_path: Path) -> None:
    projection_set = _generate(tmp_path)

    assert projection_set.pass_evidence is False
    assert [record.projection_type for record in projection_set.projections] == [
        "power_tree_view",
        "system_block_view",
    ]
    assert all(record.domain == "system" for record in projection_set.projections)
    assert all(record.renderer.renderer_type == "acd-svg" for record in projection_set.projections)
    assert all(
        record.regeneration_check.status == "reproduced"
        for record in projection_set.projections
    )
    assert all(record.input_files[0].path == "graph.json" for record in projection_set.projections)
    assert (tmp_path / "out/visual-projections-system.json").is_file()

    block = next(
        record for record in projection_set.projections
        if record.projection_type == "system_block_view"
    )
    block_svg = (tmp_path / "out" / block.image_path).read_bytes()
    assert b'id="system-block"' in block_svg
    assert b'id="block-kind-electrical-component"' in block_svg
    assert b'id="block-kind-electrical-board"' in block_svg
    assert b'id="block-edge-board-gd1-comp-u1"' in block_svg
    assert b"2026-" not in block_svg
    assert b"/home/" not in block_svg
    assert measure_svg_resolution(block_svg).view_box == (0.0, 0.0, 240.0, 498.0)

    power = next(
        record for record in projection_set.projections
        if record.projection_type == "power_tree_view"
    )
    power_svg = (tmp_path / "out" / power.image_path).read_bytes()
    assert b'id="power-tree"' in power_svg
    assert b'id="power-net-net-vbus-5v"' in power_svg
    assert b'id="power-net-net-gnd"' not in power_svg
    assert b"5.0 V" in power_svg
    assert measure_svg_resolution(power_svg).view_box == (0.0, 0.0, 240.0, 90.0)

    second = _generate(tmp_path / "second")
    assert projection_set.identity_hash == second.identity_hash
    assert [record.image_hash for record in projection_set.projections] == [
        record.image_hash for record in second.projections
    ]


def test_input_file_missing_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    with pytest.raises(SvgVisualProjectionError, match="missing"):
        generate_system_visual_projections(
            project_name="gd1",
            out_dir=tmp_path / "out",
            source_revision=graph.revision,
            graph=graph,
            lane=_lane(graph),
            authoritative_inputs=(tmp_path / "missing.json",),
            input_base_dir=tmp_path,
        )


def test_unknown_renderer_version_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SvgVisualProjectionError, match="unknown"):
        _generate(tmp_path, renderer=SvgSystemRenderer(tool_version="unknown"))


def test_duplicate_projection_ids_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SvgVisualProjectionError, match="identifiers"):
        _generate(tmp_path, projection_ids=("same", "same"))


def test_second_generation_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    class NonDeterministicRenderer(SvgSystemRenderer):
        writes = 0

        def _write_svg(
            self,
            *,
            projection_type: Literal["system_block_view", "power_tree_view"],
            graph: DesignGraph,
            lane: ElectricalLane,
            output_path: Path,
        ) -> None:
            super()._write_svg(
                projection_type=projection_type,
                graph=graph,
                lane=lane,
                output_path=output_path,
            )
            self.writes += 1
            if self.writes == 2:
                output_path.write_bytes(output_path.read_bytes() + b" ")

    with pytest.raises(SvgVisualProjectionError, match="regeneration"):
        _generate(tmp_path, renderer=NonDeterministicRenderer())


def test_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    with pytest.raises(SvgVisualProjectionError, match="revision"):
        generate_system_visual_projections(
            project_name="gd1",
            out_dir=tmp_path / "out",
            source_revision="different-revision",
            graph=graph,
            lane=_lane(graph),
            authoritative_inputs=(tmp_path / "graph.json",),
            input_base_dir=tmp_path,
        )


def test_unknown_node_kind_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    unknown = GraphNode.model_construct(
        id="unknown.node",
        kind="unknown.node",
        attrs={},
        depends_on=[],
    )
    graph = graph.model_copy(update={"nodes": [*graph.nodes, unknown]})
    with pytest.raises(SvgVisualProjectionError, match="unknown node"):
        _generate(tmp_path, graph=graph)


def test_empty_block_dependencies_fail_closed(tmp_path: Path) -> None:
    graph = _graph()
    drawable_kinds = {
        "electrical.board",
        "electrical.component",
        "electrical.net",
        "firmware.module",
        "safety.boundary",
    }
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"depends_on": []})
                if node.kind in drawable_kinds
                else node
                for node in graph.nodes
            ]
        }
    )
    with pytest.raises(SvgVisualProjectionError, match="depends_on"):
        _generate(tmp_path, graph=graph)


def test_incomplete_block_node_kind_partition_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        system_module,
        "_KNOWN_NODE_KINDS",
        frozenset((*get_args(NodeKind), "future.node")),
    )
    with pytest.raises(SvgVisualProjectionError, match="classification"):
        _generate(tmp_path)


def test_power_net_absent_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    with pytest.raises(SvgVisualProjectionError, match="no declared power rails"):
        _generate(
            tmp_path,
            lane=replace(
                lane,
                nets=tuple(replace(net, power_rail=False) for net in lane.nets),
            ),
        )


def test_voltage_undeclared_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    lane = replace(
        lane,
        nets=tuple(
            replace(net, voltage_nominal_v=None)
            if net.power_rail
            else net
            for net in lane.nets
        ),
    )
    with pytest.raises(SvgVisualProjectionError, match="voltage declaration"):
        _generate(tmp_path, lane=lane)


def test_power_voltage_nonfinite_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    nets = tuple(
        replace(net, voltage_nominal_v=float("nan"))
        if net.node_id == "net.vbus_5v"
        else net
        for net in lane.nets
    )
    with pytest.raises(SvgVisualProjectionError, match="voltage declaration"):
        _generate(tmp_path, lane=replace(lane, nets=nets))


def test_power_net_without_pin_connection_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    pins = tuple(pin for pin in lane.pins if pin.net_id != "net.vbus_5v")
    with pytest.raises(SvgVisualProjectionError, match="connected to the rail"):
        _generate(tmp_path, lane=replace(lane, pins=pins))


def test_power_source_not_identified_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    nets = tuple(
        replace(net, power_source_pin="req.gd1-req-001")
        if net.node_id == "net.vbus_5v"
        else net
        for net in lane.nets
    )
    with pytest.raises(SvgVisualProjectionError, match=r"not an electrical\.pin"):
        _generate(tmp_path, lane=replace(lane, nets=nets))


def test_power_source_pin_id_missing_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    nets = tuple(
        replace(net, power_source_pin="pin.missing")
        if net.node_id == "net.vbus_5v"
        else net
        for net in lane.nets
    )
    with pytest.raises(SvgVisualProjectionError, match="does not exist"):
        _generate(tmp_path, lane=replace(lane, nets=nets))


def test_power_source_pin_wrong_net_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    nets = tuple(
        replace(net, power_source_pin="pin.u2.2")
        if net.node_id == "net.vbus_5v"
        else net
        for net in lane.nets
    )
    with pytest.raises(SvgVisualProjectionError, match="connected to the rail"):
        _generate(tmp_path, lane=replace(lane, nets=nets))


def test_power_source_pin_missing_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    nets = tuple(
        replace(net, power_source_pin=None)
        if net.node_id == "net.vbus_5v"
        else net
        for net in lane.nets
    )
    with pytest.raises(SvgVisualProjectionError, match="undeclared"):
        _generate(tmp_path, lane=replace(lane, nets=nets))


def test_power_rail_without_load_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    lane = _lane(graph)
    pins = tuple(
        pin
        for pin in lane.pins
        if not (
            pin.net_id == "net.vbus_5v" and pin.node_id != "pin.j1.a4"
        )
    )
    with pytest.raises(SvgVisualProjectionError, match="no load pin"):
        _generate(tmp_path, lane=replace(lane, pins=pins))
