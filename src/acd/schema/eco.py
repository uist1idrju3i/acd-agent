"""Contracts for engineering-change records and close-gate results."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    WorkaroundId,
)
from acd.schema.salvage import GateRun

EcoId = Annotated[str, StringConstraints(pattern=r"^ECO-[0-9]{3,}$")]
EcoLane = Literal["electrical", "mechanical", "firmware"]
EcoReasonKind = Literal[
    "defect", "requirement", "obsolescence", "cost", "other"
]


class EcoReason(AcdModel):
    kind: EcoReasonKind
    ref: NonEmptyStr
    detail: NonEmptyStr


class EcoImpact(AcdModel):
    nodes_added: list[NodeId] = Field(default_factory=list[NodeId])
    nodes_removed: list[NodeId] = Field(default_factory=list[NodeId])
    nodes_changed: list[NodeId] = Field(default_factory=list[NodeId])
    lanes: list[EcoLane]

    @model_validator(mode="after")
    def validate_nodes_and_lanes(self) -> EcoImpact:
        node_lists = (
            self.nodes_added,
            self.nodes_removed,
            self.nodes_changed,
        )
        for label, values in zip(
            ("added", "removed", "changed"), node_lists, strict=True
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"impact nodes_{label} must be unique")
        if set(self.nodes_added) & set(self.nodes_removed):
            raise ValueError("impact added and removed nodes must be disjoint")
        if set(self.nodes_added) & set(self.nodes_changed):
            raise ValueError("impact added and changed nodes must be disjoint")
        if set(self.nodes_removed) & set(self.nodes_changed):
            raise ValueError("impact removed and changed nodes must be disjoint")
        if not self.lanes:
            raise ValueError("impact lanes must not be empty")
        if len(set(self.lanes)) != len(self.lanes):
            raise ValueError("impact lanes must be unique")
        return self


class ReverificationRequirement(AcdModel):
    gate: NonEmptyStr
    required_by: Literal["impact_lane", "declared"]


class HorizontalDisposition(AcdModel):
    defect_id: NonEmptyStr
    node_id: NodeId
    disposition: Literal["fixed_in_eco", "not_affected", "deferred"]
    reason: NonEmptyStr
    deferred_to: EcoId | None = None

    @model_validator(mode="after")
    def validate_deferred_target(self) -> HorizontalDisposition:
        if self.disposition == "deferred" and self.deferred_to is None:
            raise ValueError("deferred disposition requires deferred_to")
        if self.disposition != "deferred" and self.deferred_to is not None:
            raise ValueError(
                "non-deferred disposition must not declare deferred_to"
            )
        return self


class EcoRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["eco"] = "eco"
    pass_evidence: Literal[False] = False
    eco_id: EcoId
    title: NonEmptyStr
    graph_id: NonEmptyStr
    from_revision: Revision
    to_revision: Revision
    reasons: list[EcoReason]
    impact: EcoImpact
    reverification: list[ReverificationRequirement]
    horizontal_dispositions: list[HorizontalDisposition] = Field(
        default_factory=list[HorizontalDisposition]
    )
    retires_workaround_ids: list[WorkaroundId] = Field(
        default_factory=list[WorkaroundId]
    )

    @model_validator(mode="after")
    def validate_record(self) -> EcoRecord:
        if not self.reasons:
            raise ValueError("ECO reasons must not be empty")
        if "+" in self.from_revision or "+" in self.to_revision:
            raise ValueError("ECO revisions must be canonical")
        from_number = int(self.from_revision.removeprefix("r"))
        to_number = int(self.to_revision.removeprefix("r"))
        if to_number <= from_number:
            raise ValueError("ECO to_revision must be newer than from_revision")
        gates = [item.gate for item in self.reverification]
        if not gates:
            raise ValueError("ECO reverification must not be empty")
        if len(set(gates)) != len(gates):
            raise ValueError("ECO reverification gates must be unique")
        disposition_keys = [
            (item.defect_id, item.node_id)
            for item in self.horizontal_dispositions
        ]
        if len(set(disposition_keys)) != len(disposition_keys):
            raise ValueError(
                "ECO horizontal dispositions must be unique per defect and node"
            )
        for item in self.horizontal_dispositions:
            if item.deferred_to == self.eco_id:
                raise ValueError("ECO disposition cannot defer to itself")
        if len(set(self.retires_workaround_ids)) != len(
            self.retires_workaround_ids
        ):
            raise ValueError("ECO retired workaround IDs must be unique")
        return self


class EcoCheckResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["eco_check"] = "eco_check"
    pass_evidence: Literal[False] = False
    verdict: Literal["closable", "not_closable"]
    eco_id: EcoId
    from_revision: Revision
    to_revision: Revision
    impact_status: Literal["matched", "mismatched", "unknown"]
    gate_runs: list[GateRun]
    horizontal_status: Literal["complete", "incomplete", "unknown"]
    reasons: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    retires_workaround_ids: list[WorkaroundId] = Field(
        default_factory=list[WorkaroundId]
    )

    @model_validator(mode="after")
    def validate_verdict(self) -> EcoCheckResult:
        if self.verdict == "closable":
            if self.impact_status != "matched":
                raise ValueError("closable ECO requires matched impact")
            if any(
                run.status not in {"pass", "not_applicable"}
                for run in self.gate_runs
            ):
                raise ValueError("closable ECO requires passing gate runs")
            if self.horizontal_status != "complete":
                raise ValueError("closable ECO requires complete horizontal status")
            if self.reasons:
                raise ValueError("closable ECO must not have reasons")
        return self


class EcoDocument(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["eco_document"] = "eco_document"
    ecos: list[EcoRecord]

    @model_validator(mode="after")
    def validate_ecos(self) -> EcoDocument:
        eco_ids = [eco.eco_id for eco in self.ecos]
        if len(set(eco_ids)) != len(eco_ids):
            raise ValueError("ECO IDs must be unique")
        return self


__all__ = [
    "EcoCheckResult",
    "EcoDocument",
    "EcoId",
    "EcoImpact",
    "EcoLane",
    "EcoReason",
    "EcoReasonKind",
    "EcoRecord",
    "HorizontalDisposition",
    "ReverificationRequirement",
]
