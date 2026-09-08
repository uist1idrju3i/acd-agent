"""Print the machine-generated basis for the final report's factual sections.

The final report's source-change statements (commits and worktree state since
the bootstrap record) and design-value statements (component values, nets) must
be produced by this entry point, not written from memory. The rendered text is
intended for verbatim inclusion. The basis is an L3 observation and never
grants pass authority: ``status != "pass"`` exits nonzero.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from acd.core.final_report_basis import (
    collect_final_report_basis,
    render_final_report_basis,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root the source-change section inspects",
    )
    parser.add_argument(
        "--design-input",
        type=Path,
        default=None,
        help="spec.json or graph.json to extract design values from",
    )
    parser.add_argument(
        "--bootstrap-record",
        type=Path,
        default=None,
        help="explicit bootstrap record path (default: <root>/.openhands/bootstrap-record.json)",
    )
    parser.add_argument(
        "--bootstrap-revision",
        default=None,
        help="expected bootstrap source revision (must match the record when both exist)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable basis instead of text",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the basis and report unknown sections fail-closed."""
    args = _parser().parse_args(argv)
    report = collect_final_report_basis(
        args.root,
        design_input=args.design_input,
        bootstrap_record=args.bootstrap_record,
        bootstrap_revision=args.bootstrap_revision,
    )
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render_final_report_basis(report))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
