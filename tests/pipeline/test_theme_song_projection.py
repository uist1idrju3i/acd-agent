"""Theme-song projection stage tests (subprocess Skill invocation + record)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from acd.pipeline.repository import repository_root
from acd.pipeline.theme_song import (
    THEME_SONG_PROJECTION_NAME,
    ThemeSongProjectionError,
    generate_theme_song_projection,
    theme_song_script_path,
)
from acd.schema.theme_song import ThemeSongProjection

GRAPH_PATH = Path("fixtures/golden-design-1/graph.json")


def _graph_revision() -> str:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    return str(graph["revision"])


def test_projection_writes_midi_strudel_and_record(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    projection_path, projection = generate_theme_song_projection(
        project_name="golden",
        repository=repository_root(),
        graph_path=GRAPH_PATH.resolve(),
        out_dir=out_dir,
        source_revision=_graph_revision(),
    )
    assert projection_path == out_dir / THEME_SONG_PROJECTION_NAME
    reloaded = ThemeSongProjection.model_validate_json(projection_path.read_text(encoding="utf-8"))
    assert reloaded == projection
    assert reloaded.pass_evidence is False
    assert reloaded.record_class == "L3"
    assert reloaded.regeneration_check.status == "reproduced"
    midi = out_dir / "theme-song" / "theme-song.mid"
    strudel = out_dir / "theme-song" / "theme-song.strudel.js"
    assert midi.read_bytes().startswith(b"MThd")
    assert "setcps(" in strudel.read_text(encoding="utf-8")
    assert {artifact.path for artifact in reloaded.artifacts} == {
        "theme-song/theme-song.mid",
        "theme-song/theme-song.strudel.js",
    }
    assert not (out_dir / ".theme-song-recheck").exists()


def test_projection_is_deterministic_across_runs(tmp_path: Path) -> None:
    hashes: list[str] = []
    for name in ("a", "b"):
        out_dir = tmp_path / name
        out_dir.mkdir()
        _, projection = generate_theme_song_projection(
            project_name="golden",
            repository=repository_root(),
            graph_path=GRAPH_PATH.resolve(),
            out_dir=out_dir,
            source_revision=_graph_revision(),
        )
        hashes.append(projection.canonical_hash)
    assert hashes[0] == hashes[1]


def test_projection_rejects_revision_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ThemeSongProjectionError, match="revision"):
        generate_theme_song_projection(
            project_name="golden",
            repository=repository_root(),
            graph_path=GRAPH_PATH.resolve(),
            out_dir=tmp_path,
            source_revision="r999",
        )


def test_projection_fails_closed_on_malformed_graph(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text('{"graph_id": "x", "revision": "r1", "nodes": []}', encoding="utf-8")
    with pytest.raises(ThemeSongProjectionError, match="fail-closed"):
        generate_theme_song_projection(
            project_name="golden",
            repository=repository_root(),
            graph_path=graph_path,
            out_dir=tmp_path / "out",
            source_revision="r1",
        )
    assert not (tmp_path / "out" / THEME_SONG_PROJECTION_NAME).exists()


def test_projection_fails_closed_when_skill_is_missing(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    assert not theme_song_script_path(fake_repo).exists()
    with pytest.raises(ThemeSongProjectionError, match="missing"):
        generate_theme_song_projection(
            project_name="golden",
            repository=fake_repo,
            graph_path=GRAPH_PATH.resolve(),
            out_dir=tmp_path / "out",
            source_revision=_graph_revision(),
        )


def test_schema_rejects_unreproduced_projection(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    projection_path, _ = generate_theme_song_projection(
        project_name="golden",
        repository=repository_root(),
        graph_path=GRAPH_PATH.resolve(),
        out_dir=out_dir,
        source_revision=_graph_revision(),
    )
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    payload["regeneration_check"] = {
        "status": "not_reproduced",
        "first_hash": payload["regeneration_check"]["first_hash"],
        "second_hash": "sha256:" + "0" * 64,
    }
    payload["canonical_hash"] = "unknown"
    with pytest.raises(ValueError, match="reproduced"):
        ThemeSongProjection.model_validate(payload)
    payload["pass_evidence"] = True
    with pytest.raises(ValueError):
        ThemeSongProjection.model_validate(payload)
    shutil.rmtree(out_dir)
