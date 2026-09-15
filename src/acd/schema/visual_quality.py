"""Strict contracts for deterministic SVG readability observations."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator

from acd.schema.common import (
    AcdModel,
    NodeId,
    Revision,
    Sha256,
    canonical_json_sha256,
)

ReadabilityStatus = Literal["pass", "fail", "unknown"]
ReadabilityFindingCode = Literal[
    "font_size_missing",
    "text_oversized",
    "text_too_small",
    "text_overlap",
    "text_out_of_viewbox",
    "low_contrast",
    "unknown_color",
    "unresolved_transform",
    "unknown_viewbox",
    "malformed_svg",
    "unknown_font_size",
    "unknown_resolution",
]


def _finding_list() -> list[ReadabilityFinding]:
    return []


class ReadabilityPolicy(AcdModel):
    """Thresholds for the deterministic SVG readability analyzer."""

    max_text_ratio: float = Field(default=0.15, gt=0)
    min_text_px: float = Field(default=6.0, gt=0)
    max_overlap_ratio: float = Field(default=0.0, ge=0, le=1)
    min_contrast_ratio: float = Field(default=3.0, ge=1)
    default_px_per_unit: float | None = Field(default=4.0, gt=0)

    @field_validator(
        "max_text_ratio",
        "min_text_px",
        "max_overlap_ratio",
        "min_contrast_ratio",
        "default_px_per_unit",
    )
    @classmethod
    def validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("readability policy values must be finite")
        return value

    def policy_hash(self) -> Sha256:
        return canonical_json_sha256(self.model_dump(mode="json"))


class ReadabilityFinding(AcdModel):
    """One deterministic readability finding."""

    code: ReadabilityFindingCode
    element_id: str | None = None
    detail: str


class ReadabilityReport(AcdModel):
    """L2 steering-only readability result."""

    status: ReadabilityStatus
    authority: Literal["steering"] = "steering"
    findings: list[ReadabilityFinding] = Field(default_factory=_finding_list)
    text_count: int = Field(ge=0)
    viewbox: tuple[float, float, float, float] | None = None
    policy_hash: Sha256


class VisualReadabilityObservation(AcdModel):
    """Readability observation stored alongside the visual-review manifest."""

    projection_id: NodeId
    source_revision: Revision
    image_hash: Sha256
    readability: ReadabilityReport


class VisualReadabilityDocument(AcdModel):
    """Projection-set readability observations stored outside crosschecks."""

    artifact_kind: Literal["visual_readability_observations"] = (
        "visual_readability_observations"
    )
    pass_evidence: Literal[False] = False
    source_revision: Revision
    policy: ReadabilityPolicy
    observations: list[VisualReadabilityObservation] = Field(min_length=1)
    status: ReadabilityStatus
