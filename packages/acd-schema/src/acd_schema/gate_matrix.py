"""Gate matrix (mirrors ``schemas/gate-matrix.schema.json``)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd_schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)

GateKind = Literal[
    "erc",
    "drc",
    "fw_build",
    "fw_static_analysis",
    "fw_unit_test",
    "pin_net_consistency",
    "review_disposition",
    "safety_boundary",
]

GateStatus = Literal["pass", "fail", "stale", "not_run", "unknown"]


class Waiver(AcdModel):
    waiver_id: NonEmptyStr
    reason: NonEmptyStr
    target_revision: Revision
    expires_at: Timestamp


class Gate(AcdModel):
    gate_id: NonEmptyStr
    kind: GateKind
    status: GateStatus
    evidence_refs: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    waiver: Waiver | None = None


class GateMatrix(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    target_revision: Revision
    gates: list[Gate] = Field(default_factory=list[Gate])

    def verdict(self, now: Timestamp) -> Literal["pass", "fail"]:
        """Deterministic overall verdict: every gate must pass or hold a live waiver.

        Any stale, not_run, or unknown gate fails the matrix (fail-closed).
        """
        for gate in self.gates:
            if gate.status == "pass" and gate.evidence_refs:
                continue
            waiver = gate.waiver
            if (
                waiver is not None
                and waiver.target_revision == self.target_revision
                and waiver.expires_at > now
            ):
                continue
            return "fail"
        return "pass"
