"""Goal-driven conversation control at the ACD safety boundary."""

from __future__ import annotations

import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from openhands.sdk.conversation import ConversationExecutionStatus
from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.conversation.goal import (
    GoalController,
    GoalDone,
    GoalStatusName,
    GoalVerdict,
)
from openhands.sdk.io import FileStore
from openhands.sdk.llm import LLM
from pydantic import BaseModel

from acd.openhands.session.observation_store import (
    ObservationPayload,
    write_observation_payload,
)
from acd.openhands.session.routing import create_fixed_role_router
from acd.schema.model_routing import ModelRoutingPolicy

GateEvaluator = Callable[[BaseConversation], tuple[bool, bool]]


class AcdGoalResult(BaseModel):
    """Non-authoritative result of an ACD goal loop."""

    objective: str
    status: GoalStatusName
    iterations: int
    verdict: GoalVerdict | None
    gate_passed: bool
    authoritative: bool


def _evaluate_gate(
    conversation: BaseConversation,
    gate_evaluator: GateEvaluator | None,
) -> tuple[bool, bool]:
    if gate_evaluator is None:
        return False, False
    try:
        gate_passed, authoritative = gate_evaluator(conversation)
    except Exception:
        return False, False
    gate_passed = bool(gate_passed)
    return gate_passed, bool(authoritative and gate_passed)


def run_acd_goal(
    conversation: BaseConversation,
    objective: str,
    judge_llm: LLM,
    *,
    max_iterations: int = 10,
    gate_evaluator: GateEvaluator | None = None,
    model_routing_policy: ModelRoutingPolicy | None = None,
    routing_profile: str | None = None,
) -> AcdGoalResult:
    """Drive a goal with SDK decisions and ACD-owned I/O and authority checks."""
    if model_routing_policy is not None:
        judge_llm = create_fixed_role_router(
            model_routing_policy,
            "judge",
            judge_llm,
            profile=routing_profile,
        )
    controller = GoalController(
        objective,
        judge_llm,
        max_iterations=max_iterations,
    )
    conversation.send_message(controller.start())
    runs = 0
    while True:
        conversation.run()
        runs += 1
        if (
            conversation.state.execution_status
            == ConversationExecutionStatus.PAUSED
        ):
            gate_passed, authoritative = _evaluate_gate(
                conversation,
                gate_evaluator,
            )
            return AcdGoalResult(
                objective=objective,
                status="interrupted",
                iterations=runs,
                verdict=None,
                gate_passed=gate_passed,
                authoritative=authoritative,
            )

        step = controller.on_run_finished(conversation.state.events)
        if isinstance(step, GoalDone):
            gate_passed, authoritative = _evaluate_gate(
                conversation,
                gate_evaluator,
            )
            return AcdGoalResult(
                objective=objective,
                status=step.outcome.status,
                iterations=step.outcome.iterations,
                verdict=step.outcome.verdict,
                gate_passed=gate_passed,
                authoritative=authoritative,
            )
        conversation.send_message(step.followup)


@contextmanager
def install_goal_interrupt(conversation: BaseConversation) -> Generator[None, None, None]:
    """Route SIGINT to conversation interruption and restore its prior handler."""
    previous_handler = signal.getsignal(signal.SIGINT)

    def handle_interrupt(_signum: int, _frame: FrameType | None) -> None:
        conversation.interrupt()

    signal.signal(signal.SIGINT, handle_interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def write_goal_result(
    result: AcdGoalResult,
    path: Path,
    *,
    file_store: FileStore | None = None,
) -> None:
    """Write goal-loop metadata without creating pass evidence."""
    payload = ObservationPayload.model_validate(
        {
            "artifact_kind": "goal_result",
            "pass_evidence": False,
            "description": "This is not pass evidence.",
            "result": result.model_dump(mode="json"),
        }
    )
    write_observation_payload(payload, path, file_store=file_store)
