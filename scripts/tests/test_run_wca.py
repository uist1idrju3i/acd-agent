from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/wca/gd1-request.json"
TABLE_PATH = ROOT / "fixtures/wca/gd1-tolerances.json"
ENVIRONMENT_PATH = ROOT / "fixtures/use-environment/gd1-indoor-usb.json"
SPICE_PATH = ROOT / "fixtures/wca/gd1-spice-result.json"


def _command(
    out: Path,
    out_md: Path,
    request: Path = REQUEST_PATH,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts/run_wca.py"),
        "--graph",
        str(GRAPH_PATH),
        "--request",
        str(request),
        "--tolerance-table",
        str(TABLE_PATH),
        "--environment",
        str(ENVIRONMENT_PATH),
        "--spice-result",
        str(SPICE_PATH),
        "--out",
        str(out),
        "--out-md",
        str(out_md),
    ]


def test_cli_outputs_deterministic_json_and_markdown(tmp_path: Path) -> None:
    first_json = tmp_path / "first.json"
    first_md = tmp_path / "first.md"
    second_json = tmp_path / "second.json"
    second_md = tmp_path / "second.md"
    first = subprocess.run(
        _command(first_json, first_md),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        _command(second_json, second_md),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0
    assert second.returncode == 0
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_md.read_bytes() == second_md.read_bytes()
    assert json.loads(first_json.read_text(encoding="utf-8"))["status"] == "pass"
    assert "見積（estimate）・発注権限なし" in first_md.read_text(
        encoding="utf-8"
    )


def test_cli_revision_mismatch_exits_two(tmp_path: Path) -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["revision"] = "r2"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    completed = subprocess.run(
        _command(
            tmp_path / "result.json",
            tmp_path / "result.md",
            request,
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
