"""CLI coverage for thermal and FEM estimate entrypoints."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_thermal_cli_writes_deterministic_json_and_markdown(tmp_path: Path) -> None:
    out = tmp_path / "thermal.json"
    out_md = tmp_path / "thermal.md"
    command = [
        sys.executable,
        "scripts/estimate_thermal.py",
        "--graph",
        "fixtures/golden-design-1/graph.json",
        "--request",
        "fixtures/thermal/gd1-ldo.json",
        "--environment",
        "fixtures/use-environment/gd1-indoor-usb.json",
        "--out",
        str(out),
        "--out-md",
        str(out_md),
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0
    assert second.returncode == 0
    assert out.read_text(encoding="utf-8") == out.read_text(encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "pass"
    assert "見積（estimate）" in out_md.read_text(encoding="utf-8")


def test_fem_cli_inp_only_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.inp"
    second = tmp_path / "second.inp"
    base = [
        sys.executable,
        "scripts/run_fem.py",
        "--graph",
        "fixtures/golden-design-1/graph.json",
        "--request",
        "fixtures/fem/gd1-drop.json",
        "--inp-only",
    ]
    assert subprocess.run([*base, "--out", str(first)], cwd=ROOT, check=False).returncode == 0
    assert subprocess.run([*base, "--out", str(second)], cwd=ROOT, check=False).returncode == 0
    assert first.read_bytes() == second.read_bytes()


def test_thermal_cli_revision_mismatch_exits_two(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    payload = json.loads(
        (ROOT / "fixtures/thermal/gd1-ldo.json").read_text(encoding="utf-8")
    )
    payload["revision"] = "r2"
    request.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/estimate_thermal.py",
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "--request",
            str(request),
            "--environment",
            "fixtures/use-environment/gd1-indoor-usb.json",
            "--out",
            str(tmp_path / "result.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
