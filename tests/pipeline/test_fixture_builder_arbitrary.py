"""Arbitrary design fixture builder tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from acd.pipeline.fixture_builder import build_design_fixture
from acd.pipeline.gd1_fixture.graph import build_graph as build_gd1_graph
from acd.schema import (
    DesignFixtureSpec,
    FixtureComponentSpec,
    FixtureFunctionalBlockSpec,
    FixtureNetSpec,
    RequirementRecord,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.parts_catalog import ComponentPartRequest
from acd.schema.rationale import RationaleDocument
from acd.schema.requirement import RequirementDocument


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
            FixtureFunctionalBlockSpec(block_id="esp32c3_strapping_boot", requirement_ids=["led"])
        ],
    )
    first = build_design_fixture(spec, tmp_path / "one")
    second = build_design_fixture(spec, tmp_path / "two")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    for name in ("graph.json", "requirements.json", "rationale.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_fixture_builder_resolves_catalog_component(tmp_path: Path) -> None:
    spec = DesignFixtureSpec(
        design_name="catalog-demo",
        components=[
            FixtureComponentSpec(
                refdes="R1",
                part_request=ComponentPartRequest(
                    kind="resistor",
                    value="4.7k",
                    package="R_0603_1608Metric",
                ),
            )
        ],
        requirements=[
            RequirementRecord(
                requirement_id="r1",
                statement="Use the selected resistor.",
                constrains_node_ids=["comp.r1"],
            )
        ],
    )
    build_design_fixture(spec, tmp_path / "fixture")
    graph = json.loads(
        (tmp_path / "fixture" / "graph.json").read_text(encoding="utf-8")
    )
    component = next(node for node in graph["nodes"] if node["id"] == "comp.r1")
    assert component["attrs"]["part_number"] == "0603WAF4701T5E"
    assert component["attrs"]["parts_catalog_id"] == "acd-parts-gd1-14.5"


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


def test_gd1_builder_regression_hash_or_revision_fallback(tmp_path: Path) -> None:
    graph_path = Path("fixtures/golden-design-1/graph.json")
    committed_graph = DesignGraph.model_validate_json(
        graph_path.read_text(encoding="utf-8")
    )
    try:
        generated = build_gd1_graph()
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
        requirements = RequirementDocument.model_validate_json(
            Path("fixtures/golden-design-1/requirements.json").read_text(
                encoding="utf-8"
            )
        )
        rationale = RationaleDocument.model_validate_json(
            Path("fixtures/golden-design-1/rationale.json").read_text(
                encoding="utf-8"
            )
        )
        assert requirements.graph_id == committed_graph.graph_id
        assert requirements.revision == committed_graph.revision
        assert rationale.graph_id == committed_graph.graph_id
        assert rationale.revision == committed_graph.revision
        pytest.skip(f"GD1 builder requires unavailable external tools: {exc}")
    generated_path = tmp_path / "graph.json"
    generated_path.write_text(
        json.dumps(
            generated.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    generated_from_temp = DesignGraph.model_validate_json(
        generated_path.read_text(encoding="utf-8")
    )
    assert canonical_json_sha256(generated_from_temp.model_dump(mode="json")) == (
        canonical_json_sha256(committed_graph.model_dump(mode="json"))
    )
