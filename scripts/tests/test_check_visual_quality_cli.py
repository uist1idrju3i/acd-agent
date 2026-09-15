from __future__ import annotations

import json
from pathlib import Path

from scripts import check_visual_quality
from scripts.tests.cli_runner import run_main


def test_check_visual_quality_cli_exit_codes(
    capsys, tmp_path: Path
) -> None:
    svg = tmp_path / "input.svg"
    out = tmp_path / "report.json"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 25">'
        '<text font-size="16" x="1" y="20">x</text></svg>',
        encoding="utf-8",
    )
    result = run_main(
        capsys,
        check_visual_quality.main,
        "--svg",
        str(svg),
        "--out",
        str(out),
    )
    assert result.returncode == 1
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "fail"


def test_check_visual_quality_cli_malformed_input(
    capsys, tmp_path: Path
) -> None:
    svg = tmp_path / "input.svg"
    out = tmp_path / "report.json"
    svg.write_text("<svg", encoding="utf-8")
    result = run_main(
        capsys,
        check_visual_quality.main,
        "--svg",
        str(svg),
        "--out",
        str(out),
    )
    assert result.returncode == 2
