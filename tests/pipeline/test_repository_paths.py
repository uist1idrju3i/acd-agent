"""Repository path validation tests."""
# pyright: reportMissingTypeStubs=false

from pathlib import Path

from acd.pipeline.gd1_fixture.components import FIXTURE_DIR
from acd.pipeline.gd1_fixture.graph import FAB_PROFILE, PLACEMENT_SKILL, SILK_SKILL
from acd.pipeline.repository import REPO_ROOT


def test_pipeline_paths_resolve_to_repository_root() -> None:
    assert Path(__file__).resolve().parents[2] == REPO_ROOT
    assert (REPO_ROOT / "AGENTS.md").is_file()
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert FIXTURE_DIR.is_dir()
    assert PLACEMENT_SKILL.is_file()
    assert SILK_SKILL.is_file()
    assert FAB_PROFILE.is_file()
