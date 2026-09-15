"""Tests for the fail-closed ACD Skill contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from openhands.sdk.context import KeywordTrigger, Skill
from openhands.sdk.skills.exceptions import SkillValidationError

from acd.openhands.distribution.skills import load_acd_skills

PLUGIN_SKILLS = Path("plugins/acd/skills")


def _write_skill(root: Path, name: str, front_matter: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{front_matter}\n---\n\n# {name}\n\nbody\n", encoding="utf-8")
    return path


VALID_FRONT_MATTER = (
    "name: {name}\n"
    "description: Do something. Use when asked.\n"
    "license: BSD-3-Clause\n"
    "triggers:\n  - alpha\n  - beta"
)


def test_bundled_skills_satisfy_the_contract() -> None:
    skills = load_acd_skills(PLUGIN_SKILLS)
    assert [skill.name for skill in skills] == sorted(
        path.parent.name for path in PLUGIN_SKILLS.glob("*/SKILL.md")
    )


def test_bundled_skills_carry_japanese_keywords_and_usage_cues() -> None:
    for skill in load_acd_skills(PLUGIN_SKILLS):
        assert isinstance(skill.trigger, KeywordTrigger)
        assert any(not keyword.isascii() for keyword in skill.trigger.keywords), skill.name
        assert " Use " in f" {skill.description}", skill.name


def test_valid_skill_loads(tmp_path: Path) -> None:
    _write_skill(tmp_path, "good", VALID_FRONT_MATTER.format(name="good"))
    assert [skill.name for skill in load_acd_skills(tmp_path)] == ["good"]


@pytest.mark.parametrize(
    ("front_matter", "message"),
    [
        (
            "name: good\nlicense: BSD-3-Clause\ntriggers:\n  - alpha",
            "description is required",
        ),
        (
            "name: good\ndescription: "
            + "x" * (Skill.MAX_DESCRIPTION_LENGTH + 1)
            + "\nlicense: BSD-3-Clause\ntriggers:\n  - alpha",
            "description exceeds",
        ),
        (
            "name: good\ndescription: d\ntriggers:\n  - alpha",
            "license is required",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause",
            "trigger must be a KeywordTrigger",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause\n"
            "triggers:\n  - alpha\npaths:\n  - 'src/**'",
            "trigger must be a KeywordTrigger",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause\n"
            "triggers:\n  - alpha\ninputs:\n  - name: x\n    description: y",
            "trigger must be a KeywordTrigger",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause\ntriggers: []",
            "trigger must be a KeywordTrigger",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause\ntriggers:\n  - alpha\n  - Alpha",
            "triggers must not repeat",
        ),
        (
            "name: good\ndescription: d\nlicense: BSD-3-Clause\n"
            "triggers:\n  - alpha\ndisable-model-invocation: true",
            "disable_model_invocation must be false",
        ),
    ],
)
def test_contract_violations_fail_closed(tmp_path: Path, front_matter: str, message: str) -> None:
    _write_skill(tmp_path, "good", front_matter)
    with pytest.raises(ValueError, match=message):
        load_acd_skills(tmp_path)


def test_name_directory_mismatch_is_rejected_by_the_sdk_loader(tmp_path: Path) -> None:
    _write_skill(tmp_path, "good", VALID_FRONT_MATTER.format(name="other"))
    with pytest.raises(SkillValidationError, match="does not match directory"):
        load_acd_skills(tmp_path)


def test_one_bad_skill_blocks_the_whole_directory(tmp_path: Path) -> None:
    _write_skill(tmp_path, "good", VALID_FRONT_MATTER.format(name="good"))
    _write_skill(tmp_path, "bad", "name: bad\ndescription: d\nlicense: L")
    with pytest.raises(ValueError, match="ACD skill contract violated"):
        load_acd_skills(tmp_path)
