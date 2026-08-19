"""Validate ACD agent hook declarations against the plugin hook contract."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.hooks import HookConfig
from openhands.sdk.subagent import AgentDefinition

REQUIRED_ACD_HOOK_NAMES = frozenset(
    {
        "protect-derived-projections",
        "require-order-evidence",
        "require-gate-after-input-change",
    }
)


def _hook_commands(hook_config: HookConfig) -> dict[str, str]:
    """Return named hook commands from a hook configuration."""
    commands: dict[str, str] = {}
    for matchers in (hook_config.pre_tool_use, hook_config.stop):
        for matcher in matchers:
            for hook in matcher.hooks:
                if hook.name is not None:
                    commands[hook.name] = hook.command
    return commands


def validate_acd_hook_config(hook_config: HookConfig) -> None:
    """Require every fail-closed ACD hook declaration."""
    commands = _hook_commands(hook_config)
    if any(
        name not in commands or not commands[name].strip()
        for name in REQUIRED_ACD_HOOK_NAMES
    ):
        raise ValueError("ACD order execution requires all safety hooks")


def validate_acd_agent_hooks(
    agent_dir: Path,
    hook_config: HookConfig,
) -> list[AgentDefinition]:
    """Load ACD agent definitions and enforce the required hook commands."""
    if not agent_dir.is_dir():
        raise FileNotFoundError(f"ACD agent directory not found: {agent_dir}")
    validate_acd_hook_config(hook_config)
    expected = _hook_commands(hook_config)
    definitions: list[AgentDefinition] = []
    for agent_path in sorted(agent_dir.glob("acd-*.md")):
        definition = AgentDefinition.load(agent_path)
        if definition.hooks is None:
            raise ValueError(f"agent definition has no hooks: {agent_path}")
        actual = _hook_commands(definition.hooks)
        if any(
            name not in actual or actual[name] != expected.get(name)
            for name in REQUIRED_ACD_HOOK_NAMES
        ):
            raise ValueError(f"agent definition hooks drifted: {agent_path}")
        definitions.append(definition)
    if not definitions:
        raise FileNotFoundError(f"no ACD agent definitions found: {agent_dir}")
    return definitions


__all__ = [
    "REQUIRED_ACD_HOOK_NAMES",
    "validate_acd_agent_hooks",
    "validate_acd_hook_config",
]
