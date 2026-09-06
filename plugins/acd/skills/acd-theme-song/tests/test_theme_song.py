from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import compose_theme_song
import theme_song
import validate_theme_song_proposal

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


def test_same_graph_and_salt_is_byte_identical(tmp_path: Path) -> None:
    first = _compose(tmp_path, _graph(), name="a.json")
    second = _compose(tmp_path, _graph(), name="b.json")
    assert theme_song.render_strudel(first) == theme_song.render_strudel(second)
    assert theme_song.render_midi(first) == theme_song.render_midi(second)


def test_salt_or_graph_change_alters_the_song(tmp_path: Path) -> None:
    base = _compose(tmp_path, _graph(), name="a.json")
    salted = _compose(tmp_path, _graph(), salt="v2", name="b.json")
    changed = _compose(tmp_path, _graph(requirements=6), name="c.json")
    assert base.seed != salted.seed
    assert theme_song.render_midi(base) != theme_song.render_midi(salted)
    assert theme_song.render_midi(base) != theme_song.render_midi(changed)


def test_generated_strudel_passes_validator_and_uses_allowed_surface(tmp_path: Path) -> None:
    source = theme_song.render_strudel(_compose(tmp_path, _graph()))
    assert theme_song.validate_strudel(source) == []
    assert "setcps(" in source
    assert "// Paste into https://strudel.cc to play. Strudel itself is not bundled here." in source
    for name in theme_song.IDENTIFIER_CALL_RE.findall(theme_song.strip_comments(source)):
        assert name in theme_song.ALLOWED_FUNCTIONS


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
    ("source", "fragment"),
    [
        ("", "empty"),
        ('setcps(0.5)\nnote("c3").s("sine")\nfetch("http://x")', "forbidden token 'fetch'"),
        ('setcps(0.5)\nnote("c3").s("sine"); eval("1")', "forbidden token 'eval'"),
        ('setcps(0.5)\nnote("c3").s("sine").superpower()', "'superpower'"),
        ('note("c3").s("sine")', "setcps"),
        ('setcps(5)\nnote("c3").s("sine")', "bpm"),
        ('setcps(0.5)\nnote("c3").s("kalimba")', "sound 'kalimba'"),
        ('setcps(0.5)\nnote("c3 {e3}").s("sine")', "unsupported characters"),
        ('setcps(0.5)\nnote("c3").s("sine"', "unclosed"),
        ("setcps(0.5)\ngain(0.5)", "no note/n/s"),
    ],
)
def test_validator_rejects_bad_proposals(source: str, fragment: str) -> None:
    problems = theme_song.validate_strudel(source)
    assert problems
    assert any(fragment in problem for problem in problems), problems


def test_validator_accepts_minimal_pattern() -> None:
    assert theme_song.validate_strudel('setcps(0.5)\nnote("<c3 e3 g3>").s("triangle")') == []


def test_compose_cli_writes_artifacts_and_provenance(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "compose_theme_song.py"),
            "--graph",
            str(GOLDEN_GRAPH),
            "--out-dir",
            str(out_dir),
            "--base-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    provenance = json.loads((out_dir / "theme-song.provenance.json").read_text(encoding="utf-8"))
    assert provenance["pass_evidence"] is False
    assert provenance["source"] == "deterministic"
    assert provenance["target_revision"] == "r1"
    assert provenance["license"] == "BSD-3-Clause"
    strudel = (out_dir / "theme-song.strudel.js").read_bytes()
    midi = (out_dir / "theme-song.mid").read_bytes()
    assert provenance["artifacts"]["strudel"]["content_hash"] == theme_song.sha256_bytes(strudel)
    assert provenance["artifacts"]["midi"]["content_hash"] == theme_song.sha256_bytes(midi)
    assert provenance["generator"]["content_hash"] == theme_song.sha256_bytes(
        (SCRIPTS / "compose_theme_song.py").read_bytes()
    )


def test_compose_cli_fails_closed_on_missing_graph(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "compose_theme_song.py"),
            "--graph",
            str(tmp_path / "missing.json"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "fail-closed" in result.stderr
    assert not (tmp_path / "out").exists()


def test_proposal_path_accepts_valid_and_rejects_invalid(tmp_path: Path) -> None:
    graph = _write_graph(tmp_path, _graph())
    good = tmp_path / "good.js"
    good.write_text('setcps(0.5)\nnote("<c3 e3 g3>").s("triangle")\n', encoding="utf-8")
    provenance_path = validate_theme_song_proposal.accept_proposal(
        graph, good, tmp_path / "ok", base_dir=tmp_path
    )
    record = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert record["source"] == "agent_proposal"
    assert record["pass_evidence"] is False

    bad = tmp_path / "bad.js"
    bad.write_text('setcps(0.5)\nnote("c3").s("sine")\nimport x from "y"', encoding="utf-8")
    with pytest.raises(theme_song.ThemeSongError, match="proposal rejected"):
        validate_theme_song_proposal.accept_proposal(graph, bad, tmp_path / "ng", base_dir=tmp_path)
    assert not (tmp_path / "ng").exists()


def test_compose_theme_song_function_rejects_bad_bars(tmp_path: Path) -> None:
    with pytest.raises(theme_song.ThemeSongError):
        compose_theme_song.compose_theme_song(
            _write_graph(tmp_path, _graph()), tmp_path / "out", salt="", bars=5, base_dir=tmp_path
        )
