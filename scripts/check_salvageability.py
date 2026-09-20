"""Run the deterministic salvageability gate for a workaround."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.manufacturing.rework_diff import (
    ReworkDiffError,
    load_rework_diff,
    write_derived_graph,
)
from acd.core.manufacturing.salvage_gate import SalvageGateError, evaluate_salvage
from acd.pipeline.gate_evidence import write_gate_evidence
from acd.schema.design_graph import DesignGraph
from acd.schema.rework_diff import ReworkDiff
from acd.schema.salvage import (
    GateRun,
    ReworkDfaDeclaration,
    SafetyApproval,
    SalvageGateResult,
)


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SalvageGateError(f"design graph is invalid: {path}: {exc}") from exc


def _write_result(out_dir: Path, result: SalvageGateResult) -> None:
    (out_dir / "salvage-gate.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    write_gate_evidence(
        out_dir,
        "salvage-gate.json",
        target_revision=result.derived_revision,
        gate="salvage_gate",
        status="pass" if result.verdict == "salvageable" else "fail",
        message=(
            "workaround is salvageable"
            if result.verdict == "salvageable"
            else (
                "constrained salvage is not a pass"
                if result.verdict == "constrained_salvage"
                else "workaround is not salvageable"
            )
        ),
        observation=result.model_dump(mode="json"),
    )


def _derivation_failure_result(
    diff: ReworkDiff, error: Exception
) -> SalvageGateResult:
    return SalvageGateResult(
        workaround_id=diff.workaround_id,
        graph_id=diff.graph_id,
        base_revision=diff.base_revision,
        derived_revision=diff.derived_revision,
        verdict="not_salvageable",
        gate_runs=[
            GateRun(
                gate="derivation",
                status="fail",
                source="computed",
                detail=str(error),
            )
        ],
        dfa_blockers=[],
        safety_boundary_touched=False,
        approval_status="not_required",
        degraded_functions=diff.degraded_functions,
        reasons=[str(error)],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--rework", type=Path, required=True)
    parser.add_argument("--dfa", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--erc-evidence", type=Path)
    parser.add_argument("--drc-evidence", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        graph = _load_graph(args.graph)
        loaded_diff = load_rework_diff(args.rework)
        dfa = ReworkDfaDeclaration.model_validate_json(
            args.dfa.read_text(encoding="utf-8")
        )
        approval: SafetyApproval | None = None
        if args.approval is not None:
            approval = SafetyApproval.model_validate_json(
                args.approval.read_text(encoding="utf-8")
            )
    except (OSError, ValueError, ReworkDiffError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        derived, result = evaluate_salvage(
            base_graph=graph,
            diff=loaded_diff.diff,
            dfa=dfa,
            approval=approval,
            fixture_dir=args.fixture_dir,
            external_evidence={
                name: path
                for name, path in (
                    ("erc", args.erc_evidence),
                    ("drc", args.drc_evidence),
                )
                if path is not None
            },
            output_dir=args.out_dir,
        )
    except SalvageGateError as exc:
        result = _derivation_failure_result(loaded_diff.diff, exc)
    else:
        write_derived_graph(derived, args.out_dir)

    _write_result(args.out_dir, result)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.verdict == "salvageable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
