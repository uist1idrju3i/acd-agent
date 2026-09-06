#!/usr/bin/env python3
"""Validate an agent-proposed Strudel pattern and record it as a theme-song candidate.

This is the L2 steering path: an agent may propose a Strudel pattern text for
the design. The proposal is checked against the allowed Strudel surface
(functions, sounds, mini-notation characters, explicit tempo range, no code
that reaches outside the pattern). Only an accepted proposal is copied to
``--out-dir`` with a provenance record; a rejected proposal stops with every
reason listed. Acceptance is a pattern-text check only and never approves the
design.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from theme_song import (
    ThemeSongError,
    load_graph_summary,
    provenance_record,
    sha256_bytes,
    validate_strudel,
    write_json,
)

STRUDEL_NAME = "theme-song-proposal.strudel.js"
PROVENANCE_NAME = "theme-song-proposal.provenance.json"


def accept_proposal(
    graph_path: Path, proposal_path: Path, out_dir: Path, *, base_dir: Path
) -> Path:
    summary = load_graph_summary(graph_path)
    try:
        source = proposal_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ThemeSongError(f"cannot read proposal {proposal_path}: {exc}") from exc
    problems = validate_strudel(source)
    if problems:
        raise ThemeSongError("proposal rejected: " + "; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    strudel_path = out_dir / STRUDEL_NAME
    strudel_path.write_text(source, encoding="utf-8")
    record = provenance_record(
        summary=summary,
        graph_path=graph_path,
        generator=Path(__file__),
        base_dir=base_dir,
        artifacts={"strudel": (strudel_path, source.encode("utf-8"))},
        composition={
            "proposal_path": proposal_path.as_posix(),
            "proposal_hash": sha256_bytes(source.encode("utf-8")),
        },
        source="agent_proposal",
    )
    provenance_path = out_dir / PROVENANCE_NAME
    write_json(provenance_path, record)
    return provenance_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True, help="design graph JSON")
    parser.add_argument("--proposal", type=Path, required=True, help="Strudel pattern text")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        provenance = accept_proposal(
            args.graph, args.proposal, args.out_dir, base_dir=args.base_dir
        )
    except ThemeSongError as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 1
    print(provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
