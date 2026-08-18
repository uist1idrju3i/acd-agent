"""Tests for deterministic shipment receipt reconciliation."""

from __future__ import annotations

from pathlib import Path

from acd.core.receipt import (
    build_receipt_evidence,
    reconcile_files,
    reconcile_receipt,
)
from acd.schema import ReceiptRecord

ROOT = Path(__file__).parents[2]


def load_fixture(kind: str, name: str) -> dict[str, object]:
    import json

    return json.loads((ROOT / "fixtures/contracts" / kind / name).read_text())


def test_complete_receipt_reconciliation_builds_provisional_physical_evidence() -> None:
    manifest_path = ROOT / "fixtures/contracts/valid/fab-package-receipt.json"
    receipt_path = ROOT / "fixtures/contracts/valid/receipt.json"
    receipt, report, input_hash = reconcile_files(manifest_path, receipt_path)

    assert report.status == "match"
    assert report.matched_count == 2
    evidence = build_receipt_evidence(
        receipt,
        report,
        input_hash=input_hash,
        output_hash=report.manifest_hash,
    )
    assert evidence.measurements[0].value == 2
    assert evidence.supports_pass("r12")
    assert not evidence.supports_authoritative_pass("r12")
    assert evidence.canonical_hash() == evidence.canonical_hash()


def test_reconciliation_reports_missing_extra_and_hash_mismatch_paths() -> None:
    manifest = load_fixture("valid", "fab-package-receipt.json")
    receipt = ReceiptRecord.model_validate(load_fixture("valid", "receipt.json"))
    receipt_data = receipt.model_dump(mode="json")
    receipt_data["received_items"] = [
        {
            "path": "artifacts/board.zip",
            "content_hash": (
                "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            ),
        },
        {
            "path": "artifacts/extra.bin",
            "content_hash": (
                "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            ),
        },
    ]
    altered_receipt = ReceiptRecord.model_validate(receipt_data)
    report = reconcile_receipt(
        manifest,
        altered_receipt,
        manifest_hash=receipt.manifest_reference.manifest_hash,
    )

    assert report.status == "mismatch"
    assert report.manifest_only_paths == ["artifacts/assembly.csv"]
    assert report.receipt_only_paths == ["artifacts/extra.bin"]
    assert report.hash_mismatch_paths == ["artifacts/board.zip"]


def test_manifest_revision_and_unknowns_are_fail_closed() -> None:
    manifest = load_fixture("valid", "fab-package-receipt.json")
    receipt = ReceiptRecord.model_validate(load_fixture("valid", "receipt.json"))
    mismatch = dict(manifest)
    mismatch["target_revision"] = "r13"
    mismatch_report = reconcile_receipt(
        mismatch,
        receipt,
        manifest_hash=receipt.manifest_reference.manifest_hash,
    )
    assert mismatch_report.status == "unknown"

    unknown_manifest = dict(manifest)
    unknown_manifest["unknowns"] = {"price": "unknown"}
    unknown_report = reconcile_receipt(
        unknown_manifest,
        receipt,
        manifest_hash=receipt.manifest_reference.manifest_hash,
    )
    assert unknown_report.status == "unknown"


def test_receipt_missing_artifact_is_a_mismatch() -> None:
    manifest = load_fixture("valid", "fab-package-receipt.json")
    receipt = ReceiptRecord.model_validate(
        load_fixture("invalid", "receipt-missing-item.json")
    )
    report = reconcile_receipt(
        manifest,
        receipt,
        manifest_hash=receipt.manifest_reference.manifest_hash,
    )
    assert report.status == "mismatch"
    assert report.manifest_only_paths == ["artifacts/assembly.csv"]
