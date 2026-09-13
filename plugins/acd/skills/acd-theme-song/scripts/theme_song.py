#!/usr/bin/env python3
"""Theme-song composition for a design graph, rendered as MIDI and acd-mml.

A theme song is an L3 artifact: it presents the design (its identifier,
revision and structure) as music, carries no approval authority and never
flows back into design inputs. Only the Python standard library is used; the
module does not import ``acd`` or any music library, so the artifact can be
regenerated anywhere the plugin is installed.

Two ways produce a :class:`Score`:

* :func:`compose` derives every musical decision from
  ``sha256(canonical graph JSON + salt)``, so the same design revision always
  yields byte-identical MIDI and any change to the design changes the song.
* :func:`load_proposal` reads a *theme song proposal* JSON written by an LLM
  agent and checks it strictly (identity, tempo, bar count, pitch, velocity,
  timing, track/drum names). Accepted proposals render through the same MIDI
  writer. Acceptance judges the proposal text only, never the design.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast

T = TypeVar("T")

SCHEMA_VERSION = "0.1"
ARTIFACT_KIND = "theme_song"
PROPOSAL_ARTIFACT_KIND = "theme_song_proposal"
COMPOSER_ID = "acd-theme-song-composer-v1"
PROPOSAL_COMPOSER_ID = "acd-theme-song-proposal-v1"
STEPS_PER_BAR = 16
TICKS_PER_BEAT = 480
MIN_BPM = 92
MAX_BPM = 140
MIN_BARS = 4
MAX_BARS = 64
MAX_TRACKS = 8
MIN_PROPOSAL_NOTES = 8
MAX_PROPOSAL_EVENTS = 4096
MAX_TITLE_LENGTH = 120
MAX_RATIONALE_LENGTH = 2000

DRUM_KEYS: dict[str, int] = {
    "bd": 36,
    "rim": 37,
    "sd": 38,
    "cp": 39,
    "hh": 42,
    "lt": 45,
    "oh": 46,
    "mt": 47,
    "cr": 49,
    "ht": 50,
    "rd": 51,
}
_NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
_NOTE_ALIASES = {"db": 1, "eb": 3, "gb": 6, "ab": 8, "bb": 10}
_PITCH_NAME_RE = re.compile(r"^([a-g])(#|b)?(-?\d)$")
_TRACK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$")
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


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThemeSongError(f"{label} {path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ThemeSongError(f"{label} {path} must be a JSON object")
    return cast(dict[str, object], loaded)


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
    document = _load_json_object(path, "design graph")
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
class Track:
    name: str
    channel: int
    program: int
    notes: list[NoteEvent] = field(default_factory=list[NoteEvent])


@dataclass
class Score:
    graph_id: str
    revision: str
    seed: str
    bpm: int
    bars: int
    key_name: str
    title: str
    tracks: list[Track] = field(default_factory=list[Track])
    drums: list[DrumEvent] = field(default_factory=list[DrumEvent])

    @property
    def total_steps(self) -> int:
        return self.bars * STEPS_PER_BAR

    @property
    def note_count(self) -> int:
        return sum(len(track.notes) for track in self.tracks)


def pitch_name(pitch: int) -> str:
    octave, index = divmod(pitch, 12)
    return f"{_NOTE_NAMES[index]}{octave - 1}"


def parse_pitch(value: object) -> int:
    """Accept a MIDI number (0..127) or a name such as ``c4``, ``f#5``, ``bb3``."""
    if isinstance(value, bool):
        raise ThemeSongError(f"pitch {value!r} must be a number or note name")
    if isinstance(value, int):
        pitch = value
    elif isinstance(value, str):
        match = _PITCH_NAME_RE.match(value.strip().lower())
        if match is None:
            raise ThemeSongError(f"pitch {value!r} is not a note name like c4 or f#5")
        letter, accidental, octave = match.groups()
        index = _NOTE_NAMES.index(letter)
        if accidental == "#":
            index += 1
        elif accidental == "b":
            index = _NOTE_ALIASES.get(letter + "b", index - 1)
        pitch = (int(octave) + 1) * 12 + index
    else:
        raise ThemeSongError(f"pitch {value!r} must be a number or note name")
    if not 0 <= pitch <= 127:
        raise ThemeSongError(f"pitch {value!r} is outside the MIDI range 0..127")
    return pitch


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


