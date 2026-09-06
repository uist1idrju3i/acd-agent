"""Tests for the GD1 reference inventory drift check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.verify_gd1_references import build_report, main

ROOT = Path(__file__).parents[2]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _entry(path: str, lines: int) -> dict[str, object]:
    return {"path": path, "purpose": "message_text", "reference_lines": lines, "note": "x"}


def _inventory(root: Path, entries: list[dict[str, object]]) -> Path:
    path = root / "contracts/gd1-reference-inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "record_class": "L3",
                "pass_evidence": False,
                "scan_roots": ["src/acd"],
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_repository_inventory_matches_source() -> None:
    report = build_report(ROOT, ROOT / "contracts/gd1-reference-inventory.json")
    assert report.status == "pass", report.model_dump()
    assert report.pass_evidence is False
    assert report.record_class == "L3"


def test_undeclared_reference_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "src/acd/new.py", 'DEFAULT = "fixtures/golden-design-1"\n')
    inventory = _inventory(tmp_path, [])
    report = build_report(tmp_path, inventory)
    assert report.status == "fail"
    assert report.undeclared == ["src/acd/new.py"]


def test_stale_entry_and_count_drift_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path, "src/acd/a.py", "# gd1\n# GD1 again\n")
    _write(tmp_path, "src/acd/tests/ignored.py", "# gd1\n")
    inventory = _inventory(
        tmp_path,
        [
            {
                "path": "src/acd/a.py",
                "purpose": "positive_control",
                "reference_lines": 1,
                "note": "x",
            },
            {
                "path": "src/acd/gone.py",
                "purpose": "message_text",
                "reference_lines": 1,
                "note": "x",
            },
        ],
    )
    report = build_report(tmp_path, inventory)
    assert report.status == "fail"
    assert report.stale == ["src/acd/gone.py"]
    assert report.count_drift == ["src/acd/a.py: declared 1, found 2"]


def test_check_exit_code_reflects_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "src/acd/a.py", "# gd1\n")
    inventory = _inventory(tmp_path, [])
    assert main(["--check", "--root", str(tmp_path), "--inventory", str(inventory)]) == 1
    assert "drift" in capsys.readouterr().err
    _inventory(
        tmp_path,
        [_entry("src/acd/a.py", 1)],
    )
    assert main(["--check", "--root", str(tmp_path), "--inventory", str(inventory)]) == 0
