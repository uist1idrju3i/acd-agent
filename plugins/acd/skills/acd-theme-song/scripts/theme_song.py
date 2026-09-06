#!/usr/bin/env python3
"""Deterministic theme-song composition for a design graph.

A theme song is an L3 artifact: it presents the design (its identifier,
revision and structure) as music, carries no approval authority and never
flows back into design inputs. The composer uses only the Python standard
library and does not import ``acd`` or any music library, so the artifact can
be regenerated anywhere the plugin is installed.

Two artifacts are written from one score:

* a Strudel pattern (``.strudel.js``) that can be pasted into
  https://strudel.cc for playback. Only the pattern *text* is produced; the
  Strudel engine itself (AGPL-3.0) is never imported, bundled or executed.
* a Standard MIDI File (``.mid``, format 1) for DAWs and firmware tooling.

Every musical decision derives from ``sha256(canonical graph JSON + salt)``,
so the same design revision always yields byte-identical artifacts and any
change to the design changes the song.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

SCHEMA_VERSION = "0.1"
ARTIFACT_KIND = "theme_song"
COMPOSER_ID = "acd-theme-song-composer-v1"
STEPS_PER_BAR = 16
TICKS_PER_BEAT = 480
MIN_BPM = 92
MAX_BPM = 140
MIN_BARS = 4
MAX_BARS = 64

# Strudel surface used by the composer and accepted from agent proposals.
# Names come from the public Strudel reference (https://strudel.cc/learn/);
# nothing here is Strudel source code.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "setcps",
        "stack",
        "cat",
        "seq",
        "note",
        "n",
        "s",
        "sound",
        "gain",
        "velocity",
        "lpf",
        "hpf",
        "cutoff",
        "resonance",
        "room",
        "size",
        "delay",
        "delaytime",
        "delayfeedback",
        "pan",
        "attack",
        "decay",
        "sustain",
        "release",
        "slow",
        "fast",
        "struct",
        "euclid",
        "rev",
        "late",
        "early",
        "clip",
        "legato",
        "shape",
        "vowel",
        "detune",
    }
)
ALLOWED_SOUNDS: frozenset[str] = frozenset(
    {
        "sine",
        "square",
        "sawtooth",
        "triangle",
        "bd",
        "sd",
        "hh",
        "oh",
        "cp",
        "rim",
        "lt",
        "mt",
        "ht",
        "rd",
        "cr",
    }
)
FORBIDDEN_TOKENS: tuple[str, ...] = (
    "import",
    "require",
    "fetch",
    "eval",
    "Function",
    "samples",
    "window",
    "document",
    "globalThis",
    "process",
    "XMLHttpRequest",
    "WebSocket",
    "${",
)
_MINI_NOTATION_RE = re.compile(r"^[A-Za-z0-9#~\[\]<>*/,.!@:\s_-]*$")
IDENTIFIER_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_STRING_RE = re.compile(r'"([^"\\]*)"|\'([^\'\\]*)\'|`([^`\\]*)`')
_NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
_MAJOR = (0, 2, 4, 5, 7, 9, 11)
_MINOR = (0, 2, 3, 5, 7, 8, 10)
_MAJOR_PROGRESSIONS = ((0, 4, 5, 3), (0, 5, 3, 4), (5, 3, 0, 4), (0, 3, 4, 4))
_MINOR_PROGRESSIONS = ((0, 5, 2, 6), (0, 3, 4, 0), (0, 6, 5, 4), (0, 2, 6, 4))


class ThemeSongError(ValueError):
    """Raised when a theme song cannot be composed or a proposal is rejected."""


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ThemeSongError(f"cannot read input {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Graph input (structural checks only; the Pydantic contract lives in ``acd``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphSummary:
    graph_id: str
    revision: str
    content_hash: str
    canonical_hash: str
    node_kinds: dict[str, int]
    requirement_count: int
    component_count: int
    net_count: int
    firmware_state_count: int


def load_graph_summary(path: Path) -> GraphSummary:
    """Read the design graph as JSON and summarise the structure the song uses."""
    content_hash = sha256_file(path)
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThemeSongError(f"design graph {path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ThemeSongError(f"design graph {path} must be a JSON object")
    document = cast(dict[str, object], loaded)
    graph_id = document.get("graph_id")
    revision = document.get("revision")
    nodes = document.get("nodes")
    if not isinstance(graph_id, str) or not graph_id:
        raise ThemeSongError(f"design graph {path}: graph_id is missing or not text")
    if not isinstance(revision, str) or not revision:
        raise ThemeSongError(f"design graph {path}: revision is missing or not text")
    if not isinstance(nodes, list) or not nodes:
        raise ThemeSongError(f"design graph {path}: nodes is missing or empty")
    kinds: dict[str, int] = {}
    for index, raw_node in enumerate(cast(list[object], nodes)):
        if not isinstance(raw_node, dict):
            raise ThemeSongError(f"design graph {path}: nodes[{index}] is not an object")
        node = cast(dict[str, object], raw_node)
        kind = node.get("kind")
        node_id = node.get("id")
        if not isinstance(kind, str) or not kind:
            raise ThemeSongError(f"design graph {path}: nodes[{index}].kind is missing")
        if not isinstance(node_id, str) or not node_id:
            raise ThemeSongError(f"design graph {path}: nodes[{index}].id is missing")
        kinds[kind] = kinds.get(kind, 0) + 1
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return GraphSummary(
        graph_id=graph_id,
        revision=revision,
        content_hash=content_hash,
        canonical_hash=sha256_bytes(canonical.encode("utf-8")),
        node_kinds=dict(sorted(kinds.items())),
        requirement_count=kinds.get("requirement", 0),
        component_count=kinds.get("electrical.component", 0),
        net_count=kinds.get("electrical.net", 0),
        firmware_state_count=kinds.get("firmware.state", 0),
    )


def derive_seed(summary: GraphSummary, salt: str) -> str:
    digest = hashlib.sha256()
    digest.update(summary.canonical_hash.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(salt.encode("utf-8"))
    return "sha256:" + digest.hexdigest()


# ---------------------------------------------------------------------------
# Score model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteEvent:
    step: int
    length: int
    pitch: int
    velocity: int


@dataclass(frozen=True)
class DrumEvent:
    step: int
    sound: str


@dataclass
class Score:
    graph_id: str
    revision: str
    seed: str
    bpm: int
    bars: int
    key_root: int
    minor: bool
    progression: tuple[int, ...]
    melody: list[NoteEvent] = field(default_factory=list[NoteEvent])
    bass: list[NoteEvent] = field(default_factory=list[NoteEvent])
    chords: list[NoteEvent] = field(default_factory=list[NoteEvent])
    drums: list[DrumEvent] = field(default_factory=list[DrumEvent])

    @property
    def total_steps(self) -> int:
        return self.bars * STEPS_PER_BAR

    @property
    def scale(self) -> tuple[int, ...]:
        return _MINOR if self.minor else _MAJOR

    @property
    def key_name(self) -> str:
        return f"{_NOTE_NAMES[self.key_root % 12]} {'minor' if self.minor else 'major'}"


def euclid(pulses: int, steps: int, rotation: int = 0) -> tuple[int, ...]:
    """Bjorklund-style even distribution of ``pulses`` over ``steps``."""
    if steps <= 0 or pulses < 0 or pulses > steps:
        raise ThemeSongError(f"invalid euclidean rhythm ({pulses},{steps})")
    pattern = tuple(1 if (index * pulses) % steps < pulses else 0 for index in range(steps))
    rotation %= steps
    return pattern[rotation:] + pattern[:rotation]


def _degree_to_pitch(root: int, scale: tuple[int, ...], degree: int, octave: int) -> int:
    octave_shift, index = divmod(degree, len(scale))
    return root + 12 * (octave + octave_shift) + scale[index]


def _motif_from_text(text: str, length: int) -> tuple[int, ...]:
    """Map identifier characters to scale degrees so the design name is 'sung'."""
    degrees: list[int] = []
    for char in text.lower():
        if char.isalnum():
            degrees.append((ord(char) * 7) % 8)
        if len(degrees) == length:
            break
    while len(degrees) < length:
        degrees.append(0)
    return tuple(degrees)


def compose(summary: GraphSummary, *, salt: str = "", bars: int = 16) -> Score:
    """Compose a deterministic score from the graph summary."""
    if not MIN_BARS <= bars <= MAX_BARS or bars % 4 != 0:
        raise ThemeSongError(f"bars must be a multiple of 4 within {MIN_BARS}..{MAX_BARS}")
    seed = derive_seed(summary, salt)
    rng = random.Random(int(seed.removeprefix("sha256:"), 16))
    minor = summary.requirement_count % 2 == 1
    key_root = rng.randrange(12)
    bpm = MIN_BPM + (summary.component_count * 3 + rng.randrange(12)) % (MAX_BPM - MIN_BPM + 1)
    progression = rng.choice(_MINOR_PROGRESSIONS if minor else _MAJOR_PROGRESSIONS)
    score = Score(
        graph_id=summary.graph_id,
        revision=summary.revision,
        seed=seed,
        bpm=bpm,
        bars=bars,
        key_root=key_root,
        minor=minor,
        progression=progression,
    )
    scale = score.scale
    motif = _motif_from_text(summary.graph_id, 8)
    melody_rhythm = euclid(3 + summary.net_count % 3 + 2, 8, rng.randrange(8))
    bass_rhythm = euclid(4 + summary.firmware_state_count % 3, STEPS_PER_BAR, 0)
    kick = euclid(4, STEPS_PER_BAR, 0)
    snare = tuple(1 if index in (4, 12) else 0 for index in range(STEPS_PER_BAR))
    hat = euclid(6 + rng.randrange(3), STEPS_PER_BAR, rng.randrange(2))

    for bar in range(bars):
        section = (bar // 4) % 4
        chord_degree = progression[bar % len(progression)]
        bar_start = bar * STEPS_PER_BAR
        chord_root = _degree_to_pitch(key_root, scale, chord_degree, 3)
        triad = (
            chord_root,
            _degree_to_pitch(key_root, scale, chord_degree + 2, 3),
            _degree_to_pitch(key_root, scale, chord_degree + 4, 3),
        )
        if section != 0 or bar >= 2:
            for pitch in triad:
                score.chords.append(NoteEvent(bar_start, STEPS_PER_BAR, pitch, 56))
        for step, hit in enumerate(bass_rhythm):
            if hit:
                pitch = chord_root - 12 if step % 8 == 0 else chord_root - 12 + (7 if minor else 12)
                score.bass.append(NoteEvent(bar_start + step, 2, pitch, 84))
        if bar >= 2 and bar < bars - 1:
            transpose = 1 if section == 2 else 0
            for slot, hit in enumerate(melody_rhythm):
                if not hit:
                    continue
                degree = motif[(slot + bar) % len(motif)] + chord_degree % 3 + transpose
                pitch = _degree_to_pitch(key_root, scale, degree, 5)
                length = 2 if slot % 2 == 0 else 1
                score.melody.append(NoteEvent(bar_start + slot * 2, length, pitch, 96))
        if bar == bars - 1:
            score.melody.append(NoteEvent(bar_start, STEPS_PER_BAR, key_root + 60, 100))
        for step in range(STEPS_PER_BAR):
            if kick[step] and bar >= 1:
                score.drums.append(DrumEvent(bar_start + step, "bd"))
            if snare[step] and bar >= 1:
                score.drums.append(DrumEvent(bar_start + step, "sd"))
            if hat[step] and bar >= 1 and section != 3:
                score.drums.append(DrumEvent(bar_start + step, "hh"))
    return score


# ---------------------------------------------------------------------------
# Strudel pattern text
# ---------------------------------------------------------------------------


def pitch_name(pitch: int) -> str:
    octave, index = divmod(pitch, 12)
    return f"{_NOTE_NAMES[index]}{octave - 1}"


def _bar_sequence(events: list[NoteEvent], bar: int) -> str:
    start = bar * STEPS_PER_BAR
    slots: list[str] = []
    step = start
    end = start + STEPS_PER_BAR
    while step < end:
        at_step = [event for event in events if event.step == step]
        if not at_step:
            slots.append("~")
            step += 1
            continue
        length = min(max(event.length for event in at_step), end - step)
        names = sorted({pitch_name(event.pitch) for event in at_step})
        token = ",".join(names) if len(names) == 1 else f"[{','.join(names)}]"
        if length > 1:
            token = f"{token}@{length}"
        slots.append(token)
        step += length
    return "[" + " ".join(slots) + "]"


def _drum_sequence(drums: list[DrumEvent], sound: str, bar: int) -> str:
    start = bar * STEPS_PER_BAR
    steps = {
        event.step - start
        for event in drums
        if event.sound == sound and start <= event.step < start + STEPS_PER_BAR
    }
    if not steps:
        return "~"
    return "[" + " ".join(sound if step in steps else "~" for step in range(STEPS_PER_BAR)) + "]"


def render_strudel(score: Score) -> str:
    cps = score.bpm / 60 / 4
    melody = "\n".join(f"  {_bar_sequence(score.melody, bar)}" for bar in range(score.bars))
    chords = "\n".join(f"  {_bar_sequence(score.chords, bar)}" for bar in range(score.bars))
    bass = "\n".join(f"  {_bar_sequence(score.bass, bar)}" for bar in range(score.bars))
    drum_lines: list[str] = []
    for sound in ("bd", "sd", "hh"):
        bars = " ".join(_drum_sequence(score.drums, sound, bar) for bar in range(score.bars))
        drum_lines.append(f'  s("<{bars}>").gain({0.9 if sound == "bd" else 0.5}),')
    lines = [
        f"// Theme song for design graph {score.graph_id!r} revision {score.revision!r}",
        f"// seed {score.seed}",
        f"// {score.key_name}, {score.bpm} bpm, {score.bars} bars",
        "// Generated by ACD acd-theme-song (composer v1). L3 artifact; not evidence.",
        "// Paste into https://strudel.cc to play. Strudel itself is not bundled here.",
        f"setcps({cps:.6f})",
        "stack(",
        "  note(`<",
        melody,
        '  >`).s("triangle").gain(0.8).room(0.3),',
        "  note(`<",
        chords,
        '  >`).s("sawtooth").lpf(900).gain(0.35).attack(0.05).release(0.2),',
        "  note(`<",
        bass,
        '  >`).s("square").lpf(500).gain(0.6),',
        *drum_lines,
        ")",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strudel proposal validation (L2 steering; rejects, never approves designs)
# ---------------------------------------------------------------------------


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def _balanced(source: str) -> str | None:
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    stack: list[str] = []
    for char in source:
        if char in "([{<":
            stack.append(char)
        elif char in pairs:
            if not stack or stack[-1] != pairs[char]:
                return f"unbalanced {char!r}"
            stack.pop()
    return f"unclosed {stack[-1]!r}" if stack else None


def validate_strudel(source: str) -> list[str]:
    """Return every reason the pattern text is rejected (empty means accepted)."""
    errors: list[str] = []
    if not source.strip():
        return ["pattern is empty"]
    stripped = strip_comments(source)
    for token in FORBIDDEN_TOKENS:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", stripped):
            errors.append(f"forbidden token {token!r}")
    strings = _STRING_RE.findall(stripped)
    code_only = _STRING_RE.sub('""', stripped)
    if (problem := _balanced(code_only)) is not None:
        errors.append(problem)
    calls = sorted(set(IDENTIFIER_CALL_RE.findall(code_only)))
    for name in calls:
        if name not in ALLOWED_FUNCTIONS:
            errors.append(f"function {name!r} is not in the allowed Strudel surface")
    if "setcps" not in calls:
        errors.append("setcps(...) is required so the tempo is explicit")
    for match in re.finditer(r"setcps\(\s*([0-9.]+)\s*\)", code_only):
        cps = float(match.group(1))
        if not (MIN_BPM / 240) <= cps <= (MAX_BPM / 240):
            errors.append(f"setcps({cps}) is outside {MIN_BPM}..{MAX_BPM} bpm")
    for group in strings:
        text = next(part for part in group if part) if any(group) else ""
        if not _MINI_NOTATION_RE.match(text):
            errors.append(f"mini-notation {text[:40]!r} contains unsupported characters")
    for match in re.finditer(r"\b(?:s|sound)\(\s*(?:\"([^\"]*)\"|`([^`]*)`)\s*\)", stripped):
        for token in re.split(r"[\s\[\]<>~,*/@!.-]+", match.group(1) or match.group(2) or ""):
            base = token.split(":")[0]
            if base and not base.isdigit() and base not in ALLOWED_SOUNDS:
                errors.append(f"sound {base!r} is not in the allowed sound list")
    if not {"note", "n", "s", "sound"} & set(calls):
        errors.append("pattern produces no events (no note/n/s call)")
    return sorted(set(errors))


# ---------------------------------------------------------------------------
# Standard MIDI File (format 1)
# ---------------------------------------------------------------------------


def _vlq(value: int) -> bytes:
    if value < 0:
        raise ThemeSongError("negative delta time")
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def _track_chunk(events: list[tuple[int, bytes]]) -> bytes:
    body = bytearray()
    last = 0
    ordered = sorted(events, key=lambda item: (item[0], item[1][0] & 0xF0 == 0x90, item[1]))
    for tick, message in ordered:
        body += _vlq(tick - last) + message
        last = tick
    body += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def _note_track(events: list[NoteEvent], channel: int, program: int, name: str) -> bytes:
    ticks_per_step = TICKS_PER_BEAT // 4
    messages: list[tuple[int, bytes]] = [
        (0, b"\xff\x03" + _vlq(len(name)) + name.encode("ascii")),
        (0, bytes((0xC0 | channel, program))),
    ]
    for event in events:
        if not 0 <= event.pitch <= 127:
            raise ThemeSongError(f"pitch {event.pitch} is outside MIDI range")
        start = event.step * ticks_per_step
        end = (event.step + event.length) * ticks_per_step
        messages.append((start, bytes((0x90 | channel, event.pitch, event.velocity))))
        messages.append((end, bytes((0x80 | channel, event.pitch, 0))))
    return _track_chunk(messages)


_DRUM_KEYS = {"bd": 36, "sd": 38, "hh": 42, "oh": 46, "cp": 39, "rim": 37}


def _drum_track(events: list[DrumEvent]) -> bytes:
    ticks_per_step = TICKS_PER_BEAT // 4
    messages: list[tuple[int, bytes]] = [(0, b"\xff\x03\x05Drums")]
    for event in events:
        key = _DRUM_KEYS[event.sound]
        start = event.step * ticks_per_step
        messages.append((start, bytes((0x99, key, 100))))
        messages.append((start + ticks_per_step // 2, bytes((0x89, key, 0))))
    return _track_chunk(messages)


def render_midi(score: Score) -> bytes:
    microseconds_per_beat = round(60_000_000 / score.bpm)
    tempo_track = _track_chunk(
        [
            (0, b"\xff\x51\x03" + struct.pack(">I", microseconds_per_beat)[1:]),
            (0, b"\xff\x58\x04\x04\x02\x18\x08"),
            (score.total_steps * (TICKS_PER_BEAT // 4), b"\xff\x01\x03end"),
        ]
    )
    tracks = [
        tempo_track,
        _note_track(score.melody, 0, 80, "Melody"),
        _note_track(score.chords, 1, 81, "Chords"),
        _note_track(score.bass, 2, 38, "Bass"),
        _drum_track(score.drums),
    ]
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TICKS_PER_BEAT)
    return header + b"".join(tracks)


def parse_midi_note_pairs(payload: bytes) -> tuple[int, int]:
    """Count note-on / note-off messages of a generated file (independent re-read)."""
    if payload[:4] != b"MThd":
        raise ThemeSongError("not a MIDI file")
    ons = offs = 0
    offset = 14
    while offset < len(payload):
        if payload[offset : offset + 4] != b"MTrk":
            raise ThemeSongError("track chunk expected")
        length = struct.unpack(">I", payload[offset + 4 : offset + 8])[0]
        body = payload[offset + 8 : offset + 8 + length]
        offset += 8 + length
        cursor = 0
        while cursor < len(body):
            while body[cursor] & 0x80:
                cursor += 1
            cursor += 1
            status = body[cursor]
            if status == 0xFF:
                meta_length = body[cursor + 2]
                cursor += 3 + meta_length
            elif status & 0xF0 == 0x90:
                ons += 1
                cursor += 3
            elif status & 0xF0 == 0x80:
                offs += 1
                cursor += 3
            elif status & 0xF0 == 0xC0:
                cursor += 2
            else:
                raise ThemeSongError(f"unexpected MIDI status 0x{status:02x}")
    return ons, offs


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def provenance_record(
    *,
    summary: GraphSummary,
    graph_path: Path,
    generator: Path,
    base_dir: Path,
    artifacts: dict[str, tuple[Path, bytes]],
    composition: dict[str, object],
    source: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "pass_evidence": False,
        "source": source,
        "composer_id": COMPOSER_ID,
        "graph_id": summary.graph_id,
        "target_revision": summary.revision,
        "input_hash": summary.canonical_hash,
        "inputs": [{"path": relative(graph_path, base_dir), "content_hash": summary.content_hash}],
        "generator": {"name": generator.name, "content_hash": sha256_file(generator)},
        "composition": composition,
        "artifacts": {
            name: {"path": relative(path, base_dir), "content_hash": sha256_bytes(payload)}
            for name, (path, payload) in sorted(artifacts.items())
        },
        "license": "BSD-3-Clause",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def relative(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
