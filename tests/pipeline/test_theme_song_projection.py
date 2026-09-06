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


def test_projection_writes_midi_and_record(tmp_path: Path) -> None:
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
    assert reloaded.source == "deterministic"
    assert reloaded.proposal_input is None
    midi = out_dir / "theme-song" / "theme-song.mid"
    assert midi.read_bytes().startswith(b"MThd")
    assert [artifact.path for artifact in reloaded.artifacts] == ["theme-song/theme-song.mid"]
    assert sorted(path.name for path in (out_dir / "theme-song").iterdir()) == [
        "theme-song.mid",
        "theme-song.provenance.json",
    ]
    assert not (out_dir / ".theme-song-recheck").exists()


def _design_with_proposal(tmp_path: Path, mutate: dict[str, object] | None = None) -> Path:
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    graph_path = design_dir / "graph.json"
    shutil.copyfile(GRAPH_PATH, graph_path)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    notes = [
        {"bar": bar, "step": step, "length": 3, "pitch": pitch, "velocity": 100}
        for bar in range(4)
        for step, pitch in ((0, "d4"), (4, "f4"), (8, "a4"), (12, "d5"))
    ]
    proposal: dict[str, object] = {
        "artifact_kind": "theme_song_proposal",
        "schema_version": "0.1",
        "pass_evidence": False,
        "graph_id": graph["graph_id"],
        "target_revision": graph["revision"],
        "title": "Golden Design Fanfare",
        "rationale": "Minor arpeggio for a compact controller board.",
        "bpm": 108,
        "bars": 4,
        "key": "d minor",
        "tracks": [{"name": "Lead", "channel": 0, "program": 81, "notes": notes}],
        "drums": [{"bar": bar, "step": 0, "sound": "bd"} for bar in range(4)],
    }
    proposal.update(mutate or {})
    (design_dir / "theme-song.json").write_text(json.dumps(proposal), encoding="utf-8")
    return graph_path


def test_projection_renders_adopted_agent_proposal(tmp_path: Path) -> None:
    graph_path = _design_with_proposal(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _, projection = generate_theme_song_projection(
        project_name="golden",
        repository=repository_root(),
        graph_path=graph_path,
        out_dir=out_dir,
        source_revision=_graph_revision(),
    )
    assert projection.source == "agent_proposal"
    assert projection.composer_id == "acd-theme-song-proposal-v1"
    assert projection.title == "Golden Design Fanfare"
    assert projection.bpm == 108
    assert projection.proposal_input is not None
    assert projection.proposal_input.path == "theme-song.json"
    assert projection.pass_evidence is False
    assert (out_dir / "theme-song" / "theme-song.mid").read_bytes().startswith(b"MThd")


def test_projection_rejects_invalid_adopted_proposal(tmp_path: Path) -> None:
    graph_path = _design_with_proposal(tmp_path, {"bpm": 300, "pass_evidence": True})
    with pytest.raises(ThemeSongProjectionError, match="proposal rejected") as info:
        generate_theme_song_projection(
            project_name="golden",
            repository=repository_root(),
            graph_path=graph_path,
            out_dir=tmp_path / "out",
            source_revision=_graph_revision(),
        )
    assert "bpm" in str(info.value)
    assert "pass_evidence" in str(info.value)
    assert not (tmp_path / "out" / THEME_SONG_PROJECTION_NAME).exists()


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
