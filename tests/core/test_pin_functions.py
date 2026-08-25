"""Tests for catalog-derived pin function projection."""

from __future__ import annotations

from acd.core.pin_functions import pin_function_attrs
from acd.schema.parts_catalog import PartCplOrientation

CATALOG_ID = "acd-parts-catalog-1"
CATALOG_HASH = "sha256:" + "3" * 64


def _orientation(**overrides: object) -> PartCplOrientation:
    values: dict[str, object] = {
        "basis": "component_part_number",
        "source_url": "https://example.invalid/part",
        "offset_deg": 0.0,
        "polarized": True,
        "pin_functions": ["1=GND", "2=VBUS"],
        "pin_aliases": ["VBUS=VCC"],
    }
    values.update(overrides)
    return PartCplOrientation.model_validate(values)


def test_catalog_pin_functions_are_projected_with_provenance() -> None:
    attrs = pin_function_attrs(_orientation(), CATALOG_ID, CATALOG_HASH)
    assert attrs["pin_function_source"] == "parts_catalog"
    assert attrs["pin_function_source_ref"] == f"{CATALOG_ID}:{CATALOG_HASH}"
    assert attrs["cpl_rotation_pin_functions"] == ["1=GND", "2=VBUS"]
    assert attrs["cpl_rotation_pin_aliases"] == ["VBUS=VCC"]


def test_missing_catalog_mapping_projects_nothing() -> None:
    assert pin_function_attrs(None, CATALOG_ID, CATALOG_HASH) == {}
    empty = _orientation(pin_functions=[], pin_aliases=[])
    assert pin_function_attrs(empty, CATALOG_ID, CATALOG_HASH) == {}


def test_alias_only_mapping_still_records_its_source() -> None:
    attrs = pin_function_attrs(
        _orientation(pin_functions=[]), CATALOG_ID, CATALOG_HASH
    )
    assert "cpl_rotation_pin_functions" not in attrs
    assert attrs["cpl_rotation_pin_aliases"] == ["VBUS=VCC"]
    assert attrs["pin_function_source"] == "parts_catalog"
