"""Verify the generator's mechanical nodes match the tracked fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_core.rationale import subject_hash_for
from acd_pipeline.gd1_fixture import mechanical_nodes, silkscreen_nodes
from acd_pipeline.gd1_fixture.graph import check_rationale_hashes
from acd_pipeline.placement_evidence import summarize_placement_evidence
from acd_schema import DesignGraph, RationaleDocument

# pyright: reportMissingTypeStubs=false

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"


def test_generator_mechanical_nodes_match_fixture_without_kicad() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = [node for node in fixture["nodes"] if node["kind"].startswith("mechanical.")]
    actual = [
        node.model_dump(mode="json")
        for node in (mechanical_nodes() + silkscreen_nodes("golden-design-1", "r1"))
    ]
    for nodes in (expected, actual):
        for node in nodes:
            if node["kind"] == "mechanical.silk_text":
                for key in (
                    "x_mm",
                    "y_mm",
                    "rotation_deg",
                    "placement_rotation_deg",
                    "placement_source",
                    "placement_source_ref",
                    "placement_evidence",
                    "placement_evidence_input_sha256",
                    "placement_evidence_output_sha256",
                ):
                    node["attrs"].pop(key, None)
    assert actual == expected


def test_generator_refuses_stale_rationale_hashes(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(
        {
            "graph_id": "g",
            "revision": "r2",
            "nodes": [
                {
                    "id": "n1",
                    "kind": "electrical.component",
                    "attrs": {
                        "mpn": "U1",
                        "lcsc": "C1",
                        "placement_x_mm": 1.0,
                        "placement_y_mm": 2.0,
                        "placement_rotation_deg": 0.0,
                    },
                }
            ],
        }
    )
    rationale_path = tmp_path / "rationale.json"
    rationale_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "graph_id": "g",
                "revision": "r1",
                "records": [
                    {
                        "rationale_id": "r1",
                        "decision_kind": "placement",
                        "subject_nodes": ["n1"],
                        "subject_attrs": [
                            "mpn",
                            "lcsc",
                            "placement_x_mm",
                            "placement_y_mm",
                            "placement_rotation_deg",
                        ],
                        "subject_hash": "sha256:" + "0" * 64,
                        "decision": "Use declared placement.",
                        "justification": "Graph declares the placement.",
                        "no_alternatives_reason": "No alternatives recorded.",
                        "provenance": {
                            "source": "human",
                            "recorded_at": "2025-01-01T00:00:00Z",
                        },
                        "target_revision": "r1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert check_rationale_hashes(graph, rationale_path, refresh=False) == 2
    assert check_rationale_hashes(graph, rationale_path, refresh=True) == 0
    refreshed = RationaleDocument.model_validate(
        json.loads(rationale_path.read_text(encoding="utf-8"))
    )
    assert refreshed.records[0].subject_hash == subject_hash_for(
        graph,
        ["n1"],
        [
            "mpn",
            "lcsc",
            "placement_x_mm",
            "placement_y_mm",
            "placement_rotation_deg",
        ],
    )


def test_placement_evidence_summary_is_hash_linked_and_bounded() -> None:
    evidence = {
        "node_id": "mechanical.silk_text.demo",
        "role": "label",
        "resolution": "context_candidate",
        "accepted_position_mm": [1.0, 2.0],
        "accepted_rotation_deg": 90.0,
        "placement_order": ["mechanical.silk_text.demo"],
        "rejected_candidates": [
            {"reason": "pad_overlap", "x_mm": float(index)} for index in range(6)
        ],
    }
    summary = summarize_placement_evidence(evidence, example_limit=3)
    assert summary["rejection_counts"] == {"pad_overlap": 6}
    assert len(summary["rejection_examples"]) == 3
    assert len(summary["full_evidence_sha256"]) == 64


def test_placement_evidence_summary_fails_closed_when_rejections_are_missing() -> None:
    with pytest.raises(ValueError, match="rejected_candidates"):
        summarize_placement_evidence({"node_id": "demo", "resolution": "candidate"})


def test_fixture_placement_evidence_has_required_summary_fields() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = {
        "summary_version",
        "node_id",
        "resolution",
        "rejection_counts",
        "rejection_examples",
        "full_evidence_sha256",
    }
    for node in fixture["nodes"]:
        if node["kind"] != "mechanical.silk_text":
            continue
        evidence = json.loads(node["attrs"]["placement_evidence"])
        assert required <= evidence.keys()
        assert "rejected_candidates" not in evidence


def test_fixture_provenance_hashes_have_single_sha256_prefix() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for node in fixture["nodes"]:
        if node["kind"] != "mechanical.silk_text":
            continue
        attrs = node["attrs"]
        source_ref = attrs["placement_source_ref"]
        assert source_ref.count("sha256:") == 1
        for key in (
            "placement_evidence_input_sha256",
            "placement_evidence_output_sha256",
        ):
            value = attrs[key]
            assert value.startswith("sha256:")
            assert value.count("sha256:") == 1