def _check_bars(bars: int) -> None:
    if not MIN_BARS <= bars <= MAX_BARS or bars % 4 != 0:
        raise ThemeSongError(f"bars must be a multiple of 4 within {MIN_BARS}..{MAX_BARS}")


def compose(summary: GraphSummary, *, salt: str = "", bars: int = 16) -> Score:
    """Compose a deterministic score from the graph summary."""
    _check_bars(bars)
    seed = derive_seed(summary, salt)
    rng = random.Random(int(seed.removeprefix("sha256:"), 16))
    minor = summary.requirement_count % 2 == 1
    key_root = rng.randrange(12)
    bpm = MIN_BPM + (summary.component_count * 3 + rng.randrange(12)) % (MAX_BPM - MIN_BPM + 1)
    progression = rng.choice(_MINOR_PROGRESSIONS if minor else _MAJOR_PROGRESSIONS)
    scale = _MINOR if minor else _MAJOR
    melody = Track("Melody", 0, 80)
    chords = Track("Chords", 1, 81)
    bass = Track("Bass", 2, 38)
    score = Score(
        graph_id=summary.graph_id,
        revision=summary.revision,
        seed=seed,
        bpm=bpm,
        bars=bars,
        key_name=f"{_NOTE_NAMES[key_root]} {'minor' if minor else 'major'}",
        title=f"Theme of {summary.graph_id} {summary.revision}",
        tracks=[melody, chords, bass],
    )
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
                chords.notes.append(NoteEvent(bar_start, STEPS_PER_BAR, pitch, 56))
        for step, hit in enumerate(bass_rhythm):
            if hit:
                pitch = chord_root - 12 if step % 8 == 0 else chord_root - 12 + (7 if minor else 12)
                bass.notes.append(NoteEvent(bar_start + step, 2, pitch, 84))
        if bar >= 2 and bar < bars - 1:
            transpose = 1 if section == 2 else 0
            for slot, hit in enumerate(melody_rhythm):
                if not hit:
                    continue
                degree = motif[(slot + bar) % len(motif)] + chord_degree % 3 + transpose
                pitch = _degree_to_pitch(key_root, scale, degree, 5)
                length = 2 if slot % 2 == 0 else 1
                melody.notes.append(NoteEvent(bar_start + slot * 2, length, pitch, 96))
        if bar == bars - 1:
            melody.notes.append(NoteEvent(bar_start, STEPS_PER_BAR, key_root + 60, 100))
        for step in range(STEPS_PER_BAR):
            if kick[step] and bar >= 1:
                score.drums.append(DrumEvent(bar_start + step, "bd"))
            if snare[step] and bar >= 1:
                score.drums.append(DrumEvent(bar_start + step, "sd"))
            if hat[step] and bar >= 1 and section != 3:
                score.drums.append(DrumEvent(bar_start + step, "hh"))
    return score


# ---------------------------------------------------------------------------
# Proposal contract (L2: an LLM agent writes it, this module judges the text)
# ---------------------------------------------------------------------------


def score_to_proposal(score: Score, *, rationale: str) -> dict[str, object]:
    """Serialise a score in the proposal contract so an agent can revise it."""
    return {
        "artifact_kind": PROPOSAL_ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "pass_evidence": False,
        "graph_id": score.graph_id,
        "target_revision": score.revision,
        "title": score.title,
        "rationale": rationale,
        "bpm": score.bpm,
        "bars": score.bars,
        "key": score.key_name,
        "tracks": [
            {
                "name": track.name,
                "channel": track.channel,
                "program": track.program,
                "notes": [
                    {
                        "bar": note.step // STEPS_PER_BAR,
                        "step": note.step % STEPS_PER_BAR,
                        "length": note.length,
                        "pitch": pitch_name(note.pitch),
                        "velocity": note.velocity,
                    }
                    for note in track.notes
                ],
            }
            for track in score.tracks
        ],
        "drums": [
            {
                "bar": drum.step // STEPS_PER_BAR,
                "step": drum.step % STEPS_PER_BAR,
                "sound": drum.sound,
            }
            for drum in score.drums
        ],
    }


