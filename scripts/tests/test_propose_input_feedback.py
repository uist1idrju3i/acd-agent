"""End-to-end tests for the input-feedback proposal CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRAPH = ROOT / "fixtures/golden-design-1/graph.json"
RATIONALE = ROOT / "fixtures/golden-design-1/rationale.json"
POLICY = ROOT / "fixtures/feedback/policy.json"
EVIDENCE = ROOT / "fixtures/feedback/valid"


def invoke(
    tmp_path: Path,
    graph: Path = GRAPH,
    policy: Path = POLICY,
    rationale: Path = RATIONALE,
    evidence: Path | tuple[Path, ...] = (
        EVIDENCE / "led_frequency.json",
        EVIDENCE / "matched_artifact_count.json",
    ),
) -> tuple[subprocess.CompletedProcess[str], Path]:
    proposal = tmp_path / "proposal.json"
    evidence_paths = (evidence,) if isinstance(evidence, Path) else evidence
    command = [
        sys.executable,
        "scripts/propose_input_feedback.py",
        "--graph",
        str(graph),
        "--rationale",
        str(rationale),
        "--policy",
        str(policy),
        "--proposal",
        str(proposal),
    ]
    for evidence_path in evidence_paths:
        command.extend(["--evidence", str(evidence_path)])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, proposal


def test_cli_valid_output_and_input_hash_stability(tmp_path: Path) -> None:
    tracked = [GRAPH, RATIONALE, POLICY, *EVIDENCE.glob("*.json")]
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked
    }
    first, proposal = invoke(tmp_path / "first")
    _, second_proposal = invoke(tmp_path / "second")
    assert first.returncode == 0
    assert json.loads(proposal.read_text())["status"] == "pass"
    assert proposal.read_bytes() == second_proposal.read_bytes()
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked
    } == before


def test_cli_stale_evidence_is_unknown_without_traceback(tmp_path: Path) -> None:
    result, proposal = invoke(
        tmp_path,
        evidence=(
            ROOT / "fixtures/feedback/invalid/stale-evidence.json",
            EVIDENCE / "matched_artifact_count.json",
        ),
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    value = json.loads(proposal.read_text())
    assert value["status"] == "unknown"
    assert "evidence" in value["error"]


def test_cli_unclassified_attribute_is_unknown(tmp_path: Path) -> None:
    graph_value = json.loads(GRAPH.read_text(encoding="utf-8"))
    for node in graph_value["nodes"]:
        if node["id"] == "fw.pin.led":
            node["attrs"]["new_attr"] = 0.0
    graph_path = tmp_path / "graph-unclassified.json"
    graph_path.write_text(
        json.dumps(graph_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result, proposal = invoke(
        tmp_path,
        graph=graph_path,
        policy=ROOT / "fixtures/feedback/invalid/unclassified-attr-policy.json",
        evidence=(EVIDENCE / "led_frequency.json",),
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    value = json.loads(proposal.read_text())
    assert value["status"] == "unknown"
    assert "unclassified" in value["error"]
