"""Declarative OpenHands conversation bootstrap for ACD."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openhands.sdk import LLM, Agent
from openhands.sdk.context import AgentContext
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.conversation.conversation_stats import ConversationStats
from openhands.sdk.conversation.stuck_detector import StuckDetectionThresholds
from openhands.sdk.hooks import HookConfig
from openhands.sdk.llm.utils.metrics import Metrics
from openhands.sdk.plugin import PluginSource
from openhands.sdk.security import ConfirmRisky, SecurityRisk
from openhands.sdk.subagent import AgentDefinition
from openhands.sdk.tool import Tool
from openhands.tools.browser_use import BrowserToolSet
from openhands.tools.task import TaskToolSet

from acd.openhands.gate_critic import AcdGateCritic, GateRequirement
from acd.openhands.plugin_distribution import validate_plugin_source
from acd.openhands.sdk_tools import register_acd_tools
from acd.openhands.secrets import build_acd_secret_mapping
from acd.openhands.security import build_acd_security_analyzer
from acd.openhands.skills import load_acd_skills


def build_acd_conversation(
    repo_root: Path,
    llm: LLM,
    requirements: list[GateRequirement],
    *,
    workspace: Path | None = None,
    persistence_dir: Path | None = None,
    plugin_root: Path | None = None,
    plugin_source: PluginSource | None = None,
    tools: list[Tool] | None = None,
    tool_concurrency_limit: int = 1,
    enable_browser: bool = False,
    hooks_path: Path | None = None,
    design_graph_path: Path | None = None,
    stuck_detection_thresholds: (
        StuckDetectionThresholds | Mapping[str, int] | None
    ) = None,
) -> LocalConversation:
    """Connect ACD's declarative pieces to an SDK LocalConversation."""
    repo_root = repo_root.resolve()
    workspace = (workspace or repo_root).resolve()
    persistence_dir = persistence_dir or repo_root / "out" / "agent-sessions"
    plugin_root = plugin_root or repo_root / "plugins" / "acd"
    hooks_path = hooks_path or plugin_root / "hooks" / "hooks.json"
    design_graph_path = design_graph_path or Path("fixtures/golden-design-1/graph.json")
    skills = load_acd_skills(plugin_root / "skills")
    hook_config = HookConfig.load(hooks_path)
    validate_acd_agent_hooks(plugin_root / "agents", hook_config)

    register_acd_tools()
    selected_tools = list(tools) if tools is not None else [Tool(name=TaskToolSet.name)]
    if enable_browser:
        if not BrowserToolSet.is_usable():
            raise RuntimeError(
                "browser_use was explicitly enabled but Chromium is unavailable"
            )
        selected_tools.append(Tool(name=BrowserToolSet.name))
    critic = AcdGateCritic(
        requirements=requirements,
        repo_root=repo_root,
        design_graph_path=design_graph_path,
    )
    agent_context = AgentContext(
        skills=skills,
        load_public_skills=False,
        load_user_skills=False,
        load_project_skills=False,
        load_memory=False,
        marketplace_path=None,
    )
    agent = Agent(
        llm=llm,
        tools=selected_tools,
        critic=critic,
        condenser=LLMSummarizingCondenser(llm=llm),
        agent_context=agent_context,
        tool_concurrency_limit=tool_concurrency_limit,
    )
    selected_plugin = plugin_source or PluginSource(source=str(plugin_root))
    conversation = LocalConversation(
        agent=agent,
        workspace=workspace,
        plugins=[validate_plugin_source(selected_plugin)],
        persistence_dir=persistence_dir,
        hook_config=hook_config,
        stuck_detection=True,
        stuck_detection_thresholds=stuck_detection_thresholds,
        secrets=build_acd_secret_mapping(),
    )
    conversation.set_security_analyzer(build_acd_security_analyzer())
    conversation.set_confirmation_policy(
        ConfirmRisky(threshold=SecurityRisk.MEDIUM)
    )
    return conversation


def _hook_commands(hook_config: HookConfig) -> dict[str, str]:
    """Return named hook commands from a hook configuration."""
    commands: dict[str, str] = {}
    for matchers in (hook_config.pre_tool_use, hook_config.stop):
        for matcher in matchers:
            for hook in matcher.hooks:
                if hook.name is not None:
                    commands[hook.name] = hook.command
    return commands


def validate_acd_agent_hooks(
    agent_dir: Path,
    hook_config: HookConfig,
) -> list[AgentDefinition]:
    """Load ACD agent definitions and enforce the required hook commands."""
    if not agent_dir.is_dir():
        raise FileNotFoundError(f"ACD agent directory not found: {agent_dir}")
    required = {
        "protect-derived-projections",
        "require-order-evidence",
        "require-gate-after-input-change",
    }
    expected = _hook_commands(hook_config)
    definitions: list[AgentDefinition] = []
    for agent_path in sorted(agent_dir.glob("acd-*.md")):
        definition = AgentDefinition.load(agent_path)
        if definition.hooks is None:
            raise ValueError(f"agent definition has no hooks: {agent_path}")
        actual = _hook_commands(definition.hooks)
        if any(
            name not in actual or actual[name] != expected.get(name)
            for name in required
        ):
            raise ValueError(f"agent definition hooks drifted: {agent_path}")
        definitions.append(definition)
    if not definitions:
        raise FileNotFoundError(f"no ACD agent definitions found: {agent_dir}")
    return definitions


def write_conversation_metrics(metrics: Metrics, path: Path) -> None:
    """Write SDK metrics as progress metadata, never as pass evidence."""
    payload: dict[str, Any] = {
        "artifact_kind": "conversation_metrics",
        "pass_evidence": False,
        "description": "This is not pass evidence.",
        "metrics": metrics.model_dump(mode="json"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_conversation_stats(stats: ConversationStats, path: Path) -> None:
    """Write SDK conversation statistics as non-authoritative observations."""
    snapshot = stats.model_dump(context={"use_snapshot": True})
    payload: dict[str, Any] = {
        "artifact_kind": "conversation_stats",
        "pass_evidence": False,
        "description": "This is not pass evidence.",
        "combined_metrics": stats.get_combined_metrics().model_dump(mode="json"),
        "usage_to_metrics": snapshot["usage_to_metrics"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
