"""Validate that ACD agent definitions declare no unresolvable Skill names."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.subagent import AgentDefinition


def validate_acd_agent_skills(agent_dir: Path) -> list[AgentDefinition]:
    """Load ACD agent definitions and reject declared Skill names.

    The SDK subagent registry resolves ``skills:`` names eagerly against the user
    and project Skill stores only, and raises ``ValueError`` when a name is
    absent. Plugin-bundled Skills live in the plugin tree, so a declared name is
    unresolvable and aborts conversation startup on the installed-plugin path.
    ACD agents therefore reference plugin Skill assets by path in their prompt
    instead of declaring them.
    """
    if not agent_dir.is_dir():
        raise FileNotFoundError(f"ACD agent directory not found: {agent_dir}")
    definitions: list[AgentDefinition] = []
    for agent_path in sorted(agent_dir.glob("acd-*.md")):
        definition = AgentDefinition.load(agent_path)
        if definition.skills:
            raise ValueError(
                "agent definition declares Skill names that the SDK subagent "
                f"registry cannot resolve: {agent_path}: "
                f"{', '.join(definition.skills)}"
            )
        definitions.append(definition)
    if not definitions:
        raise FileNotFoundError(f"no ACD agent definitions found: {agent_dir}")
    return definitions


__all__ = ["validate_acd_agent_skills"]
