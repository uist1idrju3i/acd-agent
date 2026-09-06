from __future__ import annotations

import copy
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

import compose_theme_song
import theme_song

REPO_ROOT = Path(__file__).resolve().parents[5]
GOLDEN_GRAPH = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"
SCRIPTS = Path(theme_song.__file__).resolve().parent


def _graph(graph_id: str = "demo", requirements: int = 3) -> dict[str, object]:
    nodes: list[dict[str, object]] = [
        {"id": f"req-{index}", "kind": "requirement"} for index in range(requirements)
    ]
    nodes.extend({"id": f"c{index}", "kind": "electrical.component"} for index in range(5))
    nodes.extend({"id": f"n{index}", "kind": "electrical.net"} for index in range(4))
    nodes.append({"id": "fw-idle", "kind": "firmware.state"})
    return {"graph_id": graph_id, "revision": "r1", "nodes": nodes}


def _write_graph(tmp_path: Path, payload: object, name: str = "graph.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _compose(
    tmp_path: Path, payload: object, salt: str = "", name: str = "graph.json"
) -> theme_song.Score:
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, payload, name))
    return theme_song.compose(summary, salt=salt)


def _proposal(graph_id: str = "demo") -> dict[str, object]:
    notes = [
        {"bar": bar, "step": step, "length": 2, "pitch": pitch, "velocity": 90}
        for bar in range(4)
        for step, pitch in ((0, "c5"), (4, "e5"), (8, "g5"), (12, "c6"))
    ]
    return {
        "artifact_kind": "theme_song_proposal",
        "schema_version": "0.1",
        "pass_evidence": False,
        "graph_id": graph_id,
        "target_revision": "r1",
        "title": "Demo jingle",
        "rationale": "Bright arpeggio for a compact USB product.",
        "bpm": 120,
        "bars": 4,
        "key": "c major",
        "tracks": [{"name": "Lead", "channel": 0, "program": 80, "notes": notes}],
        "drums": [{"bar": bar, "step": step, "sound": "bd"} for bar in range(4) for step in (0, 8)],
    }


def test_same_graph_and_salt_is_byte_identical(tmp_path: Path) -> None:
    first = _compose(tmp_path, _graph(), name="a.json")
    second = _compose(tmp_path, _graph(), name="b.json")
    assert theme_song.render_midi(first) == theme_song.render_midi(second)


def test_salt_or_graph_change_alters_the_song(tmp_path: Path) -> None:
    base = _compose(tmp_path, _graph(), name="a.json")
    salted = _compose(tmp_path, _graph(), salt="v2", name="b.json")
    changed = _compose(tmp_path, _graph(requirements=6), name="c.json")
    assert base.seed != salted.seed
    assert theme_song.render_midi(base) != theme_song.render_midi(salted)
    assert theme_song.render_midi(base) != theme_song.render_midi(changed)


def test_midi_is_format_1_with_paired_note_events(tmp_path: Path) -> None:
    payload = theme_song.render_midi(_compose(tmp_path, _graph()))
    assert payload[:4] == b"MThd"
    length, fmt, tracks, division = struct.unpack(">IHHH", payload[4:14])
    assert (length, fmt, division) == (6, 1, theme_song.TICKS_PER_BEAT)
    assert tracks == 5
    ons, offs = theme_song.parse_midi_note_pairs(payload)
    assert ons > 0
    assert ons == offs


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        [],
        {"revision": "r1", "nodes": [{"id": "a", "kind": "requirement"}]},
        {"graph_id": "g", "nodes": [{"id": "a", "kind": "requirement"}]},
        {"graph_id": "g", "revision": "r1"},
        {"graph_id": "g", "revision": "r1", "nodes": []},
        {"graph_id": "g", "revision": "r1", "nodes": [{"id": "a"}]},
        {"graph_id": "g", "revision": "r1", "nodes": ["a"]},
    ],
)
def test_malformed_graph_fails_closed(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "graph.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(theme_song.ThemeSongError):
        theme_song.load_graph_summary(path)


def test_missing_graph_and_bad_bars_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(theme_song.ThemeSongError):
        theme_song.load_graph_summary(tmp_path / "missing.json")
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, _graph()))
    for bars in (0, 3, 6, 68):
        with pytest.raises(theme_song.ThemeSongError):
            theme_song.compose(summary, bars=bars)


