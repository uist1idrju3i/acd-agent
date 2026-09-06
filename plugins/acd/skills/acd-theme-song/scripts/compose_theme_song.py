#!/usr/bin/env python3
"""Compose the theme song of a design graph as a Standard MIDI File.

Writes ``theme-song.mid`` and ``theme-song.provenance.json`` into ``--out-dir``.
Without ``--proposal`` the song is derived deterministically from the graph
(``source: deterministic``). With ``--proposal`` an LLM-authored theme song
proposal JSON is checked strictly and rendered (``source: agent_proposal``);
a rejected proposal writes nothing and lists every reason.
``--proposal-out`` additionally writes the resulting score in the proposal
contract so an agent can revise it and feed it back through ``--proposal``.

The result is an L3 artifact: it never approves a design and never flows back
into design inputs. Missing or malformed inputs stop generation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from theme_song import (
    COMPOSER_ID,
    PROPOSAL_COMPOSER_ID,
    ThemeSongError,
    compose,
    load_graph_summary,
    load_proposal_file,
    provenance_record,
    render_checked_midi,
    score_to_proposal,
    sha256_file,
    write_json,
)

MIDI_NAME = "theme-song.mid"
PROVENANCE_NAME = "theme-song.provenance.json"
PROPOSAL_NAME = "theme-song.proposal.json"


def compose_theme_song(
    graph_path: Path,
    out_dir: Path,
    *,
    salt: str,
    bars: int,
    base_dir: Path,
    proposal_path: Path | None = None,
    proposal_out: Path | None = None,
) -> Path:
    summary = load_graph_summary(graph_path)
    if proposal_path is None:
        score = compose(summary, salt=salt, bars=bars)
        source = "deterministic"
        composer_id = COMPOSER_ID
        extra_inputs: list[tuple[Path, str]] = []
        rationale = (
            "Derived deterministically from the design graph structure; "
            "revise this proposal to express the product concept."
        )
    else:
        score = load_proposal_file(proposal_path, summary)
        source = "agent_proposal"
        composer_id = PROPOSAL_COMPOSER_ID
        extra_inputs = [(proposal_path, sha256_file(proposal_path))]
        rationale = "Accepted agent proposal."
    midi_bytes, note_events = render_checked_midi(score)

    out_dir.mkdir(parents=True, exist_ok=True)
    midi_path = out_dir / MIDI_NAME
    midi_path.write_bytes(midi_bytes)
    if proposal_out is not None:
        proposal_out.parent.mkdir(parents=True, exist_ok=True)
        write_json(proposal_out, score_to_proposal(score, rationale=rationale))
    record = provenance_record(
        summary=summary,
        graph_path=graph_path,
        generator=Path(__file__),
        base_dir=base_dir,
        inputs=extra_inputs,
        artifacts={"midi": (midi_path, midi_bytes)},
        composition={
            "seed": score.seed,
            "salt": salt if proposal_path is None else "",
            "title": score.title,
            "bpm": score.bpm,
            "bars": score.bars,
            "key": score.key_name,
            "tracks": [track.name for track in score.tracks],
            "note_events": note_events,
            "node_kinds": summary.node_kinds,
        },
        source=source,
        composer_id=composer_id,
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
    parser.add_argument(
        "--proposal", type=Path, default=None, help="agent-authored theme song proposal JSON"
    )
    parser.add_argument(
        "--proposal-out",
        type=Path,
        default=None,
        help=f"write the resulting score as a proposal JSON (for example {PROPOSAL_NAME})",
    )
    args = parser.parse_args(argv)
    try:
        provenance = compose_theme_song(
            args.graph,
            args.out_dir,
            salt=args.salt,
            bars=args.bars,
            base_dir=args.base_dir,
            proposal_path=args.proposal,
            proposal_out=args.proposal_out,
        )
    except ThemeSongError as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 1
    print(provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
