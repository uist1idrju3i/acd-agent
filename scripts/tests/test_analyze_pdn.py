from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/pdn/gd1-power.json"
BOARD_PATH = ROOT / "examples/sensor-node-20260820/board/routed/gd1.kicad_pcb"


def test_cli_output_is_deterministic(tmp_path: Path) -> None:
    outputs: list[tuple[bytes, bytes]] = []
    for index in (1, 2):
        output = tmp_path / f"result-{index}.json"
        markdown = tmp_path / f"result-{index}.md"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/analyze_pdn.py"),
                "--graph",
                str(GRAPH_PATH),
                "--request",
                str(REQUEST_PATH),
                "--board",
                str(BOARD_PATH),
                "--out",
                str(output),
                "--out-md",
                str(markdown),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert outputs == [] or outputs[-1][0] == output.read_bytes()
        outputs.append((output.read_bytes(), markdown.read_bytes()))


def test_cli_unknown_net_exits_two(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    payload = REQUEST_PATH.read_text(encoding="utf-8").replace("VBUS_5V", "UNKNOWN_NET")
    request.write_text(payload, encoding="utf-8")
    output = tmp_path / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/analyze_pdn.py"),
            "--graph",
            str(GRAPH_PATH),
            "--request",
            str(request),
            "--board",
            str(BOARD_PATH),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()
