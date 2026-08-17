"""Tests for deterministic ACD gate critic behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from acd_tools.gate_critic import (
    AcdEvidenceRequirement,
    AcdGateCritic,
    AcdManifestRequirement,
)

ROOT = Path(__file__).parents[3]
EVIDENCE_SOURCE = ROOT / "fixtures/contracts/valid/evidence.json"


def _evidence(tmp_path: Path, *, unknown: bool = False, stale: bool = False) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    value = json.loads(EVIDENCE_SOURCE.read_text(encoding="utf-8"))
    value["target_revision"] = "r1"
    value["envelope"]["target_revision"] = "r1"
    if unknown:
        value["envelope"]["tool_version"] = "unknown"
    if stale:
        value["status"] = "stale"
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_evidence_uses_design_revision(tmp_path: Path) -> None:
    path = _evidence(tmp_path)
    result = AcdGateCritic(
        repo_root=ROOT,
        requirements=[
            AcdEvidenceRequirement(path=path, evidence_id="ev-erc-r3-0001")
        ],
    ).evaluate([], None)
    assert result.score == 1.0


def test_manifest_requirement_passes_and_events_do_not_change_score(tmp_path: Path) -> None:
    path = tmp_path / "fab-package.json"
    path.write_text(
        json.dumps({"status": "ready", "gates": {"drc": "pass"}, "unknowns": {}}),
        encoding="utf-8",
    )
    critic = AcdGateCritic(
        repo_root=ROOT,
        requirements=[AcdManifestRequirement(path=path)],
    )
    assert critic.evaluate([], None).score == critic.evaluate([], "changed").score
    assert critic.evaluate([], None).score == 1.0


def test_order_readiness_manifest_checks_status_and_unknowns(tmp_path: Path) -> None:
    path = tmp_path / "order-readiness.json"
    path.write_text(
        json.dumps({"status": "ready", "unknowns": {}}),
        encoding="utf-8",
    )
    critic = AcdGateCritic(
        repo_root=ROOT,
        requirements=[
            AcdManifestRequirement(path=path, manifest_kind="order_readiness")
        ],
    )
    assert critic.evaluate([], None).score == 1.0
    path.write_text(
        json.dumps({"status": "ready", "unknowns": {"inventory": "unknown"}}),
        encoding="utf-8",
    )
    assert critic.evaluate([], None).score == 0.0


def test_missing_invalid_stale_unknown_and_unready_requirements_fail(tmp_path: Path) -> None:
    missing = AcdEvidenceRequirement(
        path=Path("missing.json"), evidence_id="missing"
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    stale = _evidence(tmp_path / "stale", stale=True)
    unknown = _evidence(tmp_path / "unknown", unknown=True)
    unready = tmp_path / "unready.json"
    unready.write_text(
        json.dumps({"status": "not_order_ready", "gates": {}, "unknowns": {}}),
        encoding="utf-8",
    )
    critic = AcdGateCritic(
        repo_root=ROOT,
        requirements=[
            missing,
            AcdEvidenceRequirement(path=invalid, evidence_id="x"),
            AcdEvidenceRequirement(path=stale, evidence_id="ev-erc-r3-0001"),
            AcdEvidenceRequirement(path=unknown, evidence_id="ev-erc-r3-0001"),
            AcdManifestRequirement(path=unready),
        ],
    )
    result = critic.evaluate([], None)
    assert result.score == 0.0
    assert result.message is not None
    assert "missing" in result.message
    assert "not ready" in result.message


def test_followup_prompt_is_deterministic_and_not_pass_evidence() -> None:
    critic = AcdGateCritic(
        requirements=[
            AcdManifestRequirement(path=Path("missing.json")),
        ]
    )
    result = critic.evaluate([], None)
    prompt = critic.get_followup_prompt(result, 2)
    assert "Do not rewrite gates, thresholds, or Evidence files" in prompt
    assert "Critic output is not pass evidence." in prompt


def test_model_round_trip_preserves_paths_and_config() -> None:
    critic = AcdGateCritic(
        requirements=[
            AcdEvidenceRequirement(
                path=Path("out/evidence.json"), evidence_id="evidence.example"
            ),
            AcdManifestRequirement(path=Path("out/fab-package.json")),
        ]
    )
    restored = AcdGateCritic.model_validate_json(critic.model_dump_json())
    assert restored == critic
    assert restored.iterative_refinement is not None
    assert restored.iterative_refinement.success_threshold == 1.0
    assert restored.iterative_refinement.max_iterations == 3


def test_unresolvable_revision_fails_closed(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text("{}", encoding="utf-8")
    result = AcdGateCritic(
        repo_root=tmp_path,
        design_graph_path=Path("graph.json"),
        requirements=[AcdManifestRequirement(path=Path("manifest.json"))],
    ).evaluate([], None)
    assert result.score == 0.0
    assert "revision" in (result.message or "")


def test_dirty_design_input_fails_closed(tmp_path: Path) -> None:
    graph = tmp_path / "fixtures/golden-design-1/graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text(
        (ROOT / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=tmp_path,
        check=True,
    )
    graph.write_text(graph.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = AcdGateCritic(
        repo_root=tmp_path,
        requirements=[AcdManifestRequirement(path=Path("manifest.json"))],
    ).evaluate([], None)
    assert result.score == 0.0
    assert "revision" in (result.message or "")
