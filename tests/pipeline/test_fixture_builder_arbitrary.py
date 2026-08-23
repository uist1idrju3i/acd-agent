"""Arbitrary design fixture builder tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path

from acd.pipeline.fixture_builder import build_design_fixture
from acd.schema import (
    DesignFixtureSpec,
    FixtureComponentSpec,
    FixtureFunctionalBlockSpec,
    FixtureNetSpec,
    RequirementRecord,
)


def test_fixture_builder_is_deterministic(tmp_path: Path) -> None:
    spec = DesignFixtureSpec(
        design_name="demo",
        board_attrs={"width_mm": 30.0, "height_mm": 25.0},
        components=[
            FixtureComponentSpec(
                refdes="R1",
                attrs={"mpn": "RES-1K"},
                pads={"1": "net.led"},
            )
        ],
        nets=[FixtureNetSpec(net_id="net.led", attrs={"name": "LED"})],
        requirements=[RequirementRecord(requirement_id="led", statement="LEDを接続する")],
        functional_blocks=[
            FixtureFunctionalBlockSpec(
                block_id="esp32c3_strapping_boot", requirement_ids=["led"]
            )
        ],
    )
    first = build_design_fixture(spec, tmp_path / "one")
    second = build_design_fixture(spec, tmp_path / "two")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    for name in ("graph.json", "requirements.json", "rationale.json"):
        assert (tmp_path / "one" / name).read_bytes() == (
            tmp_path / "two" / name
        ).read_bytes()


def test_fixture_builder_emits_machine_linked_requirement_graph(tmp_path: Path) -> None:
    spec = DesignFixtureSpec(
        design_name="demo",
        requirements=[RequirementRecord(requirement_id="r1", statement="電源を供給する")],
    )
    build_design_fixture(spec, tmp_path / "fixture")
    graph = json.loads((tmp_path / "fixture" / "graph.json").read_text())
    assert graph["nodes"][0] == {
        "attrs": {"text": "電源を供給する"},
        "depends_on": [],
        "id": "req.r1",
        "kind": "requirement",
    }
