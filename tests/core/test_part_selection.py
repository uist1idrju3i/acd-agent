"""Tests for deterministic local part selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.part_selection import PartSelectionError, select_part
from acd.schema import ComponentPartRequest, PartsCatalogDocument

CATALOG = Path("contracts/parts-catalog.json")


def test_catalog_selects_pinned_resistor() -> None:
    result = select_part(
        ComponentPartRequest(
            kind="resistor",
            value="4.7k",
            package="R_0603_1608Metric",
        ),
        CATALOG,
    )
    assert result.entry.part_number == "0603WAF4701T5E"
    assert result.pass_evidence is False
    assert result.catalog_hash.startswith("sha256:")


def test_catalog_missing_and_ambiguous_fail_closed(tmp_path: Path) -> None:
    request = ComponentPartRequest(
        kind="resistor",
        value="4.7k",
        package="R_0603_1608Metric",
    )
    with pytest.raises(PartSelectionError):
        select_part(request, tmp_path / "missing.json")
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    matching = next(
        entry for entry in data["entries"] if entry["value"] == "4.7k"
    )
    data["entries"].append(matching | {"part_number": "DUPLICATE"})
    path = tmp_path / "ambiguous.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PartSelectionError, match="ambiguous"):
        select_part(request, path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("basis", "untrusted"),
        ("offset_deg", "not-a-number"),
        ("evidence_revision", "unknown"),
    ),
)
def test_catalog_rejects_malformed_cpl_orientation(
    field: str,
    value: object,
) -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    orientation = next(
        entry["cpl_orientation"]
        for entry in data["entries"]
        if "cpl_orientation" in entry
    )
    orientation[field] = value
    with pytest.raises(ValueError):
        PartsCatalogDocument.model_validate(data)


def test_catalog_rejects_geometry_evidence_source_without_graph_placeholders() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    orientation = next(
        entry["cpl_orientation"]
        for entry in data["entries"]
        if entry.get("part_number") == "TYPE-C-31-M-12"
    )
    orientation["geometry_exception_source"] = "evidence/gd1-cpl-orientation/J1.json"
    with pytest.raises(ValueError, match="artifact_prefix"):
        PartsCatalogDocument.model_validate(data)
