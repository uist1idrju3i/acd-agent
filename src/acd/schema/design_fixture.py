"""Schema for deterministic arbitrary-design fixture generation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd.schema.common import AcdModel, NonEmptyStr, Revision, Timestamp
from acd.schema.design_graph import AttrValue
from acd.schema.parts_catalog import ComponentPartRequest
from acd.schema.requirement import RequirementRecord


class FixtureCplOrientationEvidence(AcdModel):
    evidence_at: Timestamp
    evidence_method: NonEmptyStr
    evidence_basis: Literal["estimated", "confirmed"]
    evidence_note: NonEmptyStr


class FixtureComponentSpec(AcdModel):
    refdes: NonEmptyStr
    library_ref: NonEmptyStr | None = None
    part_request: ComponentPartRequest | None = None
    cpl_orientation_evidence: FixtureCplOrientationEvidence | None = None
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    pads: dict[str, NonEmptyStr | None] = Field(default_factory=dict)


class FixtureNetSpec(AcdModel):
    net_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class FixtureFirmwarePinSpec(AcdModel):
    pin_id: NonEmptyStr
    net: NonEmptyStr
    gpio: int


class FixtureFunctionalBlockSpec(AcdModel):
    block_id: NonEmptyStr
    node_id: NonEmptyStr | None = None
    requirement_ids: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class DesignFixtureSpec(AcdModel):
    design_name: NonEmptyStr
    revision: Revision = "r1"
    graph_id: NonEmptyStr | None = None
    board_attrs: dict[str, AttrValue] = Field(default_factory=dict)
    components: list[FixtureComponentSpec] = Field(
        default_factory=list[FixtureComponentSpec]
    )
    nets: list[FixtureNetSpec] = Field(default_factory=list[FixtureNetSpec])
    firmware_pin_assignments: list[FixtureFirmwarePinSpec] = Field(
        default_factory=list[FixtureFirmwarePinSpec]
    )
    requirements: list[RequirementRecord] = Field(default_factory=list[RequirementRecord])
    functional_blocks: list[FixtureFunctionalBlockSpec] = Field(
        default_factory=list[FixtureFunctionalBlockSpec]
    )
    fab_profile_id: NonEmptyStr | None = None


__all__ = [
    "DesignFixtureSpec",
    "FixtureComponentSpec",
    "FixtureCplOrientationEvidence",
    "FixtureFirmwarePinSpec",
    "FixtureFunctionalBlockSpec",
    "FixtureNetSpec",
]
