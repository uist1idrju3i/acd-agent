"""Repository path validation tests."""
# pyright: reportMissingTypeStubs=false,reportPrivateUsage=false

from pathlib import Path

import pytest

from acd.core.silkscreen import SilkscreenLane, SilkTextView
from acd.pipeline.repository import repository_root, resolve_repository_file
from acd.pipeline.silkscreen_resolve import _assert_no_unresolved_texts


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
    assert resolve_repository_file("assets/qr-repository-silkscreen.svg") == (
        root / "assets/qr-repository-silkscreen.svg"
    )


def _text(x_mm: float | None, y_mm: float | None) -> SilkTextView:
    return SilkTextView(
        "silk.text",
        "label",
        "LABEL",
        x_mm,
        y_mm,
        "F.SilkS",
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "",
        0.25,
        1.0,
    )


def test_unresolved_texts_cannot_be_accepted() -> None:
    lane = SilkscreenLane("board", (_text(None, 1.0),), ())
    with pytest.raises(ValueError, match="unresolved text coordinates"):
        _assert_no_unresolved_texts(lane)
    _assert_no_unresolved_texts(
        SilkscreenLane("board", (_text(1.0, 1.0),), ())
    )
