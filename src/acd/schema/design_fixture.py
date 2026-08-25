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


class FixtureMechanicalOutlineSpec(AcdModel):
    """Declared board outline. Attributes are taken from the design input only."""

    node_id: NonEmptyStr | None = None
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class FixtureSilkTextSpec(AcdModel):
    """Declared silkscreen text. Placement resolvers may refine the attributes."""

    node_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    depends_on: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class FixtureSilkGraphicSpec(AcdModel):
    """Declared silkscreen graphic. Artwork sources stay in the design input."""

    node_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    depends_on: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class FixtureFirmwareStateSpec(AcdModel):
    node_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class FixtureFirmwareTransitionSpec(AcdModel):
    node_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class FixtureFirmwareSequenceStepSpec(AcdModel):
    node_id: NonEmptyStr
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class FixtureFirmwareModuleSpec(AcdModel):
    """Declared firmware module together with its declared state machine."""

    node_id: NonEmptyStr | None = None
    attrs: dict[str, AttrValue] = Field(default_factory=dict)
    states: list[FixtureFirmwareStateSpec] = Field(
        default_factory=list[FixtureFirmwareStateSpec]
    )
    transitions: list[FixtureFirmwareTransitionSpec] = Field(
        default_factory=list[FixtureFirmwareTransitionSpec]
    )
    sequence_steps: list[FixtureFirmwareSequenceStepSpec] = Field(
        default_factory=list[FixtureFirmwareSequenceStepSpec]
    )


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
    mechanical_outline: FixtureMechanicalOutlineSpec | None = None
    silk_texts: list[FixtureSilkTextSpec] = Field(
        default_factory=list[FixtureSilkTextSpec]
    )
    silk_graphics: list[FixtureSilkGraphicSpec] = Field(
        default_factory=list[FixtureSilkGraphicSpec]
    )
    firmware_module: FixtureFirmwareModuleSpec | None = None
    fab_profile_id: NonEmptyStr | None = None
    rationale_recorded_at: Timestamp | None = None


__all__ = [
    "DesignFixtureSpec",
    "FixtureComponentSpec",
    "FixtureCplOrientationEvidence",
    "FixtureFirmwareModuleSpec",
    "FixtureFirmwarePinSpec",
    "FixtureFirmwareSequenceStepSpec",
    "FixtureFirmwareStateSpec",
    "FixtureFirmwareTransitionSpec",
    "FixtureFunctionalBlockSpec",
    "FixtureMechanicalOutlineSpec",
    "FixtureNetSpec",
    "FixtureSilkGraphicSpec",
    "FixtureSilkTextSpec",
]
