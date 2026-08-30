"""Canonical order policy contract and pre-order gate result."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
    canonical_sha256,
    contains_unknown,
)
from acd.schema.quote import QuoteAmount

EvidenceLane = Literal["electrical", "mechanical"]


class OrderPolicy(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    transmission_commands: list[NonEmptyStr] = Field(min_length=1)
    artifact_paths: list[NonEmptyStr] = Field(min_length=1)
    order_commands: list[NonEmptyStr] = Field(min_length=1)
    evidence_paths: NonEmptyStr
    design_graph_roots: list[NonEmptyStr] = Field(min_length=1)
    required_evidence_lanes: list[EvidenceLane] = Field(min_length=2)
    order_total_limit: QuoteAmount

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("order policy must not contain unknown")
        for name, values in (
            ("transmission_commands", self.transmission_commands),
            ("artifact_paths", self.artifact_paths),
            ("order_commands", self.order_commands),
            ("design_graph_roots", self.design_graph_roots),
            ("required_evidence_lanes", self.required_evidence_lanes),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"order policy {name} entries must be unique")
        for root in self.design_graph_roots:
            if (
                root.startswith("/")
                or root.endswith("/")
                or "\\" in root
                or ".." in root.split("/")
                or any(not part for part in root.split("/"))
            ):
                raise ValueError(
                    "order policy design_graph_roots must be relative POSIX paths"
                )
        return self


def validate_order_policy_for_graph(policy: OrderPolicy, graph_id: str) -> None:
    """Validate graph-specific Evidence coverage at a graph-aware boundary."""
    required = required_order_evidence_ids(graph_id)
    declared = resolve_required_evidence_ids(policy, graph_id)
    if not required.issubset(declared):
        missing = ", ".join(sorted(required - declared))
        raise ValueError(f"order policy is missing required Evidence: {missing}")


def resolve_required_evidence_ids(
    policy: OrderPolicy, graph_id: str
) -> frozenset[str]:
    """Resolve declared Evidence lanes to graph-scoped Evidence identifiers."""
    from acd.core.naming import evidence_id

    return frozenset(
        evidence_id(graph_id, lane) for lane in policy.required_evidence_lanes
    )


def required_order_evidence_ids(graph_id: str) -> frozenset[str]:
    """Return the graph-scoped Evidence anchors required before ordering."""
    from acd.core.naming import required_evidence_ids

    return required_evidence_ids(graph_id)


__all__ = [
    "EvidenceLane",
    "EvidenceReference",
    "OrderPolicy",
    "PreOrderGateRecord",
    "PreOrderGateRecordBody",
    "required_order_evidence_ids",
    "resolve_required_evidence_ids",
    "validate_order_policy_for_graph",
]


class EvidenceReference(AcdModel):
    evidence_id: NonEmptyStr
    canonical_hash: Sha256


class PreOrderGateRecordBody(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    target_revision: Revision
    total: QuoteAmount
    upper_limit: QuoteAmount
    breakdown_hash: Sha256
    evidence: list[EvidenceReference] = Field(min_length=2)
    policy_hash: Sha256
    evaluated_at: Timestamp

    @model_validator(mode="after")
    def validate_body(self) -> Self:
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("pre-order Evidence identifiers must be unique")
        return self


class PreOrderGateRecord(PreOrderGateRecordBody):
    authorization_hash: Sha256

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        body = PreOrderGateRecordBody.model_validate(
            self.model_dump(exclude={"authorization_hash"})
        )
        expected_hash = canonical_sha256(body)
        if self.authorization_hash != expected_hash:
            raise ValueError("pre-order authorization hash does not match record")
        return self

    @classmethod
    def create(
        cls,
        *,
        target_revision: Revision,
        total: QuoteAmount,
        upper_limit: QuoteAmount,
        breakdown_hash: Sha256,
        evidence: list[EvidenceReference],
        policy_hash: Sha256,
        evaluated_at: Timestamp,
    ) -> PreOrderGateRecord:
        body = PreOrderGateRecordBody(
            target_revision=target_revision,
            total=total,
            upper_limit=upper_limit,
            breakdown_hash=breakdown_hash,
            evidence=evidence,
            policy_hash=policy_hash,
            evaluated_at=evaluated_at,
        )
        authorization_hash = canonical_sha256(body)
        return cls.model_validate(
            {
                **body.model_dump(mode="python"),
                "authorization_hash": authorization_hash,
            }
        )
