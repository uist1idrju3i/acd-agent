from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/spice/gd1-power.json"


def test_netlist_only_is_deterministic(tmp_path: Path) -> None:
    outputs: list[bytes] = []
    for index in (1, 2):
        output = tmp_path / f"netlist-{index}.cir"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_spice_analysis.py"),
                "--graph",
                str(GRAPH_PATH),
                "--request",
                str(REQUEST_PATH),
                "--out",
                str(output),
                "--netlist-only",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_revision_mismatch_exits_two(tmp_path: Path) -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["revision"] = "r2"
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_spice_analysis.py"),
            "--graph",
            str(GRAPH_PATH),
            "--request",
            str(request),
            "--out",
            str(tmp_path / "result.json"),
            "--netlist-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2


def test_normal_mode_reports_tool_unavailable_or_result(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_spice_analysis.py"),
            "--graph",
            str(GRAPH_PATH),
            "--request",
            str(REQUEST_PATH),
            "--out",
            str(tmp_path / "result.json"),
            "--workdir",
            str(tmp_path / "work"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(
        (tmp_path / "result.json").read_text(encoding="utf-8")
    )
    assert completed.returncode in (0, 1)
    assert payload["authority"] == "estimate"
    assert payload["status"] in ("pass", "unknown", "fail")
