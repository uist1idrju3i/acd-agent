"""Validate and register one functional-block contract declaration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.functional_block_entry import register_functional_block_contract
from acd.core.functional_blocks import FunctionalBlockContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        required=True,
        help="FunctionalBlockContract JSON path or inline JSON object.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("contracts/functional-block-registry.json"),
        help="Functional-block registry path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing the registry.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = register_functional_block_contract(
            args.contract,
            args.registry,
            dry_run=args.dry_run,
        )
        payload = {"ok": True, **result.model_dump()}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (FunctionalBlockContractError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fail_closed": True,
                    "failure_reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