@pytest.mark.parametrize(
    ("pitch", "expected"),
    [("c4", 60), ("C4", 60), ("f#5", 78), ("bb3", 58), (0, 0), (127, 127)],
)
def test_parse_pitch_accepts_names_and_numbers(pitch: object, expected: int) -> None:
    assert theme_song.parse_pitch(pitch) == expected


@pytest.mark.parametrize("pitch", ["h4", "c", 128, -1, True, 4.5, None])
def test_parse_pitch_rejects_invalid(pitch: object) -> None:
    with pytest.raises(theme_song.ThemeSongError):
        theme_song.parse_pitch(pitch)


def test_valid_proposal_renders_midi(tmp_path: Path) -> None:
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, _graph()))
    score = theme_song.load_proposal(_proposal(), summary)
    assert score.bpm == 120
    assert score.note_count == 16
    midi, ons = theme_song.render_checked_midi(score)
    assert ons == 16 + len(score.drums)
    assert struct.unpack(">IHHH", midi[4:14])[2] == 3


def test_proposal_round_trip_through_score_to_proposal(tmp_path: Path) -> None:
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, _graph()))
    seeded = theme_song.compose(summary)
    document = theme_song.score_to_proposal(seeded, rationale="seed")
    reloaded = theme_song.load_proposal(document, summary)
    assert theme_song.render_midi(reloaded) == theme_song.render_midi(
        theme_song.load_proposal(json.loads(json.dumps(document)), summary)
    )
    assert reloaded.bpm == seeded.bpm
    assert reloaded.note_count == seeded.note_count


def _mutate(document: dict[str, object], path: tuple[object, ...], value: object) -> object:
    mutated = copy.deepcopy(document)
    cursor: object = mutated
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    if value is ...:
        del cursor[path[-1]]  # type: ignore[union-attr]
    else:
        cursor[path[-1]] = value  # type: ignore[index]
    return mutated


@pytest.mark.parametrize(
    ("path", "value", "fragment"),
    [
        (("artifact_kind",), "song", "artifact_kind"),
        (("pass_evidence",), True, "pass_evidence"),
        (("graph_id",), "other", "graph_id"),
        (("target_revision",), "r2", "target_revision"),
        (("title",), "", "title"),
        (("rationale",), ..., "rationale"),
        (("bpm",), 200, "bpm"),
        (("bpm",), "120", "bpm"),
        (("bars",), 6, "multiple of 4"),
        (("tracks",), [], "tracks"),
        (("tracks", 0, "channel"), 9, "reserved for drums"),
        (("tracks", 0, "name"), "Lead/../x", "name"),
        (("tracks", 0, "notes", 0, "pitch"), "x9", "pitch"),
        (("tracks", 0, "notes", 0, "velocity"), 0, "velocity"),
        (("tracks", 0, "notes", 0, "bar"), 4, "bar"),
        (("tracks", 0, "notes", 0, "step"), 16, "step"),
        (("tracks", 0, "notes", 15, "length"), 40, "ends after the last bar"),
        (("drums", 0, "sound"), "kalimba", "sound"),
        (("drums", 0, "bar"), -1, "bar"),
    ],
)
def test_proposal_rejects_bad_fields(
    tmp_path: Path, path: tuple[object, ...], value: object, fragment: str
) -> None:
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, _graph()))
    document = _mutate(_proposal(), path, value)
    with pytest.raises(theme_song.ThemeSongError, match="proposal rejected") as info:
        theme_song.load_proposal(document, summary)  # type: ignore[arg-type]
    assert fragment in str(info.value)


