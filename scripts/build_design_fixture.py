"""Build an arbitrary design fixture from a JSON specification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.lane_preflight import (
    missing_declaration_action,
    missing_declarations,
    run_lane_preflight,
)
from acd.pipeline.fixture_builder import FixtureBuilderError, build_design_fixture
from acd.schema import DesignFixtureSpec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "acknowledge dropping graph data that the design input does not "
            "declare; a difference report is written in either case"
        ),
    )
    args = parser.parse_args()
    try:
        spec = DesignFixtureSpec.model_validate(
            json.loads(args.spec.read_text(encoding="utf-8"))
        )
        graph = build_design_fixture(spec, args.out, overwrite=args.overwrite)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, FixtureBuilderError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    # Diagnostic L3 preflight: names the declarations the spec still lacks so
    # the design input can be completed before the loop stops at its entry.
    preflight = run_lane_preflight(graph)
    report: dict[str, object] = {
        "status": "written",
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "out": str(args.out),
        "lane_preflight_status": preflight.status,
    }
    if preflight.status != "declarations_complete":
        report["missing_declarations"] = [
            item.model_dump(mode="json") for item in missing_declarations(preflight)
        ]
        report["next_step_action"] = missing_declaration_action(preflight)
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
