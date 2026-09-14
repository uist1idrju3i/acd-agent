from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
PRICE_BOOK_PATH = ROOT / "fixtures/bom-cost/gd1-2026-09.json"
LIFECYCLE_PATH = ROOT / "fixtures/part-lifecycle/gd1-2026-09.json"


def test_cli_writes_json_and_deterministic_markdown(tmp_path: Path) -> None:
    outputs: list[tuple[bytes, bytes]] = []
    for index in (1, 2):
        output = tmp_path / f"result-{index}.json"
        markdown = tmp_path / f"result-{index}.md"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/estimate_bom_cost.py"),
                "--graph",
                str(GRAPH_PATH),
                "--price-book",
                str(PRICE_BOOK_PATH),
                "--lifecycle",
                str(LIFECYCLE_PATH),
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
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["authority"] == "estimate"
        assert "見積（estimate）・発注権限なし" in markdown.read_text(
            encoding="utf-8"
        )
        outputs.append((output.read_bytes(), markdown.read_bytes()))
    assert outputs[0] == outputs[1]
