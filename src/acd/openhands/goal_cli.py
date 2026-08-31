"""Run one bounded ACD goal loop whose pass side stays with L1 gates.

The loop steers a conversation toward an objective with an explicit iteration
bound. Completion is judged by the SDK goal judge, which is L2 steering only;
the reported pass side comes from deterministic Evidence records that must be
authoritative for the current graph revision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openhands.sdk import LLM

from acd.openhands.session.bootstrap import build_acd_conversation
from acd.openhands.session.gate_critic import AcdEvidenceRequirement, GateRequirement
from acd.openhands.session.goal_loop import (
    build_evidence_gate_evaluator,
    install_goal_interrupt,
    run_acd_goal,
    write_goal_result,
)
from acd.schema.evidence import Evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective", required=True, help="Bounded goal objective.")
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        type=Path,
        help=(
            "Evidence JSON path deciding the pass side. Repeatable; every record "
            "must be authoritative for the current graph revision."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/golden-design-1"),
        help="Fixture directory whose graph.json defines the current revision.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root from which plugin and prompt assets are loaded.",
    )
    parser.add_argument("--model", required=True, help="Agent LLM model name.")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Goal judge LLM model name; defaults to the agent model.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum goal iterations. The loop stops at this bound.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/goal-result.json"),
        help="Path of the L3 goal-result observation.",
    )
    parser.add_argument(
        "--rejection-summary",
        type=Path,
        default=None,
        help="Optional path of the L3 hook-rejection summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_iterations < 1:
        raise SystemExit("--max-iterations must be at least 1")
    graph_path = args.fixture / "graph.json"
    requirements: list[GateRequirement] = [
        AcdEvidenceRequirement(
            path=path,
            evidence_id=Evidence.model_validate_json(
                path.read_text(encoding="utf-8")
            ).evidence_id,
        )
        for path in args.evidence
    ]
    conversation = build_acd_conversation(
        args.repo_root,
        LLM(model=args.model, usage_id="acd-goal-agent"),
        requirements,
        design_graph_path=graph_path,
    )
    judge_llm = LLM(
        model=args.judge_model or args.model,
        usage_id="acd-goal-judge",
    )
    with install_goal_interrupt(conversation):
        result = run_acd_goal(
            conversation,
            args.objective,
            judge_llm,
            max_iterations=args.max_iterations,
            gate_evaluator=build_evidence_gate_evaluator(graph_path, args.evidence),
            rejection_summary_path=args.rejection_summary,
        )
    write_goal_result(result, args.out)
    print(
        json.dumps(
            {
                "ok": result.authoritative,
                "pass_evidence": False,
                "record_class": "L3",
                "goal_result": result.model_dump(mode="json"),
                "output_path": str(args.out),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.authoritative else 2


if __name__ == "__main__":
    raise SystemExit(main())
