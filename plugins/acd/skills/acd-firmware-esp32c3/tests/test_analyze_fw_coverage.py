from __future__ import annotations

import json
from pathlib import Path

from analyze_fw_coverage import main


def _floor(path: Path) -> None:
    path.write_text('{"line_pct_min": 80}\n', encoding="utf-8")


def test_coverage_cli_below_floor_returns_one(tmp_path: Path) -> None:
    report = tmp_path / "gcovr.json"
    report.write_text(
        '{"files":[{"file":"a.c","line_total":10,"line_covered":5,'
        '"branch_total":0,"branch_covered":0}]}',
        encoding="utf-8",
    )
    floor = tmp_path / "floor.json"
    _floor(floor)
    out = tmp_path / "out.json"
    assert main(
        ["--gcovr-json", str(report), "--floor", str(floor), "--out", str(out)]
    ) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "fail"


def test_coverage_cli_missing_report_returns_one_unknown(tmp_path: Path) -> None:
    floor = tmp_path / "floor.json"
    _floor(floor)
    out = tmp_path / "out.json"
    assert main(
        [
            "--gcovr-json",
            str(tmp_path / "missing.json"),
            "--floor",
            str(floor),
            "--out",
            str(out),
        ]
    ) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "unknown"
