"""Repository path validation tests."""
# pyright: reportMissingTypeStubs=false,reportPrivateUsage=false

from pathlib import Path

import pytest

from acd.core.silkscreen import SilkscreenLane, SilkTextView
from acd.pipeline.repository import repository_root, resolve_repository_file
from acd.pipeline.silkscreen_resolve import _assert_no_unresolved_texts


def test_pipeline_paths_resolve_to_repository_root() -> None:
    repository_root.cache_clear()
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


def test_repository_root_uses_explicit_environment_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit_root = tmp_path / "repository"
    explicit_root.mkdir()
    (explicit_root / "AGENTS.md").write_text("", encoding="utf-8")
    (explicit_root / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("ACD_REPOSITORY_ROOT", str(explicit_root))
    repository_root.cache_clear()
    try:
        assert repository_root() == explicit_root
    finally:
        repository_root.cache_clear()


def test_repository_root_rejects_explicit_root_without_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit_root = tmp_path / "repository"
    explicit_root.mkdir()
    (explicit_root / "AGENTS.md").write_text("", encoding="utf-8")
    monkeypatch.setenv("ACD_REPOSITORY_ROOT", str(explicit_root))
    repository_root.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="repository root validation failed"):
            repository_root()
    finally:
        repository_root.cache_clear()


def test_repository_root_keeps_default_when_environment_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACD_REPOSITORY_ROOT", raising=False)
    repository_root.cache_clear()
    try:
        assert repository_root() == Path(__file__).resolve().parents[2]
    finally:
        repository_root.cache_clear()


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
