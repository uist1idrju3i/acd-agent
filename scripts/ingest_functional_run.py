"""Ingest and evaluate a deterministic firmware functional-run record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.firmware import FunctionalRunError, load_and_evaluate_functional_run
from acd.schema import FunctionalCheckReport, FunctionalRunReport


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fallback_report(error: str) -> FunctionalRunReport:
    unknown = FunctionalCheckReport(status="unknown", reason=error)
    return FunctionalRunReport(
        status="unknown",
        run_id="unknown",
        target_revision="unknown",
        input_hash="unknown",
        build=unknown,
        flash=unknown,
        led=unknown,
        serial=unknown,
        error=error,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--logs-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    try:
        _run, report, evidences = load_and_evaluate_functional_run(
            args.run,
            args.logs_dir,
        )
    except (OSError, FunctionalRunError, ValueError) as exc:
        _write_json(args.report, _fallback_report(str(exc)).model_dump(mode="json"))
        return 2

    _write_json(args.report, report.model_dump(mode="json"))
    for name, evidence in evidences.items():
        _write_json(
            args.evidence_dir / f"{name}.json",
            evidence.model_dump(mode="json"),
        )
    return 0 if report.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
