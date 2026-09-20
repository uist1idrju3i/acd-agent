#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@48dea1f5",
# ]
# ///
"""Run the opt-in PDN/IR drop estimate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.electrical.pdn import analyze_pdn, pdn_markdown
from acd.schema import DesignGraph, PdnAnalysisRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        request = PdnAnalysisRequest.model_validate(
            json.loads(args.request.read_text(encoding="utf-8"))
        )
        result = analyze_pdn(graph, request, args.board)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if args.out_md is not None:
            args.out_md.parent.mkdir(parents=True, exist_ok=True)
            args.out_md.write_text(pdn_markdown(result), encoding="utf-8")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"PDN input error: {error}", file=sys.stderr)
        return 2
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
