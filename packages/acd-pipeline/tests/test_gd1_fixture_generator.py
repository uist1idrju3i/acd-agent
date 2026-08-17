"""Verify the generator's mechanical nodes match the tracked fixture."""

from __future__ import annotations

import json
from pathlib import Path

from acd_core.rationale import subject_hash_for
from acd_pipeline.gd1_fixture import mechanical_nodes, silkscreen_nodes
from acd_pipeline.gd1_fixture.graph import check_rationale_hashes
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
                    "placement_source",
                    "placement_source_ref",
                    "placement_evidence",
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
