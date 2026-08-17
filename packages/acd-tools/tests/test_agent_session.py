"""Tests for declarative SDK conversation bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from openhands.sdk import LLM
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.llm.utils.metrics import Metrics
from openhands.sdk.testing import TestLLM

from acd_tools.agent_session import build_acd_conversation, write_conversation_metrics
from acd_tools.gate_critic import AcdEvidenceRequirement, AcdGateCritic
from acd_tools.plugin_distribution import acd_plugin_source


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
    path = tmp_path / "metrics.json"
    write_conversation_metrics(Metrics(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pass_evidence"] is False


def test_bootstrap_accepts_pinned_plugin_source(tmp_path: Path) -> None:
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
        plugin_source=acd_plugin_source("a" * 40),
    )
    assert conversation.agent is not None


def test_testllm_and_gate_critic_refinement_are_deterministic() -> None:
    llm = TestLLM.from_messages(
        [Message(role="assistant", content=[TextContent(text="done")])]
    )
    response = llm.completion([])  # pyright: ignore[reportUnknownMemberType]
    content = cast(TextContent, response.message.content[0])
    assert content.text == "done"

    critic = AcdGateCritic(
        repo_root=Path("/nonexistent"),
        requirements=[
            AcdEvidenceRequirement(
                path=Path("missing.json"),
                evidence_id="missing",
            )
        ],
    )
    result = critic.evaluate([], None)
    assert result.score == 0.0
    assert critic.should_refine(result)
    assert critic.iterative_refinement is not None
    assert critic.iterative_refinement.max_iterations == 3
    assert "Critic output is not pass evidence." in critic.get_followup_prompt(
        result, 1
    )
