"""Derive order-scope.json and a quote request declaration from a fixture."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from acd.core.manufacturing.order_scope_derivation import (
    OrderScopeDerivationError,
    build_quote_request,
    derive_order_scope,
)


def _parser() -> argparse.ArgumentParser:
    """Build the order-scope derivation command-line parser."""
    parser = argparse.ArgumentParser(
        description="Derive order-scope.json from a design fixture deterministically."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="fixture directory with graph.json, rationale.json, order-terms.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="directory receiving order-scope.json and quote-request.json",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="fab profile registry path (default: repository profiles/)",
    )
    return parser


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Derive the order scope and quote request; fail closed on errors."""
    args = _parser().parse_args(argv)
    try:
        scope = derive_order_scope(args.fixture, registry_path=args.registry)
        quote_request = build_quote_request(scope, fixture_dir=args.out_dir)
    except OrderScopeDerivationError as exc:
        print(f"order scope derivation failed: {exc}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    scope_path = args.out_dir / "order-scope.json"
    request_path = args.out_dir / "quote-request.json"
    _atomic_write_json(scope_path, scope.model_dump(mode="json"))
    _atomic_write_json(request_path, quote_request)
    print(scope_path)
    print(request_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
