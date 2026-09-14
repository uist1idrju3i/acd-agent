"""Contract tests for idea-estimate schema (ADR-0049)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema.idea_estimate import (
    EstimateRange,
    EstimateTotals,
    IdeaEstimateCatalog,
    IdeaEstimateCatalogEntry,
    IdeaRoughEstimate,
)

REPOSITORY = Path(__file__).resolve().parents[2]
CATALOG_PATH = (
    REPOSITORY / "fixtures" / "idea" / "sample-usb-thermometer" / "estimate-catalog.json"
)


def test_estimate_range_requires_ordered_nonnegative() -> None:
    with pytest.raises(ValidationError):
        EstimateRange(min=10.0, max=5.0)
    with pytest.raises(ValidationError):
        EstimateRange(min=-1.0, max=5.0)


def test_catalog_rejects_duplicate_function_class() -> None:
    entry = IdeaEstimateCatalogEntry(
        function_class="temperature_sensor",
        typical_part="part",
        unit_cost_jpy=EstimateRange(min=1.0, max=2.0),
        power_mw=EstimateRange(min=1.0, max=2.0),
        footprint_mm2=10.0,
        source="fixture",
        checked_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        IdeaEstimateCatalog(
            catalog_id="c", entries=[entry, entry.model_copy()]
        )


def test_fixture_catalog_validates() -> None:
    catalog = IdeaEstimateCatalog.model_validate_json(
        CATALOG_PATH.read_text(encoding="utf-8")
    )
    assert len(catalog.entries) == 3


def test_rough_estimate_is_l3() -> None:
    body = json.loads(
        IdeaRoughEstimate(
            idea_id="idea.x",
            revision="r1",
            catalog_id="c",
            totals=EstimateTotals(
                cost_jpy=EstimateRange(min=0.0, max=0.0),
                power_mw=EstimateRange(min=0.0, max=0.0),
                footprint_mm2=0.0,
                covers_all_functions=False,
            ),
        ).model_dump_json()
    )
    assert body["artifact_kind"] == "idea_rough_estimate"
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert body["estimate"] is True
