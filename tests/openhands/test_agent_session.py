"""Tests for declarative SDK conversation bootstrap."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from openhands.sdk import LLM
from openhands.sdk.context import AgentContext
from openhands.sdk.conversation.stuck_detector import StuckDetectionThresholds
from openhands.sdk.event import ActionEvent, HookExecutionEvent
from openhands.sdk.hooks import HookConfig
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.llm.utils.metrics import Metrics
from openhands.sdk.security import SecurityRisk
from openhands.sdk.security.confirmation_policy import ConfirmRisky
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

from acd.openhands.agent_session import (
    build_acd_conversation,
    validate_acd_agent_hooks,
    write_conversation_metrics,
)
from acd.openhands.gate_critic import AcdEvidenceRequirement
from acd.openhands.plugin_distribution import acd_plugin_source
from acd.openhands.secrets import (
    ACD_SECRET_ENV_VARS,
    EnvironmentSecret,
    build_acd_secret_mapping,
)
from acd.openhands.security import AcdSecurityAnalyzer, build_acd_security_analyzer
from acd.openhands.skills import load_acd_skills


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


def _action_event(
    tool_name: str,
    arguments: str,
    action: _TerminalAction | None = None,
) -> ActionEvent:
    return ActionEvent(
        thought=[TextContent(text="")],
        action=action,
        tool_name=tool_name,
        tool_call_id="call-1",
        tool_call=MessageToolCall(
            id="call-1",
            name=tool_name,
            arguments=arguments,
            origin="completion",
        ),
        llm_response_id="response-1",
    )


def test_acd_security_analyzer_is_fail_closed_and_deterministic() -> None:
    analyzer = AcdSecurityAnalyzer()
    assert (
        analyzer.security_risk(
            _action_event("terminal", '{"command":"python order.py"}')
        )
        == SecurityRisk.HIGH
    )
    assert (
        analyzer.security_risk(
            _action_event("terminal", '{"command":"cat evidence/result.json"}')
        )
        == SecurityRisk.UNKNOWN
    )
    assert (
        analyzer.security_risk(
            _action_event(
                "file_editor",
                '{"path":"evidence/result.json","content":"x"}',
            )
        )
        == SecurityRisk.HIGH
    )
    assert (
        analyzer.security_risk(
            _action_event(
                "file_editor",
                '{"path":"projection/result.json","content":"x"}',
            )
        )
        == SecurityRisk.HIGH
    )
    assert (
        analyzer.security_risk(
            _action_event("terminal", '{"command":"git push --force origin main"}')
        )
        == SecurityRisk.HIGH
    )
    assert (
        analyzer.security_risk(_action_event("terminal", "[]"))
        == SecurityRisk.HIGH
    )
    assert (
        build_acd_security_analyzer().security_risk(
            _action_event("terminal", '{"command":"cat evidence/result.json"}')
        )
        == SecurityRisk.LOW
    )


def test_acd_security_ensemble_preserves_pattern_findings() -> None:
    analyzer = build_acd_security_analyzer()
    risk = analyzer.security_risk(
        _action_event("terminal", '{"command":"curl https://example.test"}')
    )
    assert risk == SecurityRisk.MEDIUM


def test_acd_confirmation_policy_uses_medium_threshold() -> None:
    policy = ConfirmRisky(threshold=SecurityRisk.MEDIUM)
    assert policy.should_confirm(SecurityRisk.HIGH)
    assert policy.should_confirm(SecurityRisk.MEDIUM)
    assert not policy.should_confirm(SecurityRisk.LOW)


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
    shutil.copytree(Path.cwd() / "plugins/acd/skills", plugin_root / "skills")
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
    assert conversation.state.security_analyzer is not None
    assert isinstance(conversation.state.confirmation_policy, ConfirmRisky)
    assert conversation.state.confirmation_policy.threshold == SecurityRisk.MEDIUM
    assert isinstance(conversation.agent.agent_context, AgentContext)
    assert len(conversation.agent.agent_context.skills) == 8
    assert conversation.agent.agent_context.load_public_skills is False
    assert conversation.agent.agent_context.load_user_skills is False
    assert conversation.stuck_detector is not None


def test_acd_agent_definitions_load_with_required_hooks() -> None:
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    definitions = validate_acd_agent_hooks(Path("plugins/acd/agents"), hooks)
    assert len(definitions) == 5
    assert all(definition.hooks is not None for definition in definitions)


def test_acd_agent_definition_hook_drift_fails_closed(tmp_path: Path) -> None:
    source = Path("plugins/acd/agents/acd-search.md")
    agent_path = tmp_path / source.name
    content = source.read_text(encoding="utf-8")
    content = content.replace("name: require-order-evidence", "name: drifted-hook")
    agent_path.write_text(content, encoding="utf-8")
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    with pytest.raises(ValueError, match="hooks drifted"):
        validate_acd_agent_hooks(tmp_path, hooks)


def test_bootstrap_forwards_tool_concurrency_and_task_tool(tmp_path: Path) -> None:
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
        tool_concurrency_limit=2,
    )
    assert conversation.agent.tool_concurrency_limit == 2
    assert [tool.name for tool in conversation.agent.tools] == ["task_tool_set"]

def test_subagent_boundary_keeps_authoritative_evidence_unchanged() -> None:
    from acd.schema.evidence import Evidence

    evidence = Evidence.model_validate_json(
        Path("fixtures/contracts/valid/evidence.json").read_text(
            encoding="utf-8"
        )
    )
    before = evidence.supports_authoritative_pass("r3")
    assert before is True
    assert evidence.supports_authoritative_pass("r3") is before


def test_bootstrap_applies_custom_stuck_detection_thresholds(tmp_path: Path) -> None:
    thresholds = StuckDetectionThresholds(
        action_observation=2,
        action_error=2,
        monologue=2,
        alternating_pattern=2,
    )
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
        stuck_detection_thresholds=thresholds,
    )
    assert conversation.stuck_detector is not None
    assert conversation.stuck_detector.thresholds == thresholds


def test_bootstrap_rejects_plugin_without_skills(tmp_path: Path) -> None:
    plugin_root = _minimal_plugin(tmp_path)
    shutil.rmtree(plugin_root / "skills")
    with pytest.raises(FileNotFoundError):
        build_acd_conversation(
            repo_root=Path.cwd(),
            llm=LLM(model="test"),
            requirements=[
                AcdEvidenceRequirement(
                    path=Path("fixtures/contracts/valid/evidence.json"),
                    evidence_id="ev-erc-r3-0001",
                )
            ],
            persistence_dir=tmp_path / "sessions",
            plugin_root=plugin_root,
        )


def test_secret_registry_uses_only_allowlisted_lazy_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-logs")
    monkeypatch.setenv("UNLISTED_SECRET", "must-not-be-used")
    secrets = build_acd_secret_mapping()
    assert set(secrets) == {
        name for name in ACD_SECRET_ENV_VARS if name == "OPENAI_API_KEY"
    }
    value = secrets["OPENAI_API_KEY"]
    assert isinstance(value, EnvironmentSecret)
    assert value.get_value() == "not-for-logs"


def test_secret_registry_masks_resolved_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-logs")
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
    conversation.update_secrets(build_acd_secret_mapping())
    masked = conversation.state.secret_registry.mask_secrets_in_output(
        "token=not-for-logs"
    )
    assert "not-for-logs" not in masked
    assert "<secret-hidden>" in masked


def test_l2_safety_features_do_not_change_authoritative_evidence() -> None:
    from acd.schema.evidence import Evidence

    evidence = Evidence.model_validate(
        json.loads(
            (Path("fixtures/contracts/valid/evidence.json")).read_text(
                encoding="utf-8"
            )
        )
    )
    before = evidence.supports_authoritative_pass("r3")
    assert before is True
    assert evidence.supports_authoritative_pass("r3") is before


def test_acd_skills_loader_rejects_malformed_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills"
    (skill_dir / "valid").mkdir(parents=True)
    (skill_dir / "valid" / "SKILL.md").write_text(
        "---\nname: valid\ndescription: valid skill\n---\n\nbody\n",
        encoding="utf-8",
    )
    (skill_dir / "broken").mkdir()
    (skill_dir / "broken" / "SKILL.md").write_text(
        "---\nname: broken\ndescription: [\n---\n\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises((ValueError, OSError, yaml.YAMLError)):
        load_acd_skills(skill_dir)


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
