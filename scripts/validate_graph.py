"""Canonical graph validation entrypoint.

This is the single deterministic entrypoint for validating a design graph and
its declaration set before running lanes. It parses the graph, validates the
requirement document, checks rationale coverage, and runs the diagnostic lane
preflight. All results fail closed: an unparsable or unavailable input is an
error, never a pass. A successful validation is not design success; lane gates
and authoritative Evidence remain the only pass authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.functional_blocks import load_functional_block_registry
from acd.core.lane_cli import (
    LEGACY_FIXTURE_FLAGS,
    LEGACY_OUT_FLAGS,
    add_legacy_flags,
)
from acd.core.lane_preflight import LANE_IDS, run_lane_preflight
from acd.core.rationale import check_rationale_coverage
from acd.core.requirements import validate_requirements
from acd.schema.design_graph import DesignGraph
from acd.schema.rationale import RationaleDocument
from acd.schema.requirement import RequirementDocument


def _load(path: Path, model: type[DesignGraph]) -> DesignGraph:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    add_legacy_flags(parser, LEGACY_FIXTURE_FLAGS, "--fixture")
    add_legacy_flags(parser, LEGACY_OUT_FLAGS, "--out")
    parser.add_argument(
        "--lane",
        action="append",
        choices=list(LANE_IDS),
        default=None,
        help="restrict the preflight to the given lanes (repeatable)",
    )
    args = parser.parse_args()
    fixture: Path = args.fixture
    try:
        graph = _load(fixture / "graph.json", DesignGraph)
        preflight = run_lane_preflight(
            graph, tuple(args.lane) if args.lane else None
        )
        requirements_path = fixture / "requirements.json"
        rationale_path = fixture / "rationale.json"
        requirements = RequirementDocument.model_validate_json(
            requirements_path.read_text(encoding="utf-8")
        )
        validate_requirements(requirements, graph, load_functional_block_registry())
        rationale = RationaleDocument.model_validate_json(
            rationale_path.read_text(encoding="utf-8")
        )
        coverage = check_rationale_coverage(graph, rationale)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    report = {
        "status": (
            "ok"
            if preflight.status == "ready" and coverage.status == "pass"
            else "incomplete"
        ),
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "rationale_coverage": coverage.model_dump(mode="json"),
        "lane_preflight": preflight.model_dump(mode="json"),
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
