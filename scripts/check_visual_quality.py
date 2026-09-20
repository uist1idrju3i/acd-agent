#!/usr/bin/env python3
"""Check deterministic readability of one SVG projection."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from acd.core.electrical.visual_quality import analyze_svg_readability
from acd.schema.visual_quality import ReadabilityPolicy

DEFAULT_POLICY = Path("profiles/visual-readability-default.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        svg = args.svg.read_bytes()
        ElementTree.fromstring(svg)
        policy = ReadabilityPolicy.model_validate(
            json.loads(args.policy.read_text(encoding="utf-8"))
        )
        report = analyze_svg_readability(svg, policy=policy)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ElementTree.ParseError,
        ValueError,
    ) as exc:
        print(f"malformed input: {exc}", file=sys.stderr)
        return 2
    print(report.model_dump_json())
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
