"""Tests for fail-closed ACD agent hook validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from openhands.sdk import LLM
from openhands.sdk.hooks import HookConfig
from openhands.sdk.tool import Tool
from openhands.sdk.tool.registry import (
    list_registered_tools,
    resolve_tool,  # pyright: ignore[reportUnknownVariableType]
)
from openhands.tools.glob import GlobTool
from openhands.tools.grep import GrepTool
from openhands.tools.preset.default import register_default_tools

from acd.openhands.safety.hooks import validate_acd_agent_hooks
from acd.openhands.session.bootstrap import build_acd_conversation
from acd.openhands.session.gate_critic import AcdEvidenceRequirement


def test_acd_agent_definitions_load_with_required_hooks() -> None:
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    definitions = validate_acd_agent_hooks(Path("plugins/acd/agents"), hooks)
    assert len(definitions) == 5
    assert all(definition.hooks is not None for definition in definitions)


def test_acd_agent_definitions_resolve_all_tools_with_conversation_state(
    tmp_path: Path,
) -> None:
    register_default_tools(enable_browser=False)
    assert (GlobTool.name, GrepTool.name) == ("glob", "grep")
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
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    definitions = validate_acd_agent_hooks(Path("plugins/acd/agents"), hooks)
    registered = set(list_registered_tools())
    for definition in definitions:
        for tool_name in definition.tools:
            assert tool_name in registered
            assert resolve_tool(Tool(name=tool_name), conversation.state)


def test_acd_agent_definition_tool_resolution_rejects_broken_name(
    tmp_path: Path,
) -> None:
    source = Path("plugins/acd/agents/acd-search.md")
    agent_path = tmp_path / source.name
    content = source.read_text(encoding="utf-8").replace(
        "  - task_tool_set", "  - task"
    )
    agent_path.write_text(content, encoding="utf-8")
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    definitions = validate_acd_agent_hooks(tmp_path, hooks)
    register_default_tools(enable_browser=False)
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
    with pytest.raises(TypeError, match="conv_state"):
        resolve_tool(Tool(name=definitions[0].tools[-1]), conversation.state)


def test_acd_agent_definition_hook_drift_fails_closed(tmp_path: Path) -> None:
    source = Path("plugins/acd/agents/acd-search.md")
    agent_path = tmp_path / source.name
    content = source.read_text(encoding="utf-8")
    content = content.replace("name: require-order-evidence", "name: drifted-hook")
    agent_path.write_text(content, encoding="utf-8")
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    with pytest.raises(ValueError, match="hooks drifted"):
        validate_acd_agent_hooks(tmp_path, hooks)


def test_acd_agent_definition_directory_is_required(tmp_path: Path) -> None:
    hooks = HookConfig.load(Path("plugins/acd/hooks/hooks.json"))
    with pytest.raises(FileNotFoundError, match="agent directory"):
        validate_acd_agent_hooks(tmp_path / "missing", hooks)
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="no ACD agent definitions"):
        validate_acd_agent_hooks(empty_dir, hooks)