def test_proposal_reports_every_reason_and_needs_enough_notes(tmp_path: Path) -> None:
    summary = theme_song.load_graph_summary(_write_graph(tmp_path, _graph()))
    document = _proposal()
    document["bpm"] = 10
    document["bars"] = 5
    with pytest.raises(theme_song.ThemeSongError) as info:
        theme_song.load_proposal(document, summary)
    assert "bpm" in str(info.value)
    assert "multiple of 4" in str(info.value)
    sparse = _proposal()
    sparse["tracks"] = [{"name": "Lead", "channel": 0, "program": 80, "notes": []}]
    with pytest.raises(theme_song.ThemeSongError, match="at least"):
        theme_song.load_proposal(sparse, summary)
    duplicated = _proposal()
    tracks = cast(list[dict[str, object]], duplicated["tracks"])
    tracks.append(copy.deepcopy(tracks[0]))
    with pytest.raises(theme_song.ThemeSongError, match=r"duplicated|used twice"):
        theme_song.load_proposal(duplicated, summary)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "compose_theme_song.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_compose_cli_writes_artifacts_and_provenance(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    proposal_out = out_dir / "theme-song.proposal.json"
    result = _run_cli(
        "--graph",
        str(GOLDEN_GRAPH),
        "--out-dir",
        str(out_dir),
        "--base-dir",
        str(tmp_path),
        "--proposal-out",
        str(proposal_out),
    )
    assert result.returncode == 0, result.stderr
    provenance = json.loads((out_dir / "theme-song.provenance.json").read_text(encoding="utf-8"))
    assert provenance["pass_evidence"] is False
    assert provenance["source"] == "deterministic"
    assert provenance["composer_id"] == theme_song.COMPOSER_ID
    assert provenance["target_revision"] == "r1"
    assert provenance["license"] == "BSD-3-Clause"
    assert [entry["path"] for entry in provenance["inputs"]] == [GOLDEN_GRAPH.resolve().as_posix()]
    midi = (out_dir / "theme-song.mid").read_bytes()
    assert list(provenance["artifacts"]) == ["midi"]
    assert provenance["artifacts"]["midi"]["content_hash"] == theme_song.sha256_bytes(midi)
    assert provenance["generator"]["content_hash"] == theme_song.sha256_bytes(
        (SCRIPTS / "compose_theme_song.py").read_bytes()
    )
    seed_proposal = json.loads(proposal_out.read_text(encoding="utf-8"))
    assert seed_proposal["artifact_kind"] == "theme_song_proposal"
    assert seed_proposal["pass_evidence"] is False
    assert seed_proposal["graph_id"] == provenance["graph_id"]


def test_compose_cli_renders_accepted_proposal_and_rejects_invalid(tmp_path: Path) -> None:
    graph = _write_graph(tmp_path, _graph())
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps(_proposal()), encoding="utf-8")
    out_dir = tmp_path / "ok"
    result = _run_cli(
        "--graph",
        str(graph),
        "--out-dir",
        str(out_dir),
        "--proposal",
        str(proposal),
        "--base-dir",
        str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    provenance = json.loads((out_dir / "theme-song.provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"] == "agent_proposal"
    assert provenance["composer_id"] == theme_song.PROPOSAL_COMPOSER_ID
    assert provenance["inputs"][1] == {
        "path": "proposal.json",
        "content_hash": theme_song.sha256_file(proposal),
    }
    assert provenance["composition"]["title"] == "Demo jingle"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_proposal(graph_id="other")), encoding="utf-8")
    result = _run_cli(
        "--graph", str(graph), "--out-dir", str(tmp_path / "ng"), "--proposal", str(bad)
    )
    assert result.returncode == 1
    assert "fail-closed: proposal rejected" in result.stderr
    assert not (tmp_path / "ng").exists()


def test_compose_cli_fails_closed_on_missing_graph(tmp_path: Path) -> None:
    result = _run_cli("--graph", str(tmp_path / "missing.json"), "--out-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert "fail-closed" in result.stderr
    assert not (tmp_path / "out").exists()


def test_compose_theme_song_function_rejects_bad_bars(tmp_path: Path) -> None:
    with pytest.raises(theme_song.ThemeSongError):
        compose_theme_song.compose_theme_song(
            _write_graph(tmp_path, _graph()), tmp_path / "out", salt="", bars=5, base_dir=tmp_path
        )
