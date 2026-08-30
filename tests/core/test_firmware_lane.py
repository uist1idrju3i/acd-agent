"""Tests for deterministic firmware declaration extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.electrical import GraphExtractionError
from acd.core.firmware_lane import extract_firmware_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "golden-design-1"
    / "graph.json"
)


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _replace_node(graph: DesignGraph, node_id: str, **updates: object) -> DesignGraph:
    nodes = [
        node.model_copy(update=updates) if node.id == node_id else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def _replace_attrs(
    graph: DesignGraph, node_id: str, **attrs: object
) -> DesignGraph:
    node = graph.node_by_id(node_id)
    return _replace_node(graph, node_id, attrs={**node.attrs, **attrs})


def test_firmware_lane_extracts_all_declared_views() -> None:
    lane = extract_firmware_lane(_graph())

    assert lane.module.mcu_component == "comp.u1"
    assert lane.module.entry_state == "fw.state.boot"
    assert [state.node_id for state in lane.states] == [
        "fw.state.boot",
        "fw.state.fault",
        "fw.state.measure",
        "fw.state.report",
        "fw.state.sensor_init",
    ]
    assert sum(state.initial for state in lane.states) == 1
    assert len(lane.transitions) == 5
    assert [step.step_index for step in lane.sequence_steps] == [1, 2, 3, 4, 5]
    assert len(lane.pin_assignments) == 8


def test_firmware_lane_requires_exactly_one_module() -> None:
    graph = _graph().model_copy(
        update={
            "nodes": [
                node
                for node in _graph().nodes
                if node.kind != "firmware.module"
            ]
        }
    )
    with pytest.raises(
        GraphExtractionError, match=r"exactly one firmware\.module"
    ):
        extract_firmware_lane(graph)

    graph = _graph().model_copy(
        update={
            "nodes": [
                *_graph().nodes,
                _graph().node_by_id("fw.module.main").model_copy(
                    update={"id": "fw.module.secondary"}
                )
            ],
        }
    )
    with pytest.raises(
        GraphExtractionError, match=r"exactly one firmware\.module"
    ):
        extract_firmware_lane(graph)


@pytest.mark.parametrize(
    ("node_id", "field"),
    [
        ("fw.module.main", "mcu_component"),
        ("fw.module.main", "entry_state"),
        ("fw.transition.boot_sensor_init", "from_state"),
        ("fw.transition.boot_sensor_init", "to_state"),
        ("fw.sequence.001", "actor"),
        ("fw.sequence.001", "target"),
    ],
)
def test_firmware_lane_rejects_missing_references(
    node_id: str, field: str
) -> None:
    with pytest.raises(GraphExtractionError, match="does not exist"):
        extract_firmware_lane(_replace_attrs(_graph(), node_id, **{field: "missing"}))


def test_firmware_lane_rejects_reference_kind_mismatch() -> None:
    with pytest.raises(
        GraphExtractionError, match=r"not electrical\.component"
    ):
        extract_firmware_lane(
            _replace_attrs(
                _graph(), "fw.module.main", mcu_component="net.gnd"
            )
        )
    with pytest.raises(GraphExtractionError, match=r"not firmware\.state"):
        extract_firmware_lane(
            _replace_attrs(
                _graph(), "fw.transition.boot_sensor_init", from_state="comp.u1"
            )
        )


def test_firmware_lane_rejects_initial_state_mismatch_and_count() -> None:
    graph = _replace_attrs(_graph(), "fw.state.fault", initial=True)
    with pytest.raises(GraphExtractionError, match="exactly one initial"):
        extract_firmware_lane(graph)

    graph = _replace_attrs(_graph(), "fw.module.main", entry_state="fw.state.fault")
    with pytest.raises(GraphExtractionError, match="does not match"):
        extract_firmware_lane(graph)


def test_firmware_lane_rejects_missing_transition_and_invalid_state_graph() -> None:
    graph = _graph().model_copy(
        update={
            "nodes": [
                node
                for node in _graph().nodes
                if node.kind != "firmware.state_transition"
            ]
        }
    )
    with pytest.raises(GraphExtractionError, match="at least one state transition"):
        extract_firmware_lane(graph)

    graph = _replace_attrs(
        _graph(),
        "fw.transition.measure_fault",
        from_state="fw.state.fault",
        to_state="fw.state.fault",
    )
    graph = _replace_node(
        graph,
        "fw.transition.measure_fault",
        depends_on=["fw.state.fault"],
    )
    with pytest.raises(GraphExtractionError, match="not all reachable"):
        extract_firmware_lane(graph)


def test_firmware_lane_rejects_duplicate_transition() -> None:
    graph = _replace_attrs(
        _graph(),
        "fw.transition.measure_fault",
        from_state="fw.state.measure",
        to_state="fw.state.report",
        trigger="measurement_ready",
    )
    graph = _replace_node(
        graph,
        "fw.transition.measure_fault",
        depends_on=["fw.state.measure", "fw.state.report"],
    )
    with pytest.raises(GraphExtractionError, match="duplicate firmware state"):
        extract_firmware_lane(graph)


def test_firmware_lane_rejects_missing_or_invalid_sequence_steps() -> None:
    graph = _graph().model_copy(
        update={
            "nodes": [
                node
                for node in _graph().nodes
                if node.kind != "firmware.sequence_step"
            ]
        }
    )
    with pytest.raises(GraphExtractionError, match="at least one sequence"):
        extract_firmware_lane(graph)

    graph = _replace_attrs(_graph(), "fw.sequence.003", step_index=9)
    with pytest.raises(GraphExtractionError, match="contiguous 1-based"):
        extract_firmware_lane(graph)


def test_firmware_lane_rejects_missing_or_malformed_attributes() -> None:
    with pytest.raises(GraphExtractionError, match="state_name"):
        extract_firmware_lane(
            _replace_attrs(
                _graph(),
                "fw.state.boot",
                state_name=None,
            )
        )
    with pytest.raises(GraphExtractionError, match="initial"):
        extract_firmware_lane(
            _replace_attrs(_graph(), "fw.state.boot", initial="true")
        )
    with pytest.raises(GraphExtractionError, match="step_index"):
        extract_firmware_lane(
            _replace_attrs(_graph(), "fw.sequence.001", step_index=True)
        )
