"""Tests for the ACD GoalController driver and observation boundary."""

from __future__ import annotations

import json
import signal
from collections.abc import Callable
from pathlib import Path
from types import FrameType, SimpleNamespace
from typing import cast

from openhands.sdk.conversation import ConversationExecutionStatus
from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.conversation.conversation_stats import ConversationStats
from openhands.sdk.event import Event
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.testing import TestLLM

from acd.openhands.session.bootstrap import write_conversation_stats
from acd.openhands.session.goal_loop import (
    AcdGoalResult,
    install_goal_interrupt,
    run_acd_goal,
    write_goal_result,
)
from acd.schema.evidence import Evidence


class _FakeConversation:
    def __init__(self, *, pause_after_run: bool = False) -> None:
        self.state = SimpleNamespace(
            events=cast(list[Event], []),
            execution_status=ConversationExecutionStatus.IDLE,
        )
        self.messages: list[str] = []
        self.runs = 0
        self.interruptions = 0
        self.pause_after_run = pause_after_run

    def send_message(self, message: str) -> None:
        self.messages.append(message)

    def run(self) -> None:
        self.runs += 1
        if self.pause_after_run:
            self.state.execution_status = ConversationExecutionStatus.PAUSED

    def interrupt(self) -> None:
        self.interruptions += 1


def _conversation(
    fake: _FakeConversation,
) -> BaseConversation:
    return cast(BaseConversation, fake)


def _judge_llm(*, complete: bool, count: int = 1) -> TestLLM:
    message = Message(
        role="assistant",
        content=[
            TextContent(
                text=json.dumps(
                    {
                        "score": 1.0 if complete else 0.2,
                        "complete": complete,
                        "missing": "" if complete else "gate remains",
                    }
                )
            )
        ],
    )
    return TestLLM.from_messages([message] * count)


def test_goal_loop_completes_in_one_iteration() -> None:
    conversation = _FakeConversation()
    result = run_acd_goal(
        _conversation(conversation),
        "finish the design",
        _judge_llm(complete=True),
        gate_evaluator=lambda _conversation: (True, True),
    )

    assert result.status == "complete"
    assert result.iterations == 1
    assert result.verdict is not None
    assert result.gate_passed is True
    assert result.authoritative is True


def test_goal_loop_caps_after_max_iterations() -> None:
    conversation = _FakeConversation()
    result = run_acd_goal(
        _conversation(conversation),
        "finish the design",
        _judge_llm(complete=False, count=2),
        max_iterations=2,
    )

    assert result.status == "capped"
    assert result.iterations == 2
    assert conversation.runs == 2


def test_goal_loop_interruption_skips_judge() -> None:
    conversation = _FakeConversation(pause_after_run=True)
    result = run_acd_goal(
        _conversation(conversation),
        "finish the design",
        _judge_llm(complete=True),
        gate_evaluator=lambda _conversation: (True, True),
    )

    assert result.status == "interrupted"
    assert result.iterations == 1
    assert result.verdict is None
    assert result.gate_passed is True
    assert result.authoritative is True


def test_goal_judge_completion_does_not_pass_gate() -> None:
    conversation = _FakeConversation()
    result = run_acd_goal(
        _conversation(conversation),
        "finish the design",
        _judge_llm(complete=True),
        gate_evaluator=lambda _conversation: (False, False),
    )

    assert result.verdict is not None
    assert result.verdict.complete is True
    assert result.gate_passed is False
    assert result.authoritative is False


def test_goal_gate_exception_fails_closed() -> None:
    conversation = _FakeConversation()

    def raise_gate(_conversation: BaseConversation) -> tuple[bool, bool]:
        raise RuntimeError("gate unavailable")

    result = run_acd_goal(
        _conversation(conversation),
        "finish the design",
        _judge_llm(complete=True),
        gate_evaluator=raise_gate,
    )

    assert result.gate_passed is False
    assert result.authoritative is False


def test_goal_loop_does_not_write_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence" / "goal.json"
    evidence = Evidence.model_validate_json(
        Path("fixtures/contracts/valid/evidence.json").read_text()
    )
    authoritative_before = evidence.supports_authoritative_pass("r3")
    result = run_acd_goal(
        _conversation(_FakeConversation()),
        "finish the design",
        _judge_llm(complete=True),
    )
    assert result.authoritative is False
    assert not evidence_path.exists()
    assert evidence.supports_authoritative_pass("r3") is authoritative_before


def test_goal_and_stats_artifacts_are_not_pass_evidence(tmp_path: Path) -> None:
    goal_path = tmp_path / "goal-result.json"
    stats_path = tmp_path / "conversation-stats.json"
    result = AcdGoalResult(
        objective="finish the design",
        status="complete",
        iterations=1,
        verdict=None,
        gate_passed=False,
        authoritative=False,
    )

    write_goal_result(result, goal_path)
    write_conversation_stats(ConversationStats(), stats_path)

    assert json.loads(goal_path.read_text())["pass_evidence"] is False
    stats_payload = json.loads(stats_path.read_text())
    assert stats_payload["pass_evidence"] is False
    assert stats_payload["artifact_kind"] == "conversation_stats"
    assert stats_payload["usage_to_metrics"] == {}


def test_sigint_interrupt_handler_is_restored() -> None:
    conversation = _FakeConversation()
    previous = signal.getsignal(signal.SIGINT)
    with install_goal_interrupt(_conversation(conversation)):
        handler = cast(
            Callable[[int, FrameType | None], None],
            signal.getsignal(signal.SIGINT),
        )
        handler(signal.SIGINT, None)
        assert conversation.interruptions == 1
    assert signal.getsignal(signal.SIGINT) == previous
