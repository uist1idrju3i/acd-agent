"""Tests for deterministic rationale hashing and coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.rationale import (
    check_rationale_coverage,
    subject_hash_for,
    summarize_rationale_coverage,
)
from acd.schema import (
    DesignGraph,
    RationaleCoverageReport,
    RationaleDocument,
)
from acd.schema.design_fixture import DesignFixtureSpec


def test_gd1_rationale_decisions_and_justifications_are_unique() -> None:
    fixture = Path(__file__).parents[2] / "fixtures/golden-design-1/rationale.json"
    records = json.loads(fixture.read_text(encoding="utf-8"))["records"]

    decisions = [record["decision"] for record in records]
    justifications = [record["justification"] for record in records]

    assert len(decisions) == len(set(decisions))
    assert len(justifications) == len(set(justifications))


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


def test_document_requirement_reference_supports_coverage() -> None:
    graph = _graph()
    document = _document(graph)
    record = document.records[0].model_copy(
        update={
            "driving_requirements": [],
            "driving_requirement_refs": ["docs/golden-design-1.md#GD1-REQ-017"],
        }
    )
    report = check_rationale_coverage(
        graph, document.model_copy(update={"records": [record]})
    )
    assert report.status == "pass"
    assert report.untraceable == []


def test_unclassified_attribute_fails_closed() -> None:
    base = _graph()
    graph = base.model_copy(
        update={
            "nodes": [
                base.nodes[0].model_copy(
                    update={"attrs": {**base.nodes[0].attrs, "future_choice": "x"}}
                ),
                base.nodes[1],
            ]
        }
    )
    report = check_rationale_coverage(graph, _document(base))
    assert report.status == "fail"
    assert [(item.node_id, item.attr) for item in report.unclassified] == [
        ("comp.u1", "future_choice")
    ]


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
        "unclassified",
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
    elif change == "unclassified":
        graph = graph.model_copy(
            update={
                "nodes": [
                    graph.nodes[0].model_copy(
                        update={"attrs": {**graph.nodes[0].attrs, "future_choice": "x"}}
                    ),
                    graph.nodes[1],
                ]
            }
        )
        document = _document(graph)
    elif change == "graph_id":
        document = _document(graph, graph_id="other")
    else:
        document = _document(graph, revision="r2")
    report = check_rationale_coverage(graph, document)
    assert report.status == "fail"
    if change == "untraceable":
        assert len(report.untraceable) == 5
        assert {item.rationale_id for item in report.untraceable} == {"rat-1"}


def test_summarize_rationale_coverage_reports_pass() -> None:
    graph = _graph()
    report = check_rationale_coverage(graph, _document(graph))

    summary = summarize_rationale_coverage(report)

    assert summary.startswith(
        "status=pass graph_id_match=True revision_match=True"
    )
    assert "missing=0 " in summary
    assert "templated=0" in summary
    assert "[" not in summary


def test_summarize_rationale_coverage_formats_every_category() -> None:
    subject = {"node_id": "comp.u1", "attr": "x_mm"}
    report = RationaleCoverageReport.model_validate(
        {
            "status": "fail",
            "graph_id": "g",
            "revision": "r1",
            "graph_id_match": True,
            "revision_match": False,
            "missing": [subject],
            "stale": [{"rationale_id": "r-1", "subject": subject}],
            "unknown_provenance": [{"rationale_id": "r-2"}],
            "orphan": [
                {
                    "rationale_id": "r-3",
                    "subject": subject,
                    "reason": "unknown node",
                }
            ],
            "untraceable": [{"rationale_id": "r-4", "subject": subject}],
            "conflicting": [{"rationale_id": "r-5", "subject": subject}],
            "unclassified": [
                {
                    "node_id": "comp.u1",
                    "node_kind": "electrical.component",
                    "attr": "future_choice",
                    "reason": "unclassified attr",
                }
            ],
            "templated": [{"rationale_id": "r-6", "reason": "template text"}],
            "generator_violations": [
                {"rationale_id": "r-7", "reason": "self-declared"}
            ],
        }
    )

    summary = summarize_rationale_coverage(report)

    assert "revision_match=False" in summary
    assert "missing=1 [comp.u1.x_mm]" in summary
    assert "stale=1 [r-1→comp.u1.x_mm]" in summary
    assert "unknown_provenance=1 [r-2]" in summary
    assert "orphan=1 [r-3→comp.u1.x_mm (unknown node)]" in summary
    assert "untraceable=1 [r-4→comp.u1.x_mm]" in summary
    assert "conflicting=1 [r-5→comp.u1.x_mm]" in summary
    assert "unclassified=1 [comp.u1.future_choice (unclassified attr)]" in summary
    assert "templated=1 [r-6 (template text)]" in summary
    assert "generator_violations=1 [r-7 (self-declared)]" in summary


def test_summarize_rationale_coverage_truncates_in_stable_order() -> None:
    report = RationaleCoverageReport.model_validate(
        {
            "status": "fail",
            "graph_id": "g",
            "revision": "r1",
            "graph_id_match": True,
            "revision_match": True,
            "missing": [
                {"node_id": f"comp.u{index}", "attr": "x_mm"}
                for index in range(7, 0, -1)
            ],
        }
    )

    summary = summarize_rationale_coverage(report, limit=5)

    assert "missing=7 [comp.u1.x_mm" in summary
    assert "comp.u7" not in summary
    assert "…(+2 more)" in summary


def test_summarize_rationale_coverage_is_used_by_fixture_builder(
    tmp_path: Path,
) -> None:
    spec = DesignFixtureSpec.model_validate(
        {
            "design_name": "coverage-message",
            "components": [
                {
                    "refdes": "U1",
                    "attrs": {"mpn": "MCU-1", "future_choice": "x"},
                    "pads": {"1": "net.io"},
                }
            ],
            "nets": [{"net_id": "net.io", "attrs": {"name": "IO"}}],
            "requirements": [
                {"requirement_id": "io", "statement": "Drive the IO net."}
            ],
        }
    )

    from acd.pipeline.fixture_builder import (
        FixtureBuilderError,
        build_design_fixture,
    )

    with pytest.raises(FixtureBuilderError) as excinfo:
        build_design_fixture(spec, tmp_path / "fixture")

    message = str(excinfo.value)
    assert "rationale coverage failed while building fixture" in message
    assert "unclassified=1 [comp.u1.future_choice" in message
    assert "REQUIRED_RATIONALE_ATTRS" in message
