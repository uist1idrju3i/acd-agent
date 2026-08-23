"""Measure and iteratively resolve GD1 silkscreen placements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.pipeline.silkscreen_resolve import resolve_silkscreen

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/golden-design-1"))
    parser.add_argument("--out", type=Path, default=Path("out/gd1-silkscreen-resolve"))
    parser.add_argument("--fab-profile", type=Path, default=None)
    parser.add_argument("--fab-profile-id", default=None)
    parser.add_argument("--max-iterations", type=int, default=5)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = resolve_silkscreen(
            args.fixture,
            args.out,
            args.fab_profile,
            args.max_iterations,
            args.fab_profile_id,
        )
    except Exception as exc:
        print(f"RESOLUTION FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
