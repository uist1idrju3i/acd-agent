"""Tests for declarative SDK conversation bootstrap."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from openhands.sdk import LLM
from openhands.sdk.event import HookExecutionEvent
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.llm.utils.metrics import Metrics
from openhands.sdk.testing import TestLLM
from openhands.sdk.tool import (
    Action,
    Observation,
    Tool,
    ToolDefinition,
    ToolExecutor,
)
from openhands.sdk.tool import registry as tool_registry
from openhands.sdk.tool.registry import register_tool  # pyright: ignore[reportUnknownVariableType]

from acd_tools.agent_session import build_acd_conversation, write_conversation_metrics
from acd_tools.gate_critic import AcdEvidenceRequirement
from acd_tools.plugin_distribution import acd_plugin_source


class _TerminalAction(Action):
    command: str


class _TerminalObservation(Observation):
    pass


class _TerminalExecutor(ToolExecutor[_TerminalAction, _TerminalObservation]):
    def __call__(
        self, action: _TerminalAction, conversation: object | None = None
    ) -> _TerminalObservation:
        return _TerminalObservation.from_text(action.command)


class _TerminalTool(ToolDefinition[_TerminalAction, _TerminalObservation]):
    name = "terminal"

    @classmethod
    def create(cls, conv_state: object, **params: object) -> list[_TerminalTool]:
        return [
            cls(
                action_type=_TerminalAction,
                observation_type=_TerminalObservation,
                description="Test terminal tool",
                executor=_TerminalExecutor(),
            )
        ]


@pytest.fixture
def terminal_tool_registration() -> Iterator[None]:
    original_registry: Any = tool_registry._REG.get(  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType]
        "terminal"
    )
    original_usability: Any = tool_registry._USABILITY_REG.get(  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        "terminal"
    )
    original_module: Any = tool_registry._MODULE_QUALNAMES.get(  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        "terminal"
    )
    register_tool("terminal", _TerminalTool)  # pyright: ignore[reportUnknownVariableType]
    yield
    with tool_registry._LOCK:  # pyright: ignore[reportPrivateUsage]
        if original_registry is None:
            tool_registry._REG.pop(  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
                "terminal", None
            )
        else:
            tool_registry._REG["terminal"] = (  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
                original_registry
            )
        if original_usability is None:
            tool_registry._USABILITY_REG.pop(  # pyright: ignore[reportPrivateUsage]
                "terminal", None
            )
        else:
            tool_registry._USABILITY_REG["terminal"] = (  # pyright: ignore[reportPrivateUsage]
                original_usability
            )
        if original_module is None:
            tool_registry._MODULE_QUALNAMES.pop(  # pyright: ignore[reportPrivateUsage]
                "terminal", None
            )
        else:
            tool_registry._MODULE_QUALNAMES["terminal"] = (  # pyright: ignore[reportPrivateUsage]
                original_module
            )


def _minimal_plugin(tmp_path: Path) -> Path:
    plugin_root = tmp_path / "plugin"
    (plugin_root / ".plugin").mkdir(parents=True)
    shutil.copytree(Path.cwd() / "plugins/acd/hooks", plugin_root / "hooks")
    protect_script = plugin_root / "hooks/scripts/protect_projections.py"
    os.chmod(protect_script, 0o755)
    (plugin_root / "hooks/hooks.json").write_text(
        json.dumps(
            {
                "pre_tool_use": [
                    {
                        "matcher": "terminal",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 {protect_script}",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (plugin_root / ".plugin/plugin.json").write_text(
        '{"name":"acd-test","version":"0.0.1","description":"test plugin"}\n',
        encoding="utf-8",
    )
    return plugin_root


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
    assert conversation.agent.critic is not None
    assert conversation.state.execution_status.value == "idle"
    assert conversation.workspace.working_dir == str(Path.cwd())


def test_testllm_conversation_denies_protected_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_tool_registration: None,
) -> None:
    llm = TestLLM.from_messages(
        [
            Message(
                role="assistant",
                content=[TextContent(text="")],
                tool_calls=[
                    MessageToolCall(
                        id="call-1",
                        name="terminal",
                        arguments='{"command":"touch out/blocked.kicad_pcb"}',
                        origin="completion",
                    )
                ],
            )
        ]
    )
    plugin_root = _minimal_plugin(tmp_path)
    monkeypatch.setenv("ACD_PLUGIN_ROOT", str(plugin_root))
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=llm,
        requirements=[
            AcdEvidenceRequirement(
                path=Path("missing.json"),
                evidence_id="missing",
            )
        ],
        persistence_dir=tmp_path / "sessions",
        plugin_root=plugin_root,
        tools=[Tool(name="terminal")],
    )
    conversation.send_message("write a protected projection")
    conversation.agent.step(
        conversation,
        on_event=conversation._on_event,  # pyright: ignore[reportPrivateUsage]
    )

    assert not (Path("out") / "blocked.kicad_pcb").exists()
    assert any(
        isinstance(event, HookExecutionEvent)
        and event.tool_name == "terminal"
        and event.blocked
        for event in conversation.state.events
    )


def test_testllm_conversation_critic_refinement_stops_at_max_iterations(
    tmp_path: Path,
) -> None:
    finish = Message(
        role="assistant",
        content=[TextContent(text="")],
        tool_calls=[
            MessageToolCall(
                id="finish-call",
                name="finish",
                arguments='{"message":"done"}',
                origin="completion",
            )
        ],
    )
    llm = TestLLM.from_messages([finish, finish, finish, finish])
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=llm,
        requirements=[
            AcdEvidenceRequirement(
                path=Path("missing.json"),
                evidence_id="missing",
            )
        ],
        persistence_dir=tmp_path / "sessions",
        plugin_root=_minimal_plugin(tmp_path),
    )
    conversation.send_message("complete the task")
    conversation.run()

    assert conversation.state.agent_state["iterative_refinement_iteration"] == 3
    assert sum(
        "Deterministic ACD gate requirements remain unmet" in str(event)
        for event in conversation.state.events
    ) >= 1
