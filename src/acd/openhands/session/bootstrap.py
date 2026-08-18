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
from openhands.sdk.tool import Tool
from openhands.tools.browser_use import BrowserToolSet
from openhands.tools.task import TaskToolSet

from acd.openhands.distribution.plugin import validate_plugin_source
from acd.openhands.distribution.skills import load_acd_skills
from acd.openhands.safety.hooks import validate_acd_agent_hooks
from acd.openhands.safety.secrets import build_acd_secret_mapping
from acd.openhands.safety.security import build_acd_security_analyzer
from acd.openhands.session.gate_critic import AcdGateCritic, GateRequirement
from acd.openhands.session.prompts import (
    DEFAULT_MANIFEST_NAME,
    PromptManifestError,
    check_prompt_manifest,
)
from acd.openhands.tools.definitions import register_acd_tools


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
    prompt_manifest_path: Path | None = None,
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
    prompt_manifest_path = (
        prompt_manifest_path or plugin_root / "agents" / DEFAULT_MANIFEST_NAME
    )
    try:
        agent_dir_root = plugin_root / "agents"
        asset_root = repo_root
        try:
            agent_dir_root.resolve().relative_to(repo_root)
        except ValueError:
            asset_root = plugin_root.parent
        prompt_report = check_prompt_manifest(
            agent_dir_root,
            prompt_manifest_path,
            root=asset_root,
        )
    except (OSError, ValueError) as exc:
        raise PromptManifestError("ACD role prompt manifest verification failed") from exc
    if prompt_report.status != "pass":
        raise PromptManifestError(
            prompt_report.reason or "ACD role prompt manifest drifted"
        )
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
