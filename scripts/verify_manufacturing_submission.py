#!/usr/bin/env python3
"""Verify the independent L1 manufacturing-submission verdict."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from acd.core.manufacturing_submission import (
    ManufacturingSubmissionError,
    evaluate_manufacturing_submission,
    manufacturing_submission_content_hash_payload,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.manufacturing_submission import ManufacturingSubmissionVerdict


def _verify_verdict(
    *,
    verdict_path: Path,
    graph_path: Path,
    require_authoritative: bool,
) -> int:
    try:
        verdict = ManufacturingSubmissionVerdict.model_validate_json(
            verdict_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        print(
            "FAIL: could not parse manufacturing submission verdict "
            f"{verdict_path}: {exc}",
            file=sys.stderr,
        )
        return 2

    expected_hash = canonical_json_sha256(
        manufacturing_submission_content_hash_payload(verdict.model_dump(mode="json"))
    )
    if verdict.content_sha256 != expected_hash:
        print(
            f"FAIL: manufacturing submission verdict content hash mismatch "
            f"(expected={expected_hash!r}, actual={verdict.content_sha256!r})",
            file=sys.stderr,
        )
        return 2
    if verdict.status != "pass":
        print(
            f"FAIL: manufacturing submission verdict status={verdict.status!r}; "
            f"reasons={list(verdict.reasons)!r}",
            file=sys.stderr,
        )
        return 2
    try:
        graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        print(f"FAIL: could not parse design graph {graph_path}: {exc}", file=sys.stderr)
        return 2
    if verdict.target_revision != graph.revision:
        print(
            f"FAIL: manufacturing submission verdict revision mismatch "
            f"(target={verdict.target_revision!r}, graph={graph.revision!r})",
            file=sys.stderr,
        )
        return 2
    if verdict.graph_id != graph.graph_id:
        print(
            f"FAIL: manufacturing submission verdict graph_id mismatch "
            f"(verdict={verdict.graph_id!r}, graph={graph.graph_id!r})",
            file=sys.stderr,
        )
        return 2
    if require_authoritative and (
        not verdict.authoritative
        or any(value != "authoritative" for value in verdict.evidence_class.values())
    ):
        print(
            "FAIL: manufacturing submission verdict does not contain authoritative Evidence",
            file=sys.stderr,
        )
        return 2
    for check in verdict.checks:
        print(f"{check.status.upper()}: {check.check_id}: {check.detail}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-out", type=Path)
    parser.add_argument("--enclosure-out", type=Path)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verdict", type=Path)
    parser.add_argument("--require-authoritative", action="store_true")
    args = parser.parse_args(argv)
    if args.verdict is not None:
        if (
            args.board_out is not None
            or args.enclosure_out is not None
            or args.out is not None
        ):
            parser.error(
                "--verdict cannot be used with --board-out, --enclosure-out, or --out"
            )
        return _verify_verdict(
            verdict_path=args.verdict,
            graph_path=args.graph,
            require_authoritative=args.require_authoritative,
        )
    if args.board_out is None or args.enclosure_out is None or args.out is None:
        parser.error(
            "--board-out, --enclosure-out, and --out are required unless --verdict is used"
        )
    try:
        verdict = evaluate_manufacturing_submission(
            board_dir=args.board_out,
            enclosure_dir=args.enclosure_out,
            graph_path=args.graph,
            require_authoritative=args.require_authoritative,
        )
    except ManufacturingSubmissionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(verdict.model_dump_json(indent=2) + "\n", encoding="utf-8")
    for check in verdict.checks:
        print(f"{check.status.upper()}: {check.check_id}: {check.detail}")
    return 0 if verdict.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
