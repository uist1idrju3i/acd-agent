"""Canonical order policy contract and pre-order gate result."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
    canonical_json_sha256,
    contains_unknown,
)
from acd.schema.quote import QuoteAmount

REQUIRED_ORDER_EVIDENCE_IDS = frozenset(
    {"evidence.gd1.electrical", "evidence.gd1.mechanical"}
)


class OrderPolicy(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    transmission_commands: list[NonEmptyStr] = Field(min_length=1)
    artifact_paths: list[NonEmptyStr] = Field(min_length=1)
    order_commands: list[NonEmptyStr] = Field(min_length=1)
    evidence_paths: NonEmptyStr
    design_graph_paths: list[NonEmptyStr] = Field(min_length=1)
    required_evidence_ids: list[NonEmptyStr] = Field(min_length=2)
    order_total_limit: QuoteAmount

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("order policy must not contain unknown")
        for name, values in (
            ("transmission_commands", self.transmission_commands),
            ("artifact_paths", self.artifact_paths),
            ("order_commands", self.order_commands),
            ("design_graph_paths", self.design_graph_paths),
            ("required_evidence_ids", self.required_evidence_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"order policy {name} entries must be unique")
        if not REQUIRED_ORDER_EVIDENCE_IDS.issubset(self.required_evidence_ids):
            raise ValueError(
                "order policy must require electrical and mechanical Evidence"
            )
        return self


class EvidenceReference(AcdModel):
    evidence_id: NonEmptyStr
    canonical_hash: Sha256


class PreOrderGateRecord(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    target_revision: Revision
    total: QuoteAmount
    upper_limit: QuoteAmount
    breakdown_hash: Sha256
    evidence: list[EvidenceReference] = Field(min_length=2)
    policy_hash: Sha256
    evaluated_at: Timestamp
    authorization_hash: Sha256

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("pre-order Evidence identifiers must be unique")
        expected_hash = canonical_json_sha256(
            self.model_dump(mode="json", exclude={"authorization_hash"})
        )
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
        data: dict[str, object] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "target_revision": target_revision,
            "total": total.model_dump(mode="json"),
            "upper_limit": upper_limit.model_dump(mode="json"),
            "breakdown_hash": breakdown_hash,
            "evidence": [
                item.model_dump(mode="json") for item in evidence
            ],
            "policy_hash": policy_hash,
            "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        }
        authorization_hash = canonical_json_sha256(data)
        return cls.model_validate(
            {**data, "authorization_hash": authorization_hash}
        )
