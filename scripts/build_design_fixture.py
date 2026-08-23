"""Build an arbitrary design fixture from a JSON specification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.pipeline.fixture_builder import FixtureBuilderError, build_design_fixture
from acd.schema import DesignFixtureSpec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        spec = DesignFixtureSpec.model_validate(
            json.loads(args.spec.read_text(encoding="utf-8"))
        )
        graph = build_design_fixture(spec, args.out)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, FixtureBuilderError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": "written",
                "graph_id": graph.graph_id,
                "revision": graph.revision,
                "out": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
