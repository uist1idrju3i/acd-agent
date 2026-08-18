"""Deterministic reconciliation of shipment manifests and receipt records."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from acd.schema.common import Revision, Sha256
from acd.schema.evidence import MeasuredQuantity, MeasurementInstrument, PhysicalEvidence
from acd.schema.receipt import ReceiptRecord, ReconciliationReport
from acd.schema.tool_envelope import ToolEnvelope


class ReceiptReconciliationError(ValueError):
    """Raised when receipt reconciliation cannot produce a fail-closed result."""


def canonical_hash_for(value: object) -> Sha256:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _parse_sha256(value: object) -> Sha256:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("value is not a SHA-256 digest")
    return value


def _parse_revision(value: object) -> Revision:
    if not isinstance(value, str) or re.fullmatch(r"r[0-9]+", value) is None:
        raise ValueError("value is not a revision")
    return value


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReceiptReconciliationError(f"could not parse JSON: {path}") from exc


def _manifest_files(manifest: Mapping[str, Any]) -> dict[str, Sha256]:
    required = (
        "schema_version",
        "status",
        "target_revision",
        "fab_profile",
        "files",
        "gates",
        "unknowns",
    )
    if any(key not in manifest for key in required):
        raise ReceiptReconciliationError("manifest is missing required fields")
    if not isinstance(manifest["schema_version"], str) or not isinstance(manifest["status"], str):
        raise ReceiptReconciliationError("manifest schema_version and status must be strings")
    try:
        _parse_revision(manifest["target_revision"])
    except ValueError as exc:
        raise ReceiptReconciliationError("manifest target_revision is invalid") from exc
    if not isinstance(manifest["fab_profile"], dict) or not isinstance(manifest["gates"], dict):
        raise ReceiptReconciliationError("manifest fab_profile and gates must be objects")
    unknowns = manifest["unknowns"]
    if not isinstance(unknowns, dict):
        raise ReceiptReconciliationError("manifest unknowns must be an object")
    if unknowns:
        raise ReceiptReconciliationError("manifest contains unknowns")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ReceiptReconciliationError("manifest files must be a non-empty array")
    result: dict[str, Sha256] = {}
    for item_value in cast(list[object], files):
        if not isinstance(item_value, dict):
            raise ReceiptReconciliationError("manifest file entries must be objects")
        item = cast(dict[str, object], item_value)
        path = item.get("path")
        content_hash = item.get("content_hash")
        if not isinstance(path, str) or not path.strip():
            raise ReceiptReconciliationError("manifest file path is missing")
        if path.startswith("/") or path == ".." or path.startswith("../"):
            raise ReceiptReconciliationError("manifest file path must be relative")
        try:
            digest = _parse_sha256(content_hash)
        except ValueError as exc:
            raise ReceiptReconciliationError("manifest file content_hash is invalid") from exc
        if path in result:
            raise ReceiptReconciliationError("manifest file paths must be unique")
        result[path] = digest
    return result


def reconcile_receipt(
    manifest: Mapping[str, Any],
    receipt: ReceiptRecord,
    *,
    manifest_hash: Sha256,
) -> ReconciliationReport:
    """Reconcile a validated receipt against a manifest mapping."""
    unknown_target = receipt.manifest_reference.target_revision
    try:
        manifest_revision = _parse_revision(manifest.get("target_revision"))
    except ValueError:
        return ReconciliationReport(
            status="unknown",
            manifest_only_paths=[],
            receipt_only_paths=[],
            hash_mismatch_paths=[],
            matched_count=0,
            manifest_hash=manifest_hash,
            target_revision=unknown_target,
            error="manifest target_revision is invalid",
        )
    if manifest_hash != receipt.manifest_reference.manifest_hash:
        return ReconciliationReport(
            status="unknown",
            manifest_only_paths=[],
            receipt_only_paths=[],
            hash_mismatch_paths=[],
            matched_count=0,
            manifest_hash=manifest_hash,
            target_revision=manifest_revision,
            error="manifest hash does not match receipt declaration",
        )
    if manifest_revision != receipt.manifest_reference.target_revision:
        return ReconciliationReport(
            status="unknown",
            manifest_only_paths=[],
            receipt_only_paths=[],
            hash_mismatch_paths=[],
            matched_count=0,
            manifest_hash=manifest_hash,
            target_revision=manifest_revision,
            error="manifest and receipt revisions do not match",
        )
    try:
        manifest_files = _manifest_files(manifest)
    except ReceiptReconciliationError as exc:
        return ReconciliationReport(
            status="unknown",
            manifest_only_paths=[],
            receipt_only_paths=[],
            hash_mismatch_paths=[],
            matched_count=0,
            manifest_hash=manifest_hash,
            target_revision=manifest_revision,
            error=str(exc),
        )
    receipt_files = {item.path: item.content_hash for item in receipt.received_items}
    manifest_only = sorted(set(manifest_files) - set(receipt_files))
    receipt_only = sorted(set(receipt_files) - set(manifest_files))
    hash_mismatch = sorted(
        path
        for path in set(manifest_files) & set(receipt_files)
        if manifest_files[path] != receipt_files[path]
    )
    matched_count = sum(
        manifest_files[path] == receipt_files[path]
        for path in set(manifest_files) & set(receipt_files)
    )
    status = "match" if not manifest_only and not receipt_only and not hash_mismatch else "mismatch"
    return ReconciliationReport(
        status=status,
        manifest_only_paths=manifest_only,
        receipt_only_paths=receipt_only,
        hash_mismatch_paths=hash_mismatch,
        matched_count=matched_count,
        manifest_hash=manifest_hash,
        target_revision=manifest_revision,
    )


def build_receipt_evidence(
    receipt: ReceiptRecord,
    report: ReconciliationReport,
    *,
    input_hash: Sha256,
    output_hash: Sha256,
) -> PhysicalEvidence:
    """Build measured physical Evidence only from a complete reconciliation."""
    if report.status != "match":
        raise ReceiptReconciliationError("only a complete reconciliation can create Evidence")
    revision = report.target_revision
    measurement = MeasuredQuantity(
        name="matched_artifact_count",
        unit="count",
        value=report.matched_count,
        expected_min=report.matched_count,
        expected_max=report.matched_count,
        tolerance=0,
    )
    envelope = ToolEnvelope(
        tool_name="acd-receipt-ingestion",
        tool_version="0.1",
        format_version="0.1",
        config_hash=canonical_hash_for({"tool": "acd-receipt-ingestion", "version": "0.1"}),
        input_hash=input_hash,
        output_hash=output_hash,
        execution_env="python-3.12; deterministic receipt reconciliation",
        execution_context="host",
        measurement_conditions="shipment manifest and receipt record reconciliation",
        convergence_state="not_applicable",
        target_revision=revision,
        started_at=receipt.sent_at,
        finished_at=receipt.received_at,
    )
    return PhysicalEvidence(
        evidence_id=f"evidence.receipt.{receipt.receipt_id}",
        target_revision=revision,
        status="valid",
        envelope=envelope,
        claims=[],
        created_at=receipt.recorded_at,
        measurement_class="measured",
        instrument=MeasurementInstrument(
            instrument_name="receipt-reconciliation",
            instrument_version="0.1",
            fixture_id=receipt.manifest_reference.manifest_path,
            operator=receipt.supplier_name,
        ),
        acquired_at=receipt.received_at,
        measurements=[measurement],
    )


def reconcile_files(
    manifest_path: Path,
    receipt_path: Path,
) -> tuple[ReceiptRecord, ReconciliationReport, Sha256]:
    """Load and reconcile manifest and receipt files deterministically."""
    manifest_value = _load_json(manifest_path)
    if not isinstance(manifest_value, dict):
        raise ReceiptReconciliationError("manifest root must be an object")
    receipt_value = _load_json(receipt_path)
    try:
        receipt = ReceiptRecord.model_validate(receipt_value)
    except Exception as exc:
        raise ReceiptReconciliationError("receipt record is invalid") from exc
    manifest_hash = canonical_hash_for(cast(dict[str, object], manifest_value))
    report = reconcile_receipt(
        cast(Mapping[str, Any], manifest_value),
        receipt,
        manifest_hash=manifest_hash,
    )
    input_hash = canonical_hash_for(
        {
            "manifest": cast(dict[str, object], manifest_value),
            "receipt": receipt.model_dump(mode="json"),
        }
    )
    return receipt, report, input_hash
