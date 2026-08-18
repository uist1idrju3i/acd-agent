"""Contracts for manufacturing and assembly receipt ingestion."""

from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl, Field, field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
)

ReceiptParty = Literal["fab", "assembler"]
ReconciliationStatus = Literal["match", "mismatch", "unknown"]


def _validate_relative_path(value: str) -> str:
    path = value.strip()
    if not path or path.startswith("/") or path == ".." or path.startswith("../"):
        raise ValueError("path must be a non-empty relative path")
    return path


class ReceiptArtifact(AcdModel):
    path: NonEmptyStr
    content_hash: Sha256

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_relative_path(value)


class InspectionReportReference(AcdModel):
    report_id: NonEmptyStr
    source_uri: AnyUrl
    issued_at: Timestamp
    content_hash: Sha256


class ShipmentManifestReference(AcdModel):
    manifest_path: NonEmptyStr
    manifest_hash: HashOrUnknown
    target_revision: Revision | Literal["unknown"]

    @field_validator("manifest_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_relative_path(value)


class ReceiptRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    receipt_id: NonEmptyStr
    counterparty_type: ReceiptParty
    supplier_name: NonEmptyStr
    source_uri: AnyUrl
    received_items: list[ReceiptArtifact] = Field(min_length=1)
    inspection_reports: list[InspectionReportReference] = Field(min_length=1)
    manifest_reference: ShipmentManifestReference
    sent_at: Timestamp
    received_at: Timestamp
    recorded_at: Timestamp

    @model_validator(mode="after")
    def validate_receipt(self) -> ReceiptRecord:
        if not self.sent_at <= self.received_at <= self.recorded_at:
            raise ValueError(
                "receipt timestamps must satisfy sent_at <= received_at <= recorded_at"
            )
        paths = [item.path for item in self.received_items]
        if len(paths) != len(set(paths)):
            raise ValueError("received item paths must be unique")
        identifiers = [report.report_id for report in self.inspection_reports]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("inspection report identifiers must be unique")
        return self


class ReconciliationReport(AcdModel):
    status: ReconciliationStatus
    manifest_only_paths: list[NonEmptyStr]
    receipt_only_paths: list[NonEmptyStr]
    hash_mismatch_paths: list[NonEmptyStr]
    matched_count: int = Field(ge=0)
    manifest_hash: Sha256
    target_revision: Revision
    error: NonEmptyStr | None = None
