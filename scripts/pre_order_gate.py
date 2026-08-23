#!/usr/bin/env python3
"""Evaluate the deterministic pre-order gate without performing an order."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from acd.core.order_total import (
    OrderTotalError,
    OrderTotalResult,
    order_total_result_from_document,
)
from acd.core.timestamps import parse_evaluated_at
from acd.openhands.order_gate import PreOrderGateError, evaluate_pre_order_gate
from acd.openhands.workspace import run_command_in_workspace
from acd.schema import OrderPolicy, OrderTotalDocument


def _load_order_total(path: Path) -> OrderTotalResult:
    try:
        document = OrderTotalDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return order_total_result_from_document(document)
    except (OSError, ValueError, OrderTotalError) as exc:
        raise ValueError(f"could not parse order total: {path}") from exc


def _load_policy(path: Path) -> OrderPolicy:
    try:
        return OrderPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not parse order policy: {path}") from exc


def _evaluated_at(value: str) -> datetime:
    return parse_evaluated_at(value)


def _rerun_authoritative(
    *,
    repository: Path,
    image: str,
) -> None:
    commands = (
        (
            "uv run python scripts/run_gd1_pipeline.py --out out/gd1",
            ("out/gd1/evidence-electrical.json",),
        ),
        (
            "uv run python scripts/run_gd1_enclosure_pipeline.py "
            "--out out/gd1-enclosure",
            ("out/gd1-enclosure/evidence-mechanical.json",),
        ),
    )
    for command, download_files in commands:
        result = run_command_in_workspace(
            image=image,
            command=command,
            repository=repository,
            download_files=download_files,
        )
        if result.exit_code != 0:
            raise PreOrderGateError(
                f"authoritative gate rerun failed with exit code {result.exit_code}"
            )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repository root"
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("plugins/acd/hooks/order-policy.json"),
    )
    parser.add_argument("--order-total", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append")
    parser.add_argument("--evaluated-at", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-only",
        action="store_true",
        help="check existing authoritative Evidence without rerunning gates",
    )
    mode.add_argument(
        "--rerun-authoritative",
        action="store_true",
        help="rerun both lanes in the digest-pinned DockerWorkspace before checking",
    )
    parser.add_argument(
        "--image",
        default=os.getenv("ACD_CONTAINER_IMAGE"),
        help="digest-resolvable server image for --rerun-authoritative",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    repository = args.repo_root.resolve()
    policy_path = args.policy
    if not policy_path.is_absolute():
        policy_path = repository / policy_path
    try:
        policy = _load_policy(policy_path)
        order_total_path = args.order_total
        if not order_total_path.is_absolute():
            order_total_path = repository / order_total_path
        order_total = _load_order_total(order_total_path)
        evaluated_at = _evaluated_at(args.evaluated_at)
        if args.rerun_authoritative:
            if not args.image:
                raise ValueError(
                    "--image or ACD_CONTAINER_IMAGE is required for authoritative rerun"
                )
            _rerun_authoritative(repository=repository, image=args.image)
        evidence_paths = args.evidence
        if evidence_paths is None:
            evidence_paths = sorted(
                repository.glob(policy.evidence_paths)
            )
        else:
            evidence_paths = [
                path if path.is_absolute() else repository / path
                for path in evidence_paths
            ]
        record = evaluate_pre_order_gate(
            repository=repository,
            policy=policy,
            order_total=order_total,
            evidence_paths=evidence_paths,
            evaluated_at=evaluated_at,
        )
    except (OSError, ValueError, PreOrderGateError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    serialized = record.model_dump_json(indent=2)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