def _expect_int(value: object, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ThemeSongError(f"{label} must be an integer")
    if not low <= value <= high:
        raise ThemeSongError(f"{label} must be within {low}..{high}")
    return value


def _expect_text(value: object, label: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThemeSongError(f"{label} must be non-empty text")
    if len(value) > max_length:
        raise ThemeSongError(f"{label} exceeds {max_length} characters")
    return value


def _expect_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ThemeSongError(f"{label} must be a list")
    return cast(list[object], value)


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ThemeSongError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _event_step(record: dict[str, object], label: str, bars: int) -> int:
    bar = _expect_int(record.get("bar"), f"{label}.bar", 0, bars - 1)
    step = _expect_int(record.get("step"), f"{label}.step", 0, STEPS_PER_BAR - 1)
    return bar * STEPS_PER_BAR + step


def load_proposal(document: dict[str, object], summary: GraphSummary) -> Score:
    """Check an agent proposal and turn it into a score, or raise with every reason."""
    errors: list[str] = []

    def check(fn: Callable[..., T], *args: object) -> T | None:
        try:
            return fn(*args)
        except ThemeSongError as exc:
            errors.append(str(exc))
            return None

    if document.get("artifact_kind") != PROPOSAL_ARTIFACT_KIND:
        errors.append(f"artifact_kind must be {PROPOSAL_ARTIFACT_KIND!r}")
    if document.get("pass_evidence") is not False:
        errors.append("pass_evidence must be false")
    if document.get("graph_id") != summary.graph_id:
        errors.append(f"graph_id must be {summary.graph_id!r}")
    if document.get("target_revision") != summary.revision:
        errors.append(f"target_revision must be {summary.revision!r}")
    title = check(_expect_text, document.get("title"), "title", MAX_TITLE_LENGTH)
    check(_expect_text, document.get("rationale"), "rationale", MAX_RATIONALE_LENGTH)
    key_name = check(_expect_text, document.get("key"), "key", 32)
    bpm = check(_expect_int, document.get("bpm"), "bpm", MIN_BPM, MAX_BPM)
    bars = check(_expect_int, document.get("bars"), "bars", MIN_BARS, MAX_BARS)
    if bars is not None and bars % 4 != 0:
        errors.append("bars must be a multiple of 4")
    bar_limit = bars if bars is not None and bars % 4 == 0 else MAX_BARS

    tracks: list[Track] = []
    raw_tracks = check(_expect_list, document.get("tracks"), "tracks")
    if raw_tracks is not None:
        raw_track_list = raw_tracks
        if not 1 <= len(raw_track_list) <= MAX_TRACKS:
            errors.append(f"tracks must contain 1..{MAX_TRACKS} entries")
        channels: set[int] = set()
        names: set[str] = set()
        for index, raw in enumerate(raw_track_list[:MAX_TRACKS]):
            label = f"tracks[{index}]"
            record_map = check(_expect_object, raw, label)
            if record_map is None:
                continue
            name = record_map.get("name")
            if not isinstance(name, str) or not _TRACK_NAME_RE.match(name):
                errors.append(f"{label}.name must be a short ASCII name")
                name = f"track{index}"
            elif name in names:
                errors.append(f"{label}.name {name!r} is duplicated")
            names.add(name)
            channel = check(_expect_int, record_map.get("channel"), f"{label}.channel", 0, 15)
            if channel == 9:
                errors.append(f"{label}.channel 9 is reserved for drums")
            elif channel is not None and channel in channels:
                errors.append(f"{label}.channel {channel} is used twice")
            if channel is not None:
                channels.add(channel)
            program = check(_expect_int, record_map.get("program"), f"{label}.program", 0, 127)
            track = Track(name, channel or 0, program or 0)
            raw_notes = check(_expect_list, record_map.get("notes"), f"{label}.notes")
            for note_index, raw_note in enumerate(raw_notes or []):
                note_label = f"{label}.notes[{note_index}]"
                note_map = check(_expect_object, raw_note, note_label)
                if note_map is None:
                    continue
                step = check(_event_step, note_map, note_label, bar_limit)
                length = check(
                    _expect_int,
                    note_map.get("length"),
                    f"{note_label}.length",
                    1,
                    STEPS_PER_BAR * 4,
                )
                pitch = check(parse_pitch, note_map.get("pitch"))
                velocity = check(
                    _expect_int, note_map.get("velocity"), f"{note_label}.velocity", 1, 127
                )
                if step is None or length is None or pitch is None or velocity is None:
                    continue
                if step + length > bar_limit * STEPS_PER_BAR:
                    errors.append(f"{note_label} ends after the last bar")
                track.notes.append(NoteEvent(step, length, pitch, velocity))
            tracks.append(track)

    drums: list[DrumEvent] = []
    raw_drums = check(_expect_list, document.get("drums", []), "drums")
    for index, raw in enumerate(raw_drums or []):
        label = f"drums[{index}]"
        record_map = check(_expect_object, raw, label)
        if record_map is None:
            continue
        step = check(_event_step, record_map, label, bar_limit)
        sound = record_map.get("sound")
        if not isinstance(sound, str) or sound not in DRUM_KEYS:
            errors.append(f"{label}.sound must be one of {sorted(DRUM_KEYS)}")
        elif step is not None:
            drums.append(DrumEvent(step, sound))

    note_total = sum(len(track.notes) for track in tracks)
    if not errors and note_total < MIN_PROPOSAL_NOTES:
        errors.append(f"proposal must contain at least {MIN_PROPOSAL_NOTES} notes")
    if note_total + len(drums) > MAX_PROPOSAL_EVENTS:
        errors.append(f"proposal exceeds {MAX_PROPOSAL_EVENTS} events")
    for track in tracks:
        seen: set[tuple[int, int]] = set()
        for note in track.notes:
            if (note.step, note.pitch) in seen:
                name = pitch_name(note.pitch)
                errors.append(f"track {track.name!r} repeats {name} at step {note.step}")
                break
            seen.add((note.step, note.pitch))
    if errors or title is None or key_name is None or bpm is None or bars is None:
        raise ThemeSongError("proposal rejected: " + "; ".join(sorted(set(errors))))

    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for track in tracks:
        track.notes.sort(key=lambda note: (note.step, note.pitch))
    drums.sort(key=lambda drum: (drum.step, drum.sound))
    return Score(
        graph_id=summary.graph_id,
        revision=summary.revision,
        seed=sha256_bytes(canonical.encode("utf-8")),
        bpm=bpm,
        bars=bars,
        key_name=key_name,
        title=title,
        tracks=tracks,
        drums=drums,
    )


def load_proposal_file(path: Path, summary: GraphSummary) -> Score:
    return load_proposal(_load_json_object(path, "theme song proposal"), summary)


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


def _text_meta(kind: int, text: str) -> bytes:
    payload = text.encode("utf-8")
    return bytes((0xFF, kind)) + _vlq(len(payload)) + payload


def _note_track(track: Track) -> bytes:
    ticks_per_step = TICKS_PER_BEAT // 4
    messages: list[tuple[int, bytes]] = [
        (0, _text_meta(0x03, track.name)),
        (0, bytes((0xC0 | track.channel, track.program))),
    ]
    for event in track.notes:
        if not 0 <= event.pitch <= 127:
            raise ThemeSongError(f"pitch {event.pitch} is outside MIDI range")
        start = event.step * ticks_per_step
        end = (event.step + event.length) * ticks_per_step
        messages.append((start, bytes((0x90 | track.channel, event.pitch, event.velocity))))
        messages.append((end, bytes((0x80 | track.channel, event.pitch, 0))))
    return _track_chunk(messages)


def _drum_track(events: list[DrumEvent]) -> bytes:
    ticks_per_step = TICKS_PER_BEAT // 4
    messages: list[tuple[int, bytes]] = [(0, _text_meta(0x03, "Drums"))]
    for event in events:
        key = DRUM_KEYS[event.sound]
        start = event.step * ticks_per_step
        messages.append((start, bytes((0x99, key, 100))))
        messages.append((start + ticks_per_step // 2, bytes((0x89, key, 0))))
    return _track_chunk(messages)


def render_midi(score: Score) -> bytes:
    microseconds_per_beat = round(60_000_000 / score.bpm)
    tempo_track = _track_chunk(
        [
            (0, _text_meta(0x03, score.title)),
            (0, _text_meta(0x01, f"graph {score.graph_id} revision {score.revision}")),
            (0, _text_meta(0x01, f"seed {score.seed}")),
            (0, b"\xff\x51\x03" + struct.pack(">I", microseconds_per_beat)[1:]),
            (0, b"\xff\x58\x04\x04\x02\x18\x08"),
            (score.total_steps * (TICKS_PER_BEAT // 4), b"\xff\x01\x03end"),
        ]
    )
    tracks = [tempo_track, *(_note_track(track) for track in score.tracks)]
    if score.drums:
        tracks.append(_drum_track(score.drums))
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
                cursor += 2
                meta_length = 0
                while body[cursor] & 0x80:
                    meta_length = (meta_length << 7) | (body[cursor] & 0x7F)
                    cursor += 1
                meta_length = (meta_length << 7) | body[cursor]
                cursor += 1 + meta_length
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


def render_checked_midi(score: Score) -> tuple[bytes, int]:
    """Render MIDI and confirm by independent re-read that every note-on has a note-off."""
    midi_bytes = render_midi(score)
    ons, offs = parse_midi_note_pairs(midi_bytes)
    if ons == 0 or ons != offs:
        raise ThemeSongError(f"MIDI re-read mismatch: {ons} note-on vs {offs} note-off")
    return midi_bytes, ons


@dataclass(frozen=True)
class MmlNote:
    channel: int
    start_tick: int
    end_tick: int
    pitch: int
    velocity: int


@dataclass(frozen=True)
class MmlSong:
    bpm: int
    notes: tuple[MmlNote, ...]
    voice_ticks: dict[str, int]


@dataclass(frozen=True)
class _MmlEvent:
    start_tick: int
    end_tick: int
    pitch: int
    velocity: int
    channel: int
    drum: bool = False


_MML_NOTE_NAMES = tuple(name.replace("#", "+") for name in _NOTE_NAMES)
_MML_LENGTHS = ((16, 1), (8, 2), (4, 4), (2, 8), (1, 16))
_MML_NOTE_RE = re.compile(r"^([a-g]\+?)(\d+)?$")
_MML_REST_RE = re.compile(r"^r(\d+)?$")
_MML_VOICE_RE = re.compile(r"^; voice ([A-Z]+): .* channel (\d+)")
_MML_VOICE_LINE_RE = re.compile(r"^([A-Z]+)\s+(.+)$")


def _mml_voice_label(index: int) -> str:
    label = ""
    value = index
    while True:
        label = chr(ord("A") + value % 26) + label
        value = value // 26 - 1
        if value < 0:
            return label


def _mml_chunks(steps: int) -> list[int]:
    chunks: list[int] = []
    remaining = steps
    for chunk, _ in _MML_LENGTHS:
        while remaining >= chunk:
            chunks.append(chunk)
            remaining -= chunk
    if remaining:
        raise ThemeSongError(f"MML length cannot represent {steps} steps")
    return chunks


def _mml_length_number(step_count: int) -> list[int]:
    lengths = dict(_MML_LENGTHS)
    return [lengths[chunk] for chunk in _mml_chunks(step_count)]


def _mml_note_name(pitch: int) -> str:
    return _MML_NOTE_NAMES[pitch % 12]


def _mml_note_token(pitch: int, steps: int) -> str:
    name = _mml_note_name(pitch)
    return "&".join(f"{name}{length}" for length in _mml_length_number(steps))


def _mml_rest_tokens(ticks: int) -> list[str]:
    step_ticks = TICKS_PER_BEAT // 4
    if ticks % step_ticks:
        raise ThemeSongError("MML rest does not align to a step")
    return [f"r{length}" for length in _mml_length_number(ticks // step_ticks)]


def _mml_events(score: Score) -> list[tuple[str, str, int, int, list[_MmlEvent]]]:
    grouped: list[tuple[str, str, int, int, list[_MmlEvent]]] = []
    step_ticks = TICKS_PER_BEAT // 4
    for track in score.tracks:
        voices: list[list[_MmlEvent]] = []
        for note in sorted(track.notes, key=lambda item: (item.step, item.pitch)):
            event = _MmlEvent(
                note.step * step_ticks,
                (note.step + note.length) * step_ticks,
                note.pitch,
                note.velocity,
                track.channel,
            )
            for voice in voices:
                if voice[-1].end_tick <= event.start_tick:
                    voice.append(event)
                    break
            else:
                voices.append([event])
        grouped.extend(
            (track.name, "track", track.channel, track.program, voice) for voice in voices
        )
    drum_voices: list[list[_MmlEvent]] = []
    for drum in sorted(score.drums, key=lambda item: (item.step, DRUM_KEYS[item.sound])):
        start_tick = drum.step * step_ticks
        event = _MmlEvent(
            start_tick,
            start_tick + step_ticks // 2,
            DRUM_KEYS[drum.sound],
            100,
            9,
            True,
        )
        for voice in drum_voices:
            if voice[-1].end_tick <= event.start_tick:
                voice.append(event)
                break
        else:
            drum_voices.append([event])
    grouped.extend(("Drums", "drums", 9, 0, voice) for voice in drum_voices)
    return grouped


def render_mml(score: Score) -> str:
    """Render a Score as deterministic, text-readable acd-mml 0.1."""
    step_ticks = TICKS_PER_BEAT // 4
    bar_ticks = STEPS_PER_BAR * step_ticks
    lines = [
        "; acd-mml 0.1",
        f"; title: {score.title}",
        f"; graph: {score.graph_id} revision {score.revision}",
        f"; seed: {score.seed}",
        f"; key: {score.key_name}",
        f"; bars: {score.bars} (16 steps per bar, l16 = 1 step, 480 ticks per beat)",
    ]
    grouped = _mml_events(score)
    counts: dict[tuple[str, str], int] = {}
    for name, kind, _, _, _ in grouped:
        counts[(name, kind)] = counts.get((name, kind), 0) + 1
    numbers: dict[tuple[str, str], int] = {}
    for voice_index, (name, kind, channel, program, events) in enumerate(grouped):
        label = _mml_voice_label(voice_index)
        key = (name, kind)
        numbers[key] = numbers.get(key, 0) + 1
        program_text = f" program {program}" if kind == "track" else ""
        lines.append(
            f'; voice {label}: track "{name}" channel {channel}{program_text} '
            f"(voice {numbers[key]}/{counts[key]})"
        )
        first = events[0]
        first_octave = first.pitch // 12 - 1
        prefix = [f"t{score.bpm}"]
        if kind == "track":
            prefix.append(f"@{program}")
        prefix.extend((f"v{first.velocity}", f"o{first_octave}", "l16"))
        by_bar: dict[int, list[str]] = {}
        cursor = 0
        velocity = first.velocity
        octave = first_octave
        for event in events:
            if event.start_tick < cursor:
                raise ThemeSongError("MML voice events overlap")
            gap = event.start_tick - cursor
            while gap:
                bar_end = ((cursor // bar_ticks) + 1) * bar_ticks
                rest_ticks = min(gap, bar_end - cursor)
                by_bar.setdefault(cursor // bar_ticks, []).extend(
                    _mml_rest_tokens(rest_ticks)
                )
                cursor += rest_ticks
                gap -= rest_ticks
            controls: list[str] = []
            event_octave = event.pitch // 12 - 1
            if event.velocity != velocity:
                controls.append(f"v{event.velocity}")
                velocity = event.velocity
            if event_octave != octave:
                controls.append(f"o{event_octave}")
                octave = event_octave
            token = (
                f"{_mml_note_name(event.pitch)}32 r32"
                if event.drum
                else _mml_note_token(event.pitch, (event.end_tick - event.start_tick) // step_ticks)
            )
            by_bar.setdefault(event.start_tick // bar_ticks, []).append(
                " ".join([*controls, token])
            )
            cursor = event.start_tick + step_ticks if event.drum else event.end_tick
        while cursor < score.total_steps * step_ticks:
            bar_end = ((cursor // bar_ticks) + 1) * bar_ticks
            rest_ticks = min(score.total_steps * step_ticks - cursor, bar_end - cursor)
            by_bar.setdefault(cursor // bar_ticks, []).extend(_mml_rest_tokens(rest_ticks))
            cursor += rest_ticks
        if cursor != score.total_steps * step_ticks:
            raise ThemeSongError("MML voice does not fill the score duration")
        for bar in range(score.bars):
            tokens = by_bar.get(bar, [])
            if bar == 0:
                tokens = [*prefix, *tokens]
            lines.append(f"{label} " + " ".join(tokens) + f" ; bar {bar}")
    return "\n".join(lines) + "\n"


def _mml_ticks(length: int, default: int) -> int:
    value = default if length == 0 else length
    if value <= 0 or TICKS_PER_BEAT * 4 % value:
        raise ThemeSongError(f"invalid MML length {value}")
    return TICKS_PER_BEAT * 4 // value


def parse_mml(text: str) -> MmlSong:
    """Parse acd-mml independently of the renderer."""
    voices: dict[str, int] = {}
    voice_ticks: dict[str, int] = {}
    notes: list[MmlNote] = []
    current_voice: str | None = None
    current_bpm: int | None = None
    state: dict[str, list[int | bool]] = {}
    for raw_line in text.splitlines():
        voice_match = _MML_VOICE_RE.match(raw_line.strip())
        if voice_match:
            label, channel = voice_match.groups()
            if label in voices:
                raise ThemeSongError(f"duplicate MML voice header {label}")
            voices[label] = int(channel)
            voice_ticks[label] = 0
            state[label] = [4, 100, 16, False]
            current_voice = label
            continue
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        match = _MML_VOICE_LINE_RE.match(line)
        if match is None or current_voice is None or match.group(1) != current_voice:
            raise ThemeSongError("MML voice line has no preceding voice header")
        octave, velocity, default_length, tempo_seen = state[current_voice]
        assert isinstance(octave, int)
        assert isinstance(velocity, int)
        assert isinstance(default_length, int)
        assert isinstance(tempo_seen, bool)
        cursor = voice_ticks[current_voice]
        for token in match.group(2).split():
            if token.startswith("t") and token[1:].isdigit():
                line_bpm = int(token[1:])
                if current_bpm is None:
                    current_bpm = line_bpm
                elif current_bpm != line_bpm:
                    raise ThemeSongError("MML tempo differs between voices")
                tempo_seen = True
                continue
            if token.startswith("@") and token[1:].isdigit():
                continue
            if token.startswith("v") and token[1:].isdigit():
                velocity = int(token[1:])
                if not 1 <= velocity <= 127:
                    raise ThemeSongError("MML velocity is outside 1..127")
                continue
            if token.startswith("o") and token[1:].lstrip("-").isdigit():
                octave = int(token[1:])
                continue
            if token.startswith("l") and token[1:].isdigit():
                default_length = int(token[1:])
                _mml_ticks(default_length, default_length)
                continue
            rest_match = _MML_REST_RE.match(token)
            if rest_match:
                cursor += _mml_ticks(int(rest_match.group(1) or 0), default_length)
                continue
            parts = token.split("&")
            pitches: list[int] = []
            total_ticks = 0
            for part in parts:
                note_match = _MML_NOTE_RE.match(part)
                if note_match is None:
                    raise ThemeSongError(f"unknown MML token {token!r}")
                name, length_text = note_match.groups()
                pitch = (octave + 1) * 12 + _MML_NOTE_NAMES.index(name)
                if not 0 <= pitch <= 127:
                    raise ThemeSongError(f"MML pitch is outside 0..127: {part}")
                pitches.append(pitch)
                total_ticks += _mml_ticks(int(length_text or 0), default_length)
            if len(set(pitches)) != 1:
                raise ThemeSongError("MML tied notes must have the same pitch")
            notes.append(
                MmlNote(
                    voices[current_voice],
                    cursor,
                    cursor + total_ticks,
                    pitches[0],
                    velocity,
                )
            )
            cursor += total_ticks
        state[current_voice] = [octave, velocity, default_length, tempo_seen]
        voice_ticks[current_voice] = cursor
    if current_bpm is None or not voices or not all(bool(values[3]) for values in state.values()):
        raise ThemeSongError("MML has no voices or tempo")
    return MmlSong(current_bpm, tuple(notes), voice_ticks)


def check_mml_round_trip(score: Score, text: str) -> None:
    """Compare an independently parsed MML song with the Score fields."""
    song = parse_mml(text)
    if song.bpm != score.bpm:
        raise ThemeSongError(f"MML BPM mismatch: {song.bpm} != {score.bpm}")
    expected_ticks = score.total_steps * 120
    if any(ticks != expected_ticks for ticks in song.voice_ticks.values()):
        raise ThemeSongError("MML voice duration does not match the score")
    expected_by_channel: dict[int, list[tuple[int, int, int, int]]] = {}
    for track in score.tracks:
        expected_by_channel.setdefault(track.channel, []).extend(
            (note.step * 120, (note.step + note.length) * 120, note.pitch, note.velocity)
            for note in track.notes
        )
    if score.drums:
        expected_by_channel.setdefault(9, []).extend(
            (drum.step * 120, drum.step * 120 + 60, DRUM_KEYS[drum.sound], 100)
            for drum in score.drums
        )
    actual_by_channel: dict[int, list[tuple[int, int, int, int]]] = {}
    for note in song.notes:
        actual_by_channel.setdefault(note.channel, []).append(
            (note.start_tick, note.end_tick, note.pitch, note.velocity)
        )
    if len(song.notes) != score.note_count + len(score.drums):
        raise ThemeSongError("MML note count does not match the score")
    if {
        channel: sorted(values) for channel, values in actual_by_channel.items()
    } != {channel: sorted(values) for channel, values in expected_by_channel.items()}:
        raise ThemeSongError("MML note data does not match the Score")


def render_checked_mml(score: Score) -> str:
    text = render_mml(score)
    check_mml_round_trip(score, text)
    return text


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def provenance_record(
    *,
    summary: GraphSummary,
    graph_path: Path,
    generator: Path,
    base_dir: Path,
    inputs: list[tuple[Path, str]],
    artifacts: dict[str, tuple[Path, bytes]],
    composition: dict[str, object],
    source: str,
    composer_id: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "pass_evidence": False,
        "source": source,
        "composer_id": composer_id,
        "graph_id": summary.graph_id,
        "target_revision": summary.revision,
        "input_hash": summary.canonical_hash,
        "inputs": [
            {"path": relative(graph_path, base_dir), "content_hash": summary.content_hash},
            *(
                {"path": relative(path, base_dir), "content_hash": digest}
                for path, digest in inputs
            ),
        ],
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
