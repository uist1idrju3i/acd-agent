#!/usr/bin/env python3
"""Execute a fail-closed ACD order dry-run; real provider sending is disabled."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from acd.openhands.order_execution import (
    default_confirmation_policy,
    execute_order,
    load_order_hooks,
)
from acd.schema import PreOrderGateRecord


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("occurred-at must include a timezone")
    return parsed


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--package-hash", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--credential-reference", required=True)
    parser.add_argument("--occurred-at", required=True)
    parser.add_argument(
        "--hooks",
        type=Path,
        default=Path("plugins/acd/hooks/hooks.json"),
    )
    parser.add_argument(
        "--command",
        nargs="+",
        required=True,
        help="required local dry-run command; never a real provider command",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="refuse explicitly: real provider sending is not enabled",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        authorization = PreOrderGateRecord.model_validate_json(
            args.permit.read_text(encoding="utf-8")
        )
        hooks = load_order_hooks(args.hooks)
        result = execute_order(
            authorization=authorization,
            journal_path=args.journal,
            idempotency_key=args.idempotency_key,
            package_hash=args.package_hash,
            destination=args.destination,
            target_revision=args.target_revision,
            provider_credential_reference=args.credential_reference,
            confirmation_policy=default_confirmation_policy(),
            hook_config=hooks,
            occurred_at=_timestamp(args.occurred_at),
            execution_mode="real" if args.real else "dry_run",
            command=args.command,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"order execution refused: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "payload": result.payload.model_dump(mode="json"),
                "payload_hash": result.payload_hash,
                "planned": result.planned.model_dump(mode="json"),
                "result": result.result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
