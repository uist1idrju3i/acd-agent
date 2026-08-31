"""Print the L3 progress digest of a run for the conversation.

A design loop writes timing records and exploration reports to disk, so a
standalone run otherwise leaves the operator without visible progress. This
entry point renders those records as text and, with ``--json``, as the
machine-readable digest. The digest is an L3 observation and never grants pass
authority: an unreadable record makes the digest ``unknown`` and exits nonzero.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from acd.core.progress_digest import collect_progress_digest, render_progress_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="run output directory to digest",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable digest instead of text",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the digest and report unreadable records fail-closed."""
    args = _parser().parse_args(argv)
    report = collect_progress_digest(args.out)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render_progress_digest(report))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
