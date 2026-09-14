# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Write a deterministic workaround candidate set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workaround import WorkaroundError, build_proposal, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--defect-id", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        proposal = build_proposal(args.graph, args.defects, args.defect_id)
    except WorkaroundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    path = args.out_dir / "workaround-candidates.json"
    write_json(path, proposal.model_dump(mode="json"))
    print(json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if proposal.defect_check_status == "workaround_eligible" else 1


if __name__ == "__main__":
    raise SystemExit(main())
