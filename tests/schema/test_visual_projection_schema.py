"""Tests for visual projection provenance contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from acd.schema import (
    VisualProjectionRecord,
    VisualProjectionSet,
)


def _projection(projection_id: str = "schematic") -> dict[str, object]:
    return {
        "projection_id": projection_id,
        "projection_type": "schematic_view",
        "domain": "electrical",
        "source_revision": "r8",
        "input_files": [
            {
                "path": "out/gd1/gd1.kicad_sch",
                "content_hash": "sha256:"
                + "1" * 64,
            }
        ],
        "renderer": {
            "renderer_type": "kicad-cli",
            "tool_name": "kicad-cli",
            "tool_version": "10.0.5",
        },
        "media_type": "image/svg+xml",
        "resolution": {
            "width": "29.9974mm",
            "height": "24.9936mm",
            "view_box": [0.0, 0.0, 29.9974, 24.9936],
        },
        "normalization_rule_id": "kicad-svg-title-v1",
        "normalization_rule_description": "Replace one volatile KiCad SVG title.",
        "image_hash": "sha256:" + "2" * 64,
        "generated_at": datetime(2026, 8, 19, tzinfo=UTC).isoformat(),
        "regeneration_check": {
            "status": "reproduced",
            "first_image_hash": "sha256:" + "2" * 64,
            "second_image_hash": "sha256:" + "2" * 64,
        },
        "image_path": "out/visual/schematic.svg",
    }


def _set(*projections: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "source_revision": "r8",
        "projections": list(projections),
        "canonical_hash": "unknown",
    }
    parsed = VisualProjectionSet.model_validate(value)
    value["canonical_hash"] = parsed.computed_canonical_hash()
    return value


def test_visual_projection_set_validates_and_self_hashes() -> None:
    value = VisualProjectionSet.model_validate(_set(_projection()))
    assert value.canonical_hash == value.computed_canonical_hash()
    assert value.pass_evidence is False


@pytest.mark.parametrize(
    ("mutation",),
    [
        ("renderer_version_unknown",),
        ("resolution_missing",),
        ("image_hash_unknown",),
        ("absolute_image_path",),
        ("pass_evidence_true",),
    ],
)
def test_visual_projection_rejects_fail_closed_values(mutation: str) -> None:
    value = _projection()
    if mutation == "renderer_version_unknown":
        renderer = value["renderer"]
        assert isinstance(renderer, dict)
        renderer["tool_version"] = "unknown"
    elif mutation == "resolution_missing":
        value.pop("resolution")
    elif mutation == "image_hash_unknown":
        value["image_hash"] = "unknown"
    elif mutation == "absolute_image_path":
        value["image_path"] = "/tmp/image.svg"
    else:
        value["pass_evidence"] = True
    with pytest.raises(ValidationError):
        VisualProjectionRecord.model_validate(value)


def test_visual_projection_set_rejects_duplicate_identifiers() -> None:
    with pytest.raises(ValidationError):
        VisualProjectionSet.model_validate(_set(_projection(), _projection()))


def test_visual_projection_set_rejects_mismatched_canonical_hash() -> None:
    value = _set(_projection())
    value["canonical_hash"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        VisualProjectionSet.model_validate(value)
