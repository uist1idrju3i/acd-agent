"""Synthetic tests for deterministic decoupling placement exploration."""
# pyright: reportUnknownParameterType=false,reportMissingParameterType=false,reportUnknownMemberType=false,reportUnknownLambdaType=false,reportUnknownVariableType=false,reportUnknownArgumentType=false,reportPrivateUsage=false,reportArgumentType=false,reportIndexIssue=false

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from acd.core import decoupling_placement as placement
from acd.core.electrical import ComponentView, ElectricalLane, extract_electrical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE_DIR = Path("fixtures/golden-design-1")


def _graph(*, rotation_fixed: bool = False) -> DesignGraph:
    graph = DesignGraph.model_validate_json(
        (FIXTURE_DIR / "graph.json").read_text(encoding="utf-8")
    )
    nodes = []
    for node in graph.nodes:
        if node.attrs.get("refdes") != "C4":
            nodes.append(node)
            continue
        attrs = {
            key: value
            for key, value in node.attrs.items()
            if not key.startswith("cpl_rotation_")
        }
        attrs.update(
            {
                "placement_x_mm": 20.0,
                "placement_y_mm": 20.0,
                "placement_rotation_deg": 0.0,
            }
        )
        if rotation_fixed:
            attrs["cpl_rotation_polarized"] = True
        nodes.append(node.model_copy(update={"attrs": attrs}))
    return graph.model_copy(update={"nodes": nodes})


def _lane(graph: DesignGraph, refs: set[str]) -> ElectricalLane:
    lane = extract_electrical_lane(graph)
    components = tuple(item for item in lane.components if item.refdes in refs)
    component_ids = {item.node_id for item in components}
    pins = tuple(item for item in lane.pins if item.component_id in component_ids)
    return replace(lane, components=components, pins=pins)


def _patch_geometry(
    monkeypatch: pytest.MonkeyPatch, lane: ElectricalLane, *, blocked: bool
) -> None:
    monkeypatch.setattr(placement, "extract_electrical_lane", lambda graph: lane)
    monkeypatch.setattr(
        placement,
        "component_net_pad_positions",
        lambda graph, current_lane, component, net_id, fixture_dir, library: (
            ("1", (0.0, 0.0)),
        ),
    )
    monkeypatch.setattr(
        placement,
        "_pad_offsets",
        lambda graph, current_lane, component, net_id, fixture_dir, library, **kwargs: (
            ("1", (0.0, 0.0)),
        ),
    )
    monkeypatch.setattr(
        placement,
        "_candidate_origins",
        lambda target_positions, capacitor_offsets, limit_mm: ((1.0, 1.0),),
    )

    def fake_box(
        graph: DesignGraph,
        component: ComponentView,
        fixture_dir: Path,
        library: placement.FootprintLibrary,
        **kwargs: object,
    ) -> tuple[float, float, float, float] | None:
        refdes = component.refdes
        if refdes == "U1":
            return (0.9, 0.9, 1.1, 1.1) if blocked else None
        if refdes != "C4":
            return None
        if kwargs.get("x_mm") is None:
            return (20.0, 20.0, 21.0, 21.0)
        rotation = kwargs.get("rotation_deg")
        if isinstance(rotation, float) and rotation in (90.0, 180.0, 270.0):
            return (10.0, 10.0, 11.0, 11.0)
        return (0.0, 0.0, 2.0, 2.0)

    monkeypatch.setattr(placement, "_component_box", fake_box)


def test_rotation_exploration_updates_rotation_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    lane = _lane(graph, {"C4", "U1"})
    _patch_geometry(monkeypatch, lane, blocked=True)

    report = placement.solve_decoupling_placements(graph, FIXTURE_DIR)

    assert report.status == "adjusted"
    moved = next(item for item in report.placements if item.refdes == "C4")
    assert moved.placement_rotation_deg == 90.0
    applied = placement.apply_decoupling_placements(graph, report)
    c4 = next(node for node in applied.nodes if node.attrs.get("refdes") == "C4")
    assert c4.attrs["placement_rotation_deg"] == 90.0
    source_ref = c4.attrs["placement_source_ref"]
    assert isinstance(source_ref, str)
    assert "rotation_deg=90.0" in source_ref


def test_impossible_rotation_fixed_case_reports_machine_readable_deficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph(rotation_fixed=True)
    lane = _lane(graph, {"C4", "U1"})
    _patch_geometry(monkeypatch, lane, blocked=True)

    report = placement.solve_decoupling_placements(graph, FIXTURE_DIR)
    deficiency = report.deficiencies[0]
    payload = report.as_payload()["deficiencies"][0]

    assert deficiency.distance_deficit_mm == 0.0
    assert deficiency.clearance_deficit_mm is not None
    assert deficiency.blocking_refdes == ("U1",)
    assert payload["best_distance_mm"] < deficiency.limit_mm
    dimensions = {item["dimension"]: item for item in deficiency.explored_dimensions}
    assert dimensions["rotation"]["status"] == "unavailable"
    assert dimensions["rotation"]["candidates_evaluated"] == 0
    assert dimensions["side"]["status"] == "unavailable"
    assert deficiency.changeable_dimensions


def test_identical_synthetic_solves_have_identical_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph(rotation_fixed=True)
    lane = _lane(graph, {"C4", "U1"})
    _patch_geometry(monkeypatch, lane, blocked=True)

    first = placement.solve_decoupling_placements(graph, FIXTURE_DIR)
    second = placement.solve_decoupling_placements(graph, FIXTURE_DIR)

    assert first.as_payload() == second.as_payload()


def test_placement_order_retries_the_deficient_component_first(monkeypatch) -> None:
    graph = _graph(rotation_fixed=True)
    lane = extract_electrical_lane(graph)
    calls: list[tuple[str, ...]] = []

    def fake_pass(
        graph: DesignGraph,
        baseline_graph: DesignGraph,
        fixture_dir: Path,
        order: tuple[ComponentView, ...],
        placement_passes: int,
    ) -> placement._PassResult:
        calls.append(tuple(item.refdes for item in order))
        if len(calls) == 1:
            return placement._PassResult(
                placements=(),
                deficiencies=(
                    placement.DecouplingPlacementDeficiency(
                        refdes="C4",
                        target_refdes="U1",
                        net_id="net.p3v3",
                        limit_mm=3.0,
                        distance_mm=4.0,
                        reason="synthetic deficiency",
                    ),
                ),
            )
        return placement._PassResult(placements=(), deficiencies=())

    monkeypatch.setattr(placement, "extract_electrical_lane", lambda graph: lane)
    monkeypatch.setattr(placement, "_solve_pass", fake_pass)

    report = placement.solve_decoupling_placements(graph, FIXTURE_DIR)

    assert report.status == "satisfied"
    assert len(calls) == 2
    assert calls[0] == tuple(sorted(calls[0]))
    assert calls[1][0] == "C4"
