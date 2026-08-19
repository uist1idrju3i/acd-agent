"""Pin the measured GD1 silkscreen resolver output and documentation table."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "golden-design-1" / "graph.json"
DOCUMENT = ROOT / "docs" / "golden-design-1.md"

EXPECTED = {
    "RST": (26.325, 5.4),
    "BOOT": (2.3, 5.15),
    "D1": (9.1, 12.4),
    "USB": (8.075, 23.9),
    "DEV BOARD": (24.925, 16.9614905),
    "golden-design-1-r1": (8.95, 15.305683004),
}


def _coordinate(value: str) -> tuple[float, float]:
    match = re.fullmatch(r"\(([^,]+),\s*([^)]+)\)", value.strip())
    assert match is not None
    return float(match.group(1)), float(match.group(2))


def test_final_silkscreen_coordinates_are_pinned() -> None:
    graph = json.loads(FIXTURE.read_text(encoding="utf-8"))
    silk = {
        node["attrs"]["text"]: (
            float(node["attrs"]["x_mm"]),
            float(node["attrs"]["y_mm"]),
        )
        for node in graph["nodes"]
        if node["kind"] == "mechanical.silk_text"
    }
    assert set(silk) == set(EXPECTED)
    assert silk == EXPECTED

    document = DOCUMENT.read_text(encoding="utf-8")
    assert "現行resolverは\n`status=measured_pass`となり" in document
    for label, coordinate in EXPECTED.items():
        pattern = rf"\|\s*{re.escape(label)}\s*\|\s*[^|]+\|\s*`(\([^`]+\))`\s*\|"
        matches = re.findall(pattern, document)
        assert matches, f"documentation coordinate is missing: {label}"
        assert _coordinate(matches[0]) == coordinate
