"""Pydantic contracts for declared per-lane recovery from rejection."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion
from acd.schema.design_freedom import DesignFreedomDimensionId

RecoveryLaneId = Literal[
    "board-pipeline",
    "enclosure-pipeline",
    "firmware-pipeline",
    "silkscreen-resolve",
    "order-readiness",
]
RecoveryExplorer = Literal["board", "enclosure", "firmware", "none"]

RECOVERY_LANE_IDS = frozenset(
    {
        "board-pipeline",
        "enclosure-pipeline",
        "firmware-pipeline",
        "silkscreen-resolve",
        "order-readiness",
    }
)


class LaneRecoveryDeclaration(AcdModel):
    """Declared recovery capability of one deterministic lane."""

    lane_id: RecoveryLaneId
    title: NonEmptyStr
    explorer: RecoveryExplorer
    recovery_dimensions: list[DesignFreedomDimensionId] = Field(
        default_factory=list[DesignFreedomDimensionId]
    )
    next_step_action: NonEmptyStr
    unsupported_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_declaration(self) -> LaneRecoveryDeclaration:
        if len(self.recovery_dimensions) != len(set(self.recovery_dimensions)):
            raise ValueError("recovery_dimensions entries must be unique")
        if self.explorer == "none":
            if self.recovery_dimensions:
                raise ValueError(
                    "a lane without an explorer must not declare recovery dimensions"
                )
            if self.unsupported_reason is None:
                raise ValueError(
                    "a lane without an explorer requires an unsupported_reason"
                )
            return self
        if not self.recovery_dimensions:
            raise ValueError("an explorable lane requires at least one recovery dimension")
        if self.unsupported_reason is not None:
            raise ValueError("unsupported_reason is forbidden for an explorable lane")
        return self


class LaneRecoveryDeclarationDocument(AcdModel):
    """The full declared recovery surface of the design loop."""

    schema_version: SchemaVersion
    declaration_id: NonEmptyStr
    lanes: list[LaneRecoveryDeclaration] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_canonical_lane_set(self) -> LaneRecoveryDeclarationDocument:
        ids = [lane.lane_id for lane in self.lanes]
        if len(ids) != len(set(ids)):
            raise ValueError("lane recovery lane_id values must be unique")
        declared = set(ids)
        if declared != set(RECOVERY_LANE_IDS):
            missing = sorted(RECOVERY_LANE_IDS - declared)
            unknown = sorted(declared - RECOVERY_LANE_IDS)
            details: list[str] = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            raise ValueError(
                "lane recovery lane set is invalid (" + "; ".join(details) + ")"
            )
        return self


__all__ = [
    "RECOVERY_LANE_IDS",
    "LaneRecoveryDeclaration",
    "LaneRecoveryDeclarationDocument",
    "RecoveryExplorer",
    "RecoveryLaneId",
]
