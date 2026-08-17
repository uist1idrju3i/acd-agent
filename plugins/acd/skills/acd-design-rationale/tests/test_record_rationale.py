from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "plugins/acd/skills/acd-design-rationale/scripts/record_rationale.py"


def test_record_rejects_duplicate_coverage(tmp_path: Path) -> None:
    graph = {
        "graph_id": "g",
        "revision": "r1",
        "nodes": [{"id": "n1", "kind": "x", "attrs": {"value": 1}}],
    }
    document = {
        "schema_version": "0.1",
        "graph_id": "g",
        "revision": "r1",
        "records": [
            {
                "subject_nodes": ["n1"],
                "subject_attrs": ["value"],
            }
        ],
    }
    record = {
        "rationale_id": "r1",
        "decision_kind": "mechanical",
        "subject_nodes": ["n1"],
        "subject_attrs": ["value"],
        "decision": "Use value one.",
        "justification": "The graph declares value one.",
        "no_alternatives_reason": "No alternative recorded.",
        "provenance": {"source": "human", "recorded_at": "2025-01-01T00:00:00Z"},
    }
    graph_path = tmp_path / "graph.json"
    rationale_path = tmp_path / "rationale.json"
    record_path = tmp_path / "record.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    rationale_path.write_text(json.dumps(document), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    first = subprocess.run(
        [sys.executable, str(SCRIPT), "--graph", str(graph_path), "--rationale",
         str(rationale_path), "--record", str(record_path)],
        cwd=ROOT,
        check=False,
    )
    assert first.returncode == 2
