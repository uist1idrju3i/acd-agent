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
from acd.pipeline.lane_plan import build_lane_plan
from acd.schema import DesignGraph, OrderPolicy, OrderTotalDocument


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


def _repository_relative_path(path: Path, repository: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise ValueError(f"path is outside repository: {path}") from exc


def authoritative_commands(
    *,
    repository: Path,
    design_graph_path: Path,
    out_root: Path,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    graph = DesignGraph.model_validate_json(
        design_graph_path.read_text(encoding="utf-8")
    )
    plan = build_lane_plan(graph.graph_id, out_root)
    board_output = plan.stage("board-pipeline").output_path
    enclosure_output = plan.stage("enclosure-pipeline").output_path
    if board_output is None or enclosure_output is None:
        raise ValueError("authoritative lane output path is undeclared")
    board_output_relative = _repository_relative_path(board_output, repository)
    enclosure_output_relative = _repository_relative_path(
        enclosure_output, repository
    )
    fixture_relative = _repository_relative_path(
        design_graph_path.parent, repository
    )
    return (
        (
            "uv run python scripts/run_gd1_pipeline.py "
            f"--fixture {fixture_relative} --out {board_output_relative}",
            (f"{board_output_relative}/evidence-electrical.json",),
        ),
        (
            "uv run python scripts/run_enclosure_pipeline.py "
            f"--fixture {fixture_relative} --out {enclosure_output_relative}",
            (f"{enclosure_output_relative}/evidence-mechanical.json",),
        ),
    )


def _rerun_authoritative(
    *,
    repository: Path,
    image: str,
    design_graph_path: Path,
    out_root: Path,
) -> None:
    try:
        commands = authoritative_commands(
            repository=repository,
            design_graph_path=design_graph_path,
            out_root=out_root,
        )
    except (OSError, ValueError) as exc:
        raise PreOrderGateError(
            f"could not resolve authoritative lane outputs: {exc}"
        ) from exc
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
    parser.add_argument("--design-graph", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=Path("out"))
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
            design_graph_path = args.design_graph
            if not design_graph_path.is_absolute():
                design_graph_path = repository / design_graph_path
            out_root = args.out_root
            if not out_root.is_absolute():
                out_root = repository / out_root
            _rerun_authoritative(
                repository=repository,
                image=args.image,
                design_graph_path=design_graph_path,
                out_root=out_root,
            )
        design_graph_path = args.design_graph
        if not design_graph_path.is_absolute():
            design_graph_path = repository / design_graph_path
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
            design_graph_path=design_graph_path,
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
