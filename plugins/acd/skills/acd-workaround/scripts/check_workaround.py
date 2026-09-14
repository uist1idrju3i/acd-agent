# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Validate a completed workaround and observe salvageability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workaround import WorkaroundError, evaluate_completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rework", type=Path, required=True)
    parser.add_argument("--dfa", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--erc-evidence", type=Path)
    parser.add_argument("--drc-evidence", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evaluation = evaluate_completed(
            graph_path=args.graph,
            defects_path=args.defects,
            proposal_path=args.candidates,
            candidate_id=args.candidate_id,
            rework_path=args.rework,
            dfa_path=args.dfa,
            fixture_dir=args.fixture_dir,
            out_dir=args.out_dir,
            approval_path=args.approval,
            erc_path=args.erc_evidence,
            drc_path=args.drc_evidence,
        )
    except WorkaroundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(evaluation.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return (
        0
        if evaluation.salvage is not None
        and evaluation.salvage.verdict == "salvageable"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
