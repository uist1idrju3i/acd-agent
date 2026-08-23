#!/usr/bin/env python3
"""Fetch a quote through a declared deterministic provider boundary."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

from acd.core.quote import QuoteReadError, quote_provider_from_config


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("quote provider config must be an object")
        typed_config = cast(dict[str, object], config)
        provider = quote_provider_from_config(typed_config)
        record = provider.fetch(
            configuration=typed_config,
            evaluated_at=_timestamp(args.evaluated_at),
            target_revision=args.target_revision,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError, QuoteReadError) as exc:
        print(f"quote fetch refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"provider": provider.provider_id, "quote": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
