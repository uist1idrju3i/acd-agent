#!/usr/bin/env python3
"""Theme-song composition for a design graph, rendered as a Standard MIDI File.

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
