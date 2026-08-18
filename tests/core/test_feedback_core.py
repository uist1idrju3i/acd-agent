"""Tests for deterministic physical-measurement feedback proposals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.feedback import propose_input_feedback, validate_applied_feedback
from acd.schema import (
    DesignGraph,
    FeedbackPolicy,
    PhysicalEvidence,
    RationaleDocument,
)

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
RATIONALE_PATH = ROOT / "fixtures/golden-design-1/rationale.json"
POLICY_PATH = ROOT / "fixtures/feedback/policy.json"


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(
    policy_path: Path = POLICY_PATH,
    rationale_path: Path = RATIONALE_PATH,
    evidence_paths: tuple[Path, ...] = (
        ROOT / "fixtures/feedback/valid/led_frequency.json",
        ROOT / "fixtures/feedback/valid/matched_artifact_count.json",
    ),
) -> tuple[DesignGraph, RationaleDocument, list[PhysicalEvidence], FeedbackPolicy]:
    graph = DesignGraph.model_validate(_load(GRAPH_PATH))
    rationale = RationaleDocument.model_validate(_load(rationale_path))
    evidences = [
        PhysicalEvidence.model_validate(_load(path)) for path in evidence_paths
    ]
    policy = FeedbackPolicy.model_validate(_load(policy_path))
    return graph, rationale, evidences, policy


def test_feedback_proposal_is_deterministic_and_non_mutating() -> None:
    graph, rationale, evidences, policy = _inputs()
    before = graph.model_dump_json()
    first = propose_input_feedback(graph, rationale, evidences, policy)
    second = propose_input_feedback(graph, rationale, evidences, policy)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.input_hash == second.input_hash
    assert first.output_hash == second.output_hash
    assert graph.model_dump_json() == before
    assert first.status == "pass"
    assert first.applicable is True
    assert [item.status for item in first.items] == ["proposed", "no_change"]
    assert first.items[0].proposed_value == 7


@pytest.mark.parametrize(
    ("policy_name", "evidence_paths", "expected"),
    [
        (
            "policy.json",
            ("invalid/stale-evidence.json", "valid/matched_artifact_count.json"),
            "unknown",
        ),
        (
            "policy.json",
            ("invalid/virtual-evidence.json", "valid/matched_artifact_count.json"),
            "unknown",
        ),
        (
            "policy.json",
            ("invalid/status-evidence.json", "valid/matched_artifact_count.json"),
            "unknown",
        ),
        ("invalid/node-missing-policy.json", ("valid/led_frequency.json",), "unknown"),
        ("invalid/attr-missing-policy.json", ("valid/led_frequency.json",), "unknown"),
        (
            "invalid/unclassified-attr-policy.json",
            ("valid/led_frequency.json",),
            "unknown",
        ),
        (
            "invalid/measurement-missing-policy.json",
            ("valid/led_frequency.json",),
            "unknown",
        ),
        ("invalid/graph-mismatch-policy.json", ("valid/led_frequency.json",), "unknown"),
    ],
)
def test_feedback_fail_closed(
    policy_name: str, evidence_paths: tuple[str, ...], expected: str
) -> None:
    graph, rationale, _, _ = _inputs()
    policy = FeedbackPolicy.model_validate(_load(ROOT / "fixtures/feedback" / policy_name))
    evidences = [
        PhysicalEvidence.model_validate(
            _load(ROOT / "fixtures/feedback" / path)
        )
        for path in evidence_paths
    ]
    proposal = propose_input_feedback(graph, rationale, evidences, policy)
    assert proposal.status == expected
    assert proposal.items == []
    assert proposal.error


def test_missing_rationale_is_explicit() -> None:
    graph, _, evidences, policy = _inputs(
        rationale_path=ROOT / "fixtures/feedback/invalid/rationale-missing.json"
    )
    proposal = propose_input_feedback(
        graph,
        RationaleDocument.model_validate(
            _load(ROOT / "fixtures/feedback/invalid/rationale-missing.json")
        ),
        evidences,
        policy,
    )
    assert proposal.status == "pass"
    assert proposal.applicable is False
    assert all(item.rationale_required for item in proposal.items if item.status == "proposed")


def test_application_validator_rejects_extra_difference() -> None:
    graph, rationale, evidences, _ = _inputs(
        policy_path=ROOT / "fixtures/feedback/policy.json",
        evidence_paths=(ROOT / "fixtures/feedback/valid/led_frequency.json",),
    )
    policy = FeedbackPolicy.model_validate(
        {
            "graph_id": graph.graph_id,
            "revision": graph.revision,
            "rules": [
                {
                    "rule_id": "set-hole-count",
                    "measurement_name": "led_frequency",
                    "node_id": "mechanical.outline.gd1",
                    "attr": "mount_hole_count",
                    "rule_kind": "set_value",
                    "tolerance": 0,
                    "decision_kind": "mechanical",
                }
            ],
        }
    )
    proposal = propose_input_feedback(graph, rationale, evidences, policy)
    updated = graph.model_copy(
        deep=True,
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            **(
                                {
                                    "mount_hole_count": 1,
                                    "width_mm": 123.0,
                                }
                                if node.id == "mechanical.outline.gd1"
                                else {}
                            ),
                        }
                    }
                )
                for node in graph.nodes
            ]
        },
    )
    report = validate_applied_feedback(graph, updated, proposal)
    assert report.status == "fail"
    assert report.reason


def test_application_validator_accepts_declared_change() -> None:
    graph, rationale, evidences, _ = _inputs(
        evidence_paths=(ROOT / "fixtures/feedback/valid/led_frequency.json",)
    )
    policy = FeedbackPolicy.model_validate(
        {
            "graph_id": graph.graph_id,
            "revision": graph.revision,
            "rules": [
                {
                    "rule_id": "set-hole-count",
                    "measurement_name": "led_frequency",
                    "node_id": "mechanical.outline.gd1",
                    "attr": "mount_hole_count",
                    "rule_kind": "set_value",
                    "tolerance": 0,
                    "decision_kind": "mechanical",
                }
            ],
        }
    )
    proposal = propose_input_feedback(graph, rationale, evidences, policy)
    updated = graph.model_copy(
        deep=True,
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            **(
                                {"mount_hole_count": 1}
                                if node.id == "mechanical.outline.gd1"
                                else {}
                            ),
                        }
                    }
                )
                for node in graph.nodes
            ]
        },
    )
    report = validate_applied_feedback(graph, updated, proposal)
    assert report.status == "pass"
