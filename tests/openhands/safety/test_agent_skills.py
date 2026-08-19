"""Tests for fail-closed ACD agent Skill declaration validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.openhands.safety.agent_skills import validate_acd_agent_skills

AGENT_DIR = Path("plugins/acd/agents")


def test_acd_agent_definitions_declare_no_subagent_skills() -> None:
    definitions = validate_acd_agent_skills(AGENT_DIR)
    assert len(definitions) == 5
    assert all(definition.skills == [] for definition in definitions)


def test_acd_agent_definitions_reference_plugin_skill_assets_by_path() -> None:
    for agent_path in sorted(AGENT_DIR.glob("acd-*.md")):
        body = agent_path.read_text(encoding="utf-8")
        for reference in body.split("skills/")[1:]:
            skill_name = reference.split("/", 1)[0]
            assert (Path("plugins/acd/skills") / skill_name / "SKILL.md").is_file()


def test_declared_skill_name_fails_closed(tmp_path: Path) -> None:
    source = AGENT_DIR / "acd-search.md"
    agent_path = tmp_path / source.name
    agent_path.write_text(
        source.read_text(encoding="utf-8").replace(
            "model: inherit",
            "model: inherit\nskills:\n  - acd-placement-search",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot resolve"):
        validate_acd_agent_skills(tmp_path)


def test_missing_agent_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_acd_agent_skills(tmp_path / "absent")
    with pytest.raises(FileNotFoundError):
        validate_acd_agent_skills(tmp_path)
