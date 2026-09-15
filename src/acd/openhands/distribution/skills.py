"""Fail-closed loading of the repository's ACD skills."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.context import KeywordTrigger, Skill, load_skills_from_dir

# The SDK silently clips descriptions longer than `Skill.MAX_DESCRIPTION_LENGTH`
# (1024, the AgentSkills cap) and splices this marker into the clipped text.
TRUNCATED_DESCRIPTION_MARKER = "<response clipped>"


def validate_acd_skill_contract(skill: Skill, skill_file: Path) -> None:
    """Reject a loaded Skill that does not satisfy ACD's plugin contract.

    Every bundled Skill must be a model-invocable AgentSkills asset whose
    description fits the prompt budget unclipped and whose trigger is a non-empty
    `KeywordTrigger`. `paths:` (PathTrigger) disables model
    invocation and `inputs:` (TaskTrigger) changes the activation semantics, so both
    fail closed instead of being loaded with unexpected behaviour.
    """
    problems: list[str] = []
    if not skill.is_agentskills_format:
        problems.append("must be an AgentSkills SKILL.md asset")
    description = (skill.description or "").strip()
    if not description:
        problems.append("description is required")
    elif TRUNCATED_DESCRIPTION_MARKER in description:
        problems.append(
            f"description exceeds {Skill.MAX_DESCRIPTION_LENGTH} characters "
            "and was clipped by the SDK"
        )
    if not (skill.license or "").strip():
        problems.append("license is required")
    trigger = skill.trigger
    if not isinstance(trigger, KeywordTrigger):
        problems.append(
            "trigger must be a KeywordTrigger declared via `triggers:` "
            f"(got {type(trigger).__name__ if trigger is not None else 'none'})"
        )
    else:
        keywords = [keyword.strip() for keyword in trigger.keywords]
        if not keywords or any(not keyword for keyword in keywords):
            problems.append("triggers must be non-empty keywords")
        elif len({keyword.lower() for keyword in keywords}) != len(keywords):
            problems.append("triggers must not repeat keywords")
    if skill.disable_model_invocation:
        problems.append("disable_model_invocation must be false")
    if problems:
        raise ValueError(f"ACD skill contract violated by {skill_file}: " + "; ".join(problems))


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
        skill = Skill.load(skill_file, skill_base_dir=skill_dir, strict=True)
        validate_acd_skill_contract(skill, skill_file)

    repo_skills, knowledge_skills, agent_skills = load_skills_from_dir(skill_dir)
    loaded = [*repo_skills.values(), *knowledge_skills.values(), *agent_skills.values()]
    if len(loaded) != len(skill_files):
        raise ValueError(f"ACD skill loader returned {len(loaded)} of {len(skill_files)} assets")
    return sorted(loaded, key=lambda skill: skill.name)
