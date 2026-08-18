"""Repository path validation tests."""
# pyright: reportMissingTypeStubs=false

from pathlib import Path

from acd.pipeline.repository import repository_root


def test_pipeline_paths_resolve_to_repository_root() -> None:
    root = repository_root()
    assert Path(__file__).resolve().parents[2] == root
    assert (root / "AGENTS.md").is_file()
    assert (root / "pyproject.toml").is_file()
    assert (root / "fixtures" / "golden-design-1").is_dir()
    assert (
        root / "plugins/acd/skills/acd-placement-search/scripts/placement_search.py"
    ).is_file()
    assert (
        root / "plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py"
    ).is_file()
    assert (root / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json").is_file()
