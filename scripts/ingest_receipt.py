"""Ingest a manufacturing receipt and reconcile it with a shipment manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.receipt import (
    ReceiptReconciliationError,
    build_receipt_evidence,
    reconcile_files,
)
from acd.schema import ReconciliationReport, canonical_json_sha256


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    try:
        receipt, report, input_hash = reconcile_files(args.manifest, args.receipt)
        report_value = report.model_dump(mode="json")
        output_hash = canonical_json_sha256(report_value)
        _write_json(args.report, report_value)
        if report.status != "match":
            return 2
        evidence = build_receipt_evidence(
            receipt,
            report,
            input_hash=input_hash,
            output_hash=output_hash,
        )
        _write_json(args.evidence, evidence.model_dump(mode="json"))
        return 0
    except (OSError, ReceiptReconciliationError, ValueError) as exc:
        _write_json(
            args.report,
            ReconciliationReport(
                status="unknown",
                manifest_only_paths=[],
                receipt_only_paths=[],
                hash_mismatch_paths=[],
                matched_count=0,
                manifest_hash="unknown",
                target_revision="unknown",
                manifest_status="unknown",
                manifest_unknown_keys=[],
                error=str(exc),
            ).model_dump(mode="json"),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
