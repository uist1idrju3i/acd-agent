"""Fail-closed loading of the repository's ACD skills."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.context import Skill, load_skills_from_dir


def load_acd_skills(skill_dir: Path) -> list[Skill]:
    """Load only local ACD skills and reject malformed skill assets."""
    skill_dir = skill_dir.resolve()
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"ACD skill directory does not exist: {skill_dir}")

    skill_files = sorted(skill_dir.glob("*/SKILL.md"))
    if not skill_files:
        raise FileNotFoundError(f"No ACD skill assets found in {skill_dir}")

    # The SDK loader intentionally logs and skips malformed files. ACD's local
    # contract is stricter, so validate every discovered asset before loading.
    for skill_file in skill_files:
        Skill.load(skill_file, skill_base_dir=skill_dir, strict=False)

    repo_skills, knowledge_skills, agent_skills = load_skills_from_dir(skill_dir)
    loaded = [*repo_skills.values(), *knowledge_skills.values(), *agent_skills.values()]
    if len(loaded) != len(skill_files):
        raise ValueError(
            f"ACD skill loader returned {len(loaded)} of {len(skill_files)} assets"
        )
    return sorted(loaded, key=lambda skill: skill.name)
