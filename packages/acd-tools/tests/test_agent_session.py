"""Tests for declarative SDK conversation bootstrap."""

from __future__ import annotations

import json
from pathlib import Path

from openhands.sdk import LLM

from acd_tools.agent_session import build_acd_conversation, write_conversation_metrics
from acd_tools.gate_critic import AcdEvidenceRequirement


def test_bootstrap_wires_sdk_conversation_without_llm_call(tmp_path: Path) -> None:
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=LLM(model="test"),
        requirements=[
            AcdEvidenceRequirement(
                path=Path("fixtures/contracts/valid/evidence.json"),
                evidence_id="ev-erc-r3-0001",
            )
        ],
        persistence_dir=tmp_path / "sessions",
    )
    assert conversation.agent.critic is not None
    assert conversation.agent.condenser is not None
    assert conversation.workspace.working_dir == str(Path.cwd())


def test_metrics_are_marked_as_non_evidence(tmp_path: Path) -> None:
    class Stats:
        def get_combined_metrics(self):
            class Metrics:
                def model_dump(self, mode: str):
                    return {"accumulated_cost": 0.0}

            return Metrics()

    class Conversation:
        conversation_stats = Stats()

    path = tmp_path / "metrics.json"
    write_conversation_metrics(Conversation(), path)  # type: ignore[arg-type]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pass_evidence"] is False
