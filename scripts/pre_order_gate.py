#!/usr/bin/env python3
"""Evaluate the deterministic pre-order gate without performing an order."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

from acd.core.order_total import (
    OrderSubtotal,
    OrderTotalResult,
    QuoteCanonicalHash,
)
from acd.openhands.order_gate import PreOrderGateError, evaluate_pre_order_gate
from acd.openhands.workspace import run_command_in_workspace
from acd.schema import OrderPolicy, QuoteAmount, QuoteCategory
from acd.schema.common import canonical_json_sha256

_CATEGORIES = frozenset(
    {"board", "components", "assembly", "mechanical", "shipping", "tax"}
)
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_PATTERN = re.compile(r"^r[0-9]+$")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _category(value: object) -> QuoteCategory:
    text = _text(value, "subtotal category")
    if text not in _CATEGORIES:
        raise ValueError(f"unknown subtotal category: {text}")
    return cast(QuoteCategory, text)


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{label} must be a sha256 hash")
    return text


def _load_order_total(path: Path) -> OrderTotalResult:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not parse order total: {path}") from exc
    value = _mapping(raw, "order total")
    expected_keys = {
        "subtotals",
        "total",
        "target_revision",
        "quote_hashes",
        "breakdown_hash",
    }
    if set(value) != expected_keys:
        raise ValueError("order total fields are incomplete or unexpected")
    raw_subtotals_value = value["subtotals"]
    raw_hashes_value = value["quote_hashes"]
    if not isinstance(raw_subtotals_value, list) or not isinstance(
        raw_hashes_value, list
    ):
        raise ValueError("order total arrays are invalid")
    raw_subtotals = cast(list[object], raw_subtotals_value)
    raw_hashes = cast(list[object], raw_hashes_value)
    subtotals = tuple(
        OrderSubtotal(
            category=_category(_mapping(item, "subtotal")["category"]),
            amount=QuoteAmount.model_validate(
                _mapping(item, "subtotal")["amount"]
            ),
        )
        for item in raw_subtotals
    )
    quote_hashes = tuple(
        QuoteCanonicalHash(
            quote_id=_text(
                _mapping(item, "quote hash")["quote_id"],
                "quote hash identifier",
            ),
            canonical_hash=_sha256(
                _mapping(item, "quote hash")["canonical_hash"],
                "quote canonical hash",
            ),
        )
        for item in raw_hashes
    )
    target_revision = _text(value["target_revision"], "order total revision")
    if _REVISION_PATTERN.fullmatch(target_revision) is None:
        raise ValueError("order total revision is invalid")
    breakdown_hash = _sha256(value["breakdown_hash"], "breakdown hash")
    total = QuoteAmount.model_validate(value["total"])
    categories = [item.category for item in subtotals]
    if len(categories) != len(set(categories)) or categories != sorted(categories):
        raise ValueError("order total subtotals must be unique and sorted")
    if any(
        item.amount.currency != total.currency
        or item.amount.minor_unit_digits != total.minor_unit_digits
        for item in subtotals
    ):
        raise ValueError("order subtotal currency does not match total")
    if sum(item.amount.amount_minor for item in subtotals) != total.amount_minor:
        raise ValueError("order subtotal does not match total")
    quote_ids = [item.quote_id for item in quote_hashes]
    if len(quote_ids) != len(set(quote_ids)) or quote_ids != sorted(quote_ids):
        raise ValueError("order quote hashes must be unique and sorted")
    expected_breakdown_hash = canonical_json_sha256(
        {
            "quote_hashes": [
                {
                    "canonical_hash": item.canonical_hash,
                    "quote_id": item.quote_id,
                }
                for item in quote_hashes
            ],
            "subtotals": [
                {
                    "amount": item.amount.model_dump(mode="json"),
                    "category": item.category,
                }
                for item in subtotals
            ],
            "target_revision": target_revision,
            "total": total.model_dump(mode="json"),
        }
    )
    if breakdown_hash != expected_breakdown_hash:
        raise ValueError("order total breakdown hash does not match contents")
    return OrderTotalResult(
        subtotals=subtotals,
        total=total,
        target_revision=target_revision,
        quote_hashes=quote_hashes,
        breakdown_hash=breakdown_hash,
    )


def _load_policy(path: Path) -> OrderPolicy:
    try:
        return OrderPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not parse order policy: {path}") from exc


def _evaluated_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("evaluated-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return parsed


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
