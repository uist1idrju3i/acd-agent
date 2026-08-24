"""Tests for the VibeBB loop command asset."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.plugin.format.claude_code import ClaudeCodePluginFormat

from acd.openhands.tools.registration import generate_tool_registration_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "acd"


def test_vibebb_loop_command_loads_with_registered_tools() -> None:
    commands = ClaudeCodePluginFormat().load_commands(PLUGIN_ROOT)
    command = next(item for item in commands if item.name == "vibebb-loop")
    registered = {
        item.tool_name for item in generate_tool_registration_manifest().tools
    }

    assert command.description
    assert command.argument_hint
    assert command.allowed_tools
    assert set(command.allowed_tools) <= registered
    assert "terminal" not in command.allowed_tools
