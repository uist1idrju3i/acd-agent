"""Tests for the VibeBB loop and recovery command assets."""

from __future__ import annotations

from pathlib import Path

import pytest
from openhands.sdk.plugin.format.claude_code import ClaudeCodePluginFormat

from acd.openhands.tools.registration import generate_tool_registration_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "acd"


@pytest.mark.parametrize("name", ["vibebb-loop", "vibebb-recover"])
def test_vibebb_commands_load_with_registered_tools(name: str) -> None:
    commands = ClaudeCodePluginFormat().load_commands(PLUGIN_ROOT)
    command = next(item for item in commands if item.name == name)
    registered = {
        item.tool_name for item in generate_tool_registration_manifest().tools
    }

    assert command.description
    assert command.argument_hint
    assert command.allowed_tools
    assert set(command.allowed_tools) <= registered
    assert "terminal" not in command.allowed_tools


def test_recover_command_declares_bounded_recovery_arguments() -> None:
    commands = ClaudeCodePluginFormat().load_commands(PLUGIN_ROOT)
    command = next(item for item in commands if item.name == "vibebb-recover")

    hint = command.argument_hint or ""
    assert "--recover-lanes" in hint
    assert "--max-exploration-candidates" in hint
    assert "--max-exploration-rounds" in hint
    assert "acd_register_firmware_capability" in (command.allowed_tools or ())
