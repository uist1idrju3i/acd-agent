from __future__ import annotations

from pathlib import Path

from openhands.sdk.hooks.config import HookConfig
from openhands.sdk.hooks.types import HookEventType

HOOKS_PATH = Path(__file__).parents[1] / "hooks.json"
RATIONALE_COMMAND = "uv run python scripts/check_rationale.py --if-present"


def test_rationale_hooks_match_sdk_tool_name_and_commands() -> None:
    config = HookConfig.load(HOOKS_PATH)

    post_hooks = config.get_hooks_for_event(HookEventType.POST_TOOL_USE, "file_editor")
    assert len(post_hooks) == 1
    assert post_hooks[0].command == f"{RATIONALE_COMMAND} --warn-only"
    assert not config.get_hooks_for_event(
        HookEventType.POST_TOOL_USE, "FileEditorTool"
    )

    stop_hooks = config.get_hooks_for_event(HookEventType.STOP, "file_editor")
    assert len(stop_hooks) == 1
    assert stop_hooks[0].command == RATIONALE_COMMAND
