"""Tests for rationale generator provenance and anti-template validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from acd.core.rationale import (
    BULK_RECORD_MIN,
    check_rationale_coverage,
    subject_hash_for,
)
from acd.schema import DesignGraph, RationaleDocument
from acd.schema.rationale import RationaleProvenance

RECORDED_AT = datetime(2026, 8, 11, tzinfo=UTC)
COMPONENT_ATTRS = [
    "mpn",
    "lcsc",
    "placement_x_mm",
    "placement_y_mm",
    "placement_rotation_deg",
]


def _graph(requirements: int = 1) -> DesignGraph:
    nodes: list[dict[str, Any]] = [
        {
            "id": "comp.u1",
            "kind": "electrical.component",
            "attrs": {
                "mpn": "U1",
                "lcsc": "C1",
                "placement_x_mm": 1.0,
                "placement_y_mm": 2.0,
                "placement_rotation_deg": 0.0,
            },
        }
    ]
    nodes.extend(
        {
            "id": f"req.{index}",
            "kind": "requirement",
            "attrs": {"text": f"required {index}"},
        }
        for index in range(1, requirements + 1)
    )
    return DesignGraph.model_validate(
        {"graph_id": "test", "revision": "r1", "nodes": nodes}
    )


def _record(graph: DesignGraph, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "rationale_id": "rat-1",
        "decision_kind": "part_selection",
        "subject_nodes": ["comp.u1"],
        "subject_attrs": COMPONENT_ATTRS,
        "subject_hash": subject_hash_for(graph, ["comp.u1"], COMPONENT_ATTRS),
        "decision": "Use U1 at (1.0, 2.0) mm",
        "justification": "The catalog entry satisfies req.1 for comp.u1.",
        "driving_requirements": ["req.1"],
        "no_alternatives_reason": "No alternatives were evaluated.",
        "provenance": {
            "source": "acd_skill",
            "skill_name": "acd-board-pipeline",
            "script_hash": "sha256:" + "1" * 64,
            "recorded_at": RECORDED_AT.isoformat(),
        },
        "target_revision": "r1",
    }
    record.update(overrides)
    return record


def _document(graph: DesignGraph, records: list[dict[str, Any]]) -> RationaleDocument:
    return RationaleDocument.model_validate(
        {"graph_id": graph.graph_id, "revision": graph.revision, "records": records}
    )


@pytest.mark.parametrize(
    "provenance",
    [
        {"source": "acd_skill", "recorded_at": RECORDED_AT.isoformat()},
        {
            "source": "acd_skill",
            "skill_name": "acd-board-pipeline",
            "recorded_at": RECORDED_AT.isoformat(),
        },
        {
            "source": "openhands_agent",
            "agent_model": "some-model",
            "recorded_at": RECORDED_AT.isoformat(),
        },
        {"source": "deterministic_tool", "recorded_at": RECORDED_AT.isoformat()},
    ],
)
def test_provenance_without_a_named_generator_is_rejected(
    provenance: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        RationaleProvenance.model_validate(provenance)


def test_agent_provenance_requires_a_conversation_reference() -> None:
    valid = RationaleProvenance.model_validate(
        {
            "source": "openhands_agent",
            "agent_model": "litellm_proxy/some-model",
            "conversation_event_ref": "conv-1:event-4",
            "recorded_at": RECORDED_AT.isoformat(),
        }
    )
    assert valid.conversation_event_ref == "conv-1:event-4"


def test_unknown_deterministic_generator_fails_coverage() -> None:
    graph = _graph()
    document = _document(
        graph,
        [
            _record(
                graph,
                provenance={
                    "source": "deterministic_tool",
                    "tool_name": "some.other.tool",
                    "tool_version": "1.0.0",
                    "script_hash": "sha256:" + "2" * 64,
                    "recorded_at": RECORDED_AT.isoformat(),
                },
            )
        ],
    )
    report = check_rationale_coverage(graph, document)
    assert report.status == "fail"
    assert [item.rationale_id for item in report.generator_violations] == ["rat-1"]


def test_repeated_template_text_fails_closed() -> None:
    graph = _graph()
    records = [
        _record(
            graph,
            rationale_id=f"rat-{index}",
            decision="Selected by the deterministic tool.",
            justification="The deterministic tool produced this decision.",
        )
        for index in range(1, 5)
    ]
    report = check_rationale_coverage(graph, _document(graph, records))
    assert report.status == "fail"
    assert {item.rationale_id for item in report.templated} == {
        f"rat-{index}" for index in range(1, 5)
    }


def test_single_requirement_attribution_for_many_records_fails_closed() -> None:
    graph = _graph(requirements=3)
    records = [
        _record(
            graph,
            rationale_id=f"rat-{index}",
            decision=f"Use U1 variant {index}",
            justification=f"Variant {index} satisfies the declared constraint.",
        )
        for index in range(1, BULK_RECORD_MIN + 1)
    ]
    report = check_rationale_coverage(graph, _document(graph, records))
    assert report.status == "fail"
    assert len(report.templated) == BULK_RECORD_MIN


def test_valid_generator_provenance_passes_coverage() -> None:
    graph = _graph()
    report = check_rationale_coverage(graph, _document(graph, [_record(graph)]))
    assert report.status == "pass"
    assert report.templated == []
    assert report.generator_violations == []
