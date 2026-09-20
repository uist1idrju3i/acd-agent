#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@e8d0307410666e9ed11f794b9e46d0595a3528f3",
# ]
# ///
"""Summarize opt-in BOM compliance declarations without issuing a verdict."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.manufacturing.bom_compliance import (
    compliance_summary_markdown,
    summarize_bom_compliance,
)
from acd.schema import ComplianceDeclarationRegistry, DesignGraph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        registry = ComplianceDeclarationRegistry.model_validate(
            json.loads(args.registry.read_text(encoding="utf-8"))
        )
        if args.as_of is not None:
            registry = registry.model_copy(update={"as_of": args.as_of})
        summary = summarize_bom_compliance(
            graph,
            extract_electrical_lane(graph),
            registry,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                summary.model_dump(mode="json"),
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
                compliance_summary_markdown(summary),
                encoding="utf-8",
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"BOM compliance input error: {error}", file=sys.stderr)
        return 2
    return 0 if summary.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
