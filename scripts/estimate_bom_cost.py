#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@8ae1e927",
# ]
# ///
"""Estimate opt-in BOM cost from a saved deterministic price book."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.manufacturing.bom_cost import bom_cost_markdown, estimate_bom_cost
from acd.schema import DesignGraph, PartLifecycleRegistry, PartPriceBook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--price-book", required=True, type=Path)
    parser.add_argument("--lifecycle", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        price_book = PartPriceBook.model_validate(
            json.loads(args.price_book.read_text(encoding="utf-8"))
        )
        if args.as_of is not None:
            price_book = price_book.model_copy(update={"as_of": args.as_of})
        lifecycle = None
        if args.lifecycle is not None:
            lifecycle = PartLifecycleRegistry.model_validate(
                json.loads(args.lifecycle.read_text(encoding="utf-8"))
            )
            if args.as_of is not None:
                lifecycle = lifecycle.model_copy(update={"as_of": args.as_of})
        estimate = estimate_bom_cost(
            graph,
            extract_electrical_lane(graph),
            price_book,
            lifecycle,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                estimate.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if args.out_md is not None:
            args.out_md.parent.mkdir(parents=True, exist_ok=True)
            args.out_md.write_text(
                bom_cost_markdown(estimate),
                encoding="utf-8",
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"BOM cost input error: {error}", file=sys.stderr)
        return 2
    return 0 if estimate.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
