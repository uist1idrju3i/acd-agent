"""Declarative OpenHands conversation bootstrap for ACD."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openhands.sdk import LLM, Agent
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.hooks import HookConfig
from openhands.sdk.llm.utils.metrics import Metrics
from openhands.sdk.plugin import PluginSource
from openhands.sdk.tool import Tool

from acd.openhands.gate_critic import AcdGateCritic, GateRequirement
from acd.openhands.plugin_distribution import validate_plugin_source
from acd.openhands.sdk_tools import register_acd_tools


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
    hooks_path: Path | None = None,
    design_graph_path: Path | None = None,
) -> LocalConversation:
    """Connect ACD's declarative pieces to an SDK LocalConversation."""
    repo_root = repo_root.resolve()
    workspace = (workspace or repo_root).resolve()
    persistence_dir = persistence_dir or repo_root / "out" / "agent-sessions"
    plugin_root = plugin_root or repo_root / "plugins" / "acd"
    hooks_path = hooks_path or plugin_root / "hooks" / "hooks.json"
    design_graph_path = design_graph_path or Path("fixtures/golden-design-1/graph.json")

    register_acd_tools()
    critic = AcdGateCritic(
        requirements=requirements,
        repo_root=repo_root,
        design_graph_path=design_graph_path,
    )
    agent = Agent(
        llm=llm,
        tools=tools or [],
        critic=critic,
        condenser=LLMSummarizingCondenser(llm=llm),
    )
    hook_config = HookConfig.load(hooks_path)
    selected_plugin = plugin_source or PluginSource(source=str(plugin_root))
    return LocalConversation(
        agent=agent,
        workspace=workspace,
        plugins=[validate_plugin_source(selected_plugin)],
        persistence_dir=persistence_dir,
        hook_config=hook_config,
    )


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
