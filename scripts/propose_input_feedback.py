#!/usr/bin/env python3
"""Create a deterministic, non-mutating proposal from physical Evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.feedback import propose_input_feedback
from acd.schema import (
    DesignGraph,
    FeedbackPolicy,
    FeedbackProposal,
    PhysicalEvidence,
    RationaleDocument,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _fallback_proposal(reason: str) -> FeedbackProposal:
    return FeedbackProposal(
        status="unknown",
        graph_id="unknown",
        revision="unknown",
        input_hash="unknown",
        output_hash="unknown",
        error=reason,
    )


def _evidence_paths(values: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        if value.is_dir():
            paths.extend(sorted(value.glob("*.json")))
        else:
            paths.append(value)
    return sorted(set(paths))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Propose non-mutating design-input feedback from physical Evidence"
    )
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--rationale", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        graph = DesignGraph.model_validate(_load_json(args.graph))
        rationale = RationaleDocument.model_validate(_load_json(args.rationale))
        policy = FeedbackPolicy.model_validate(_load_json(args.policy))
        evidences = [
            PhysicalEvidence.model_validate(_load_json(path))
            for path in _evidence_paths(args.evidence)
        ]
        proposal = propose_input_feedback(graph, rationale, evidences, policy)
    except Exception:
        proposal = _fallback_proposal("feedback input is invalid")
    _write_json(args.proposal, proposal.model_dump(mode="json"))
    return 0 if proposal.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
