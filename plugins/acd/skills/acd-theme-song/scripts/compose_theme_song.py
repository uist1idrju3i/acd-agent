#!/usr/bin/env python3
"""Compose the deterministic theme song of a design graph.

Writes ``theme-song.strudel.js``, ``theme-song.mid`` and
``theme-song.provenance.json`` into ``--out-dir``. The result is an L3
artifact: it never approves a design and never flows back into design inputs.
Missing or malformed inputs stop generation instead of producing a song.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from theme_song import (
    ThemeSongError,
    compose,
    load_graph_summary,
    parse_midi_note_pairs,
    provenance_record,
    render_midi,
    render_strudel,
    validate_strudel,
    write_json,
)

STRUDEL_NAME = "theme-song.strudel.js"
MIDI_NAME = "theme-song.mid"
PROVENANCE_NAME = "theme-song.provenance.json"


def compose_theme_song(
    graph_path: Path, out_dir: Path, *, salt: str, bars: int, base_dir: Path
) -> Path:
    summary = load_graph_summary(graph_path)
    score = compose(summary, salt=salt, bars=bars)
    strudel_text = render_strudel(score)
    problems = validate_strudel(strudel_text)
    if problems:
        raise ThemeSongError("composer output failed self-check: " + "; ".join(problems))
    midi_bytes = render_midi(score)
    ons, offs = parse_midi_note_pairs(midi_bytes)
    if ons == 0 or ons != offs:
        raise ThemeSongError(f"MIDI re-read mismatch: {ons} note-on vs {offs} note-off")

    out_dir.mkdir(parents=True, exist_ok=True)
    strudel_path = out_dir / STRUDEL_NAME
    midi_path = out_dir / MIDI_NAME
    strudel_path.write_text(strudel_text, encoding="utf-8")
    midi_path.write_bytes(midi_bytes)
    record = provenance_record(
        summary=summary,
        graph_path=graph_path,
        generator=Path(__file__),
        base_dir=base_dir,
        artifacts={
            "strudel": (strudel_path, strudel_text.encode("utf-8")),
            "midi": (midi_path, midi_bytes),
        },
        composition={
            "seed": score.seed,
            "salt": salt,
            "bpm": score.bpm,
            "bars": score.bars,
            "key": score.key_name,
            "progression_degrees": list(score.progression),
            "note_events": ons,
            "node_kinds": summary.node_kinds,
        },
        source="deterministic",
    )
    provenance_path = out_dir / PROVENANCE_NAME
    write_json(provenance_path, record)
    return provenance_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True, help="design graph JSON")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--salt", default="", help="optional text mixed into the seed")
    parser.add_argument("--bars", type=int, default=16, help="song length (multiple of 4)")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        provenance = compose_theme_song(
            args.graph, args.out_dir, salt=args.salt, bars=args.bars, base_dir=args.base_dir
        )
    except ThemeSongError as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 1
    print(provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
