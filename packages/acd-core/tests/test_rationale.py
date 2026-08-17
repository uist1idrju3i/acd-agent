"""Tests for deterministic rationale hashing and coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from acd_core.rationale import check_rationale_coverage, subject_hash_for
from acd_schema import DesignGraph, RationaleDocument


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        {
            "graph_id": "test",
            "revision": "r1",
            "nodes": [
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
                },
                {"id": "req.1", "kind": "requirement", "attrs": {"text": "required"}},
            ],
        }
    )


def _document(graph: DesignGraph, **overrides: object) -> RationaleDocument:
    values: dict[str, object] = {
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "records": [
            {
                "rationale_id": "rat-1",
                "decision_kind": "part_selection",
                "subject_nodes": ["comp.u1"],
                "subject_attrs": [
                    "mpn", "lcsc", "placement_x_mm", "placement_y_mm",
                    "placement_rotation_deg",
                ],
                "subject_hash": subject_hash_for(
                    graph,
                    ["comp.u1"],
                    ["mpn", "lcsc", "placement_x_mm", "placement_y_mm", "placement_rotation_deg"],
                ),
                "decision": "Use U1",
                "justification": "It satisfies the requirements.",
                "driving_requirements": ["req.1"],
                "no_alternatives_reason": "No alternatives were evaluated.",
                "provenance": {
                    "source": "acd_skill",
                    "skill_name": "test-skill",
                    "script_hash": "sha256:" + "1" * 64,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
                "target_revision": "r1",
            }
        ],
    }
    values.update(overrides)
    return RationaleDocument.model_validate(values)


def test_subject_hash_is_deterministic_and_changes_with_value() -> None:
    graph = _graph()
    first = subject_hash_for(graph, ["comp.u1"], ["mpn"])
    assert first == subject_hash_for(graph, ["comp.u1"], ["mpn"])
    changed = graph.model_copy(
        update={"nodes": [graph.nodes[0].model_copy(update={"attrs": {"mpn": "U2"}})]}
    )
    assert first != subject_hash_for(changed, ["comp.u1"], ["mpn"])


def test_coverage_passes() -> None:
    report = check_rationale_coverage(_graph(), _document(_graph()))
    assert report.status == "pass"


def test_human_provenance_without_script_is_covered() -> None:
    graph = _graph()
    document = _document(graph)
    record = document.records[0].model_copy(
        update={
            "provenance": document.records[0].provenance.model_copy(
                update={"source": "human", "script_hash": None}
            )
        }
    )
    report = check_rationale_coverage(
        graph, document.model_copy(update={"records": [record]})
    )
    assert report.status == "pass"
    assert report.unknown_provenance == []
    assert record.supports_coverage(
        graph.revision, record.subject_hash
    )


def test_explicit_unknown_script_hash_fails_coverage() -> None:
    graph = _graph()
    document = _document(graph)
    record = document.records[0].model_copy(
        update={
            "provenance": document.records[0].provenance.model_copy(
                update={"script_hash": "unknown"}
            )
        }
    )
    report = check_rationale_coverage(
        graph, document.model_copy(update={"records": [record]})
    )
    assert report.status == "fail"
    assert [item.rationale_id for item in report.unknown_provenance] == ["rat-1"]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "stale",
        "conflicting",
        "orphan",
        "unknown",
        "untraceable",
        "graph_id",
        "revision",
    ],
)
def test_coverage_failures(change: str) -> None:
    graph = _graph()
    if change == "missing":
        document = RationaleDocument.model_validate(
            {"graph_id": "test", "revision": "r1", "records": []}
        )
    elif change == "stale":
        document = _document(
            graph,
            records=[
                {
                    **_document(graph).records[0].model_dump(),
                    "target_revision": "r2",
                }
            ],
        )
    elif change == "conflicting":
        record = _document(graph).records[0].model_dump()
        document = _document(graph, records=[record, {**record, "rationale_id": "rat-2"}])
    elif change == "orphan":
        record = _document(graph).records[0].model_dump()
        record["driving_requirements"] = ["req.missing"]
        document = _document(graph, records=[record])
    elif change == "unknown":
        record = _document(graph).records[0].model_dump()
        record["provenance"] = {**record["provenance"], "script_hash": "unknown"}
        document = _document(graph, records=[record])
    elif change == "untraceable":
        record = _document(graph).records[0].model_dump()
        record["driving_requirements"] = []
        document = _document(graph, records=[record])
    elif change == "graph_id":
        document = _document(graph, graph_id="other")
    else:
        document = _document(graph, revision="r2")
    report = check_rationale_coverage(graph, document)
    assert report.status == "fail"
    if change == "untraceable":
        assert len(report.untraceable) == 5
        assert {item.rationale_id for item in report.untraceable} == {"rat-1"}
