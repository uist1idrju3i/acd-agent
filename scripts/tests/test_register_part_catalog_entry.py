"""Tests for the parts-catalog registration CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import register_part_catalog_entry


def test_cli_dry_run_reports_success_without_writing(tmp_path: Path, capsys) -> None:
    root = Path(__file__).parents[2]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        (root / "contracts/parts-catalog.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    symbol = tmp_path / "symbol"
    footprint = tmp_path / "footprint"
    symbol.write_text("symbol", encoding="utf-8")
    footprint.write_text("footprint", encoding="utf-8")
    entry = {
        "part_number": "CLI-22K",
        "kind": "resistor",
        "value": "22k",
        "package": "R_0603_1608Metric",
        "library_ref": {
            "symbol": "Device:R",
            "symbol_file": str(symbol),
            "symbol_source": "test",
            "symbol_source_ref": "1",
            "symbol_sha256": "sha256:" + hashlib.sha256(symbol.read_bytes()).hexdigest(),
            "footprint": "Resistor_SMD:R_0603_1608Metric",
            "footprint_file": str(footprint),
            "footprint_source": "test",
            "footprint_source_ref": "1",
            "footprint_sha256": "sha256:" + hashlib.sha256(footprint.read_bytes()).hexdigest(),
        },
    }
    entry_path = tmp_path / "entry.json"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")

    assert register_part_catalog_entry.main(
        ["--entry", str(entry_path), "--catalog", str(catalog), "--dry-run"]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["written"] is False
    assert "CLI-22K" not in catalog.read_text(encoding="utf-8")
