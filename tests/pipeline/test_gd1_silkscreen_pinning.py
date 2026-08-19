"""Pin the measured GD1 silkscreen resolver output and documentation table."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import cast

from acd.pipeline.silkscreen_resolve import (  # pyright: ignore[reportMissingTypeStubs]
    resolve_silkscreen,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "golden-design-1" / "graph.json"
FIXTURE_DIR = FIXTURE.parent
DOCUMENT = ROOT / "docs" / "golden-design-1.md"
FAB_PROFILE = ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"

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


def _silkscreen_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    silk = {
        node["attrs"]["text"]: (
            float(node["attrs"]["x_mm"]),
            float(node["attrs"]["y_mm"]),
        )
        for node in graph["nodes"]
        if node["kind"] == "mechanical.silk_text"
    }
    return silk


def test_final_silkscreen_coordinates_are_pinned(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, fixture_dir)
    result = resolve_silkscreen(
        fixture_dir,
        tmp_path / "resolver-output",
        FAB_PROFILE,
    )
    assert result["status"] == "resolved"
    final = result["final"]
    assert isinstance(final, dict)
    context = cast(dict[str, object], final["context"])
    assert context["status"] == "measured_pass"

    silk = _silkscreen_coordinates(fixture_dir / "graph.json")
    assert set(silk) == set(EXPECTED)
    assert silk == EXPECTED

    document = DOCUMENT.read_text(encoding="utf-8")
    table_blocks = re.findall(r"(?:^\|.*\n?)+", document, flags=re.MULTILINE)
    final_tables = [
        block
        for block in table_blocks
        if all(
            re.search(rf"^\|\s*{re.escape(label)}\s*\|", block, flags=re.MULTILINE)
            for label in EXPECTED
        )
    ]
    assert len(final_tables) == 1
    section = final_tables[0]
    for label, coordinate in EXPECTED.items():
        pattern = rf"\|\s*{re.escape(label)}\s*\|\s*[^|]+\|\s*`(\([^`]+\))`\s*\|"
        matches = re.findall(pattern, section)
        assert len(matches) == 1, f"documentation coordinate is not unique: {label}"
        assert _coordinate(matches[0]) == coordinate
