"""Minimal ACD event payloads (mirrors ``schemas/event-payload.schema.json``).

These payloads ride on the OpenHands SDK ``EventLog`` via ``acd_events``;
they are defined here so the wire contract stays SDK-independent.
Unknown kinds are rejected fail-closed at parse time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, TypeAdapter

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    IdempotencyKey,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)
from acd_schema.gate_matrix import GateStatus


class GateResultPayload(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    kind: Literal["gate_result"] = "gate_result"
    target_revision: Revision
    gate_id: NonEmptyStr
    status: GateStatus
    evidence_refs: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class ApprovalPayload(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    kind: Literal["approval"] = "approval"
    target_revision: Revision
    approval_id: NonEmptyStr
    subject: NonEmptyStr
    approved: bool


class CommitSideEffectReceiptPayload(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    kind: Literal["commit_side_effect_receipt"] = "commit_side_effect_receipt"
    target_revision: Revision
    receipt_ref: NonEmptyStr
    idempotency_key: IdempotencyKey


AcdEventPayload = GateResultPayload | ApprovalPayload | CommitSideEffectReceiptPayload

_PAYLOAD_ADAPTER: TypeAdapter[AcdEventPayload] = TypeAdapter(
    GateResultPayload | ApprovalPayload | CommitSideEffectReceiptPayload
)


def parse_event_payload(data: Mapping[str, object]) -> AcdEventPayload:
    """Parse an event payload, rejecting unknown kinds and fields (fail-closed)."""
    return _PAYLOAD_ADAPTER.validate_python(data)
