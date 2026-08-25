"""Arbitrary design fixture builder tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.parts_catalog_entry import register_parts_catalog_entry
from acd.pipeline.fixture_builder import build_design_fixture
from acd.pipeline.gd1_fixture.graph import build_graph as build_gd1_graph
from acd.schema import (
    DesignFixtureSpec,
    FixtureComponentSpec,
    FixtureCplOrientationEvidence,
    FixtureFunctionalBlockSpec,
    FixtureNetSpec,
    RequirementRecord,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.parts_catalog import ComponentPartRequest
from acd.schema.rationale import RationaleDocument
from acd.schema.requirement import RequirementDocument


def _cpl_evidence() -> FixtureCplOrientationEvidence:
    return FixtureCplOrientationEvidence(
        evidence_at=datetime(2026, 8, 11, tzinfo=UTC),
        evidence_method="fixture placement cross-check",
        evidence_basis="confirmed",
        evidence_note="Declared rotation matches this design placement.",
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
            FixtureFunctionalBlockSpec(block_id="esp32c3_strapping_boot", requirement_ids=["led"])
        ],
        # A declared recording time keeps regeneration byte-identical. Without it
        # the builder records the real generation time.
        rationale_recorded_at=datetime(2026, 8, 11, tzinfo=UTC),
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
                cpl_orientation_evidence=_cpl_evidence(),
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
    assert component["attrs"]["cpl_rotation_basis"] == "component_part_number"
    assert component["attrs"]["cpl_rotation_offset_deg"] == 0.0


def test_battery_fixture_uses_test_provenance_without_battery_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_data = json.loads(
        Path("contracts/parts-catalog.json").read_text(encoding="utf-8")
    )
    symbol = tmp_path / "battery-test-symbol.kicad_sym"
    footprint = tmp_path / "battery-test-footprint.kicad_mod"
    symbol.write_text("battery test symbol", encoding="utf-8")
    footprint.write_text("battery test footprint", encoding="utf-8")
    # These files are test scaffolding, not a normative battery part declaration.
    battery_entry = {
        "part_number": "BATTERY-CELL-3V7",
        "kind": "battery_cell",
        "value": "3.7V",
        "package": "18650",
        "library_ref": {
            "symbol": "Test:BatteryCell",
            "symbol_file": str(symbol),
            "symbol_source": "test-scaffolding",
            "symbol_source_ref": "fixture",
            "symbol_sha256": "sha256:" + hashlib.sha256(symbol.read_bytes()).hexdigest(),
            "footprint": "Test:BatteryCell",
            "footprint_file": str(footprint),
            "footprint_source": "test-scaffolding",
            "footprint_source_ref": "fixture",
            "footprint_sha256": "sha256:"
            + hashlib.sha256(footprint.read_bytes()).hexdigest(),
        },
    }
    catalog_path = tmp_path / "parts-catalog.json"
    catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")
    register_parts_catalog_entry(battery_entry, catalog_path)
    monkeypatch.setattr(
        "acd.core.part_selection.default_parts_catalog_path",
        lambda: catalog_path,
    )
    spec = DesignFixtureSpec(
        design_name="battery-demo",
        components=[
            FixtureComponentSpec(
                refdes="BT1",
                part_request=ComponentPartRequest(
                    kind="battery_cell",
                    value="3.7V",
                    package="18650",
                ),
            )
        ],
        requirements=[
            RequirementRecord(
                requirement_id="battery",
                statement="電池給電の試作設計として扱う",
                constrains_node_ids=["comp.bt1"],
            )
        ],
        functional_blocks=[
            FixtureFunctionalBlockSpec(
                block_id="safety_power_boundary",
                requirement_ids=["battery"],
            )
        ],
    )
    build_design_fixture(spec, tmp_path / "fixture")
    graph = json.loads(
        (tmp_path / "fixture" / "graph.json").read_text(encoding="utf-8")
    )
    block_ids = {
        node["attrs"]["block_id"]
        for node in graph["nodes"]
        if node["kind"] == "design.functional_block"
    }
    battery = next(node for node in graph["nodes"] if node["id"] == "comp.bt1")
    assert "usb_c_cc_termination" not in block_ids
    assert "safety_power_boundary" in block_ids
    assert battery["attrs"]["part_number"] == "BATTERY-CELL-3V7"


def test_fixture_builder_derives_cpl_evidence_path_from_graph_id(tmp_path: Path) -> None:
    spec = DesignFixtureSpec(
        design_name="custom-orientation",
        components=[
            FixtureComponentSpec(
                refdes="J1",
                part_request=ComponentPartRequest(
                    kind="connector",
                    value="TYPE-C-31-M-12",
                    package="USB_C_Receptacle_HRO_TYPE-C-31-M-12",
                ),
                cpl_orientation_evidence=_cpl_evidence(),
            )
        ],
        requirements=[
            RequirementRecord(
                requirement_id="r1",
                statement="Use the selected connector.",
                constrains_node_ids=["comp.j1"],
            )
        ],
    )
    build_design_fixture(spec, tmp_path / "fixture")
    graph = json.loads(
        (tmp_path / "fixture" / "graph.json").read_text(encoding="utf-8")
    )
    component = next(node for node in graph["nodes"] if node["id"] == "comp.j1")
    assert component["attrs"]["cpl_rotation_geometry_exception_source"] == (
        "evidence/custom-orientation-cpl-orientation/J1.json"
    )
    assert {
        key.removeprefix("cpl_rotation_")
        for key in component["attrs"]
        if key.startswith("cpl_rotation_")
    } == {
        "basis",
        "source_url",
        "evidence_at",
        "evidence_method",
        "evidence_revision",
        "evidence_basis",
        "evidence_note",
        "offset_deg",
        "polarized",
        "pin_functions",
        "pin_aliases",
        "unverified_pads",
        "unverified_pad_reason",
        "unverified_pad_source",
        "geometry_exception",
        "geometry_exception_reason",
        "geometry_exception_source",
    }
    assert component["attrs"]["cpl_rotation_evidence_revision"] == (
        "custom-orientation-r1"
    )


def test_fixture_builder_does_not_default_missing_cpl_orientation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = json.loads(Path("contracts/parts-catalog.json").read_text(encoding="utf-8"))
    resistor = next(
        entry for entry in data["entries"] if entry["part_number"] == "0603WAF1001T5E"
    )
    resistor.pop("cpl_orientation")
    catalog_path = tmp_path / "parts-catalog.json"
    catalog_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(
        "acd.core.part_selection.default_parts_catalog_path",
        lambda: catalog_path,
    )
    spec = DesignFixtureSpec(
        design_name="without-orientation",
        components=[
            FixtureComponentSpec(
                refdes="R1",
                part_request=ComponentPartRequest(
                    kind="resistor",
                    value="1k",
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
    assert "cpl_rotation_basis" not in component["attrs"]


def test_fixture_builder_requires_design_cpl_provenance(
    tmp_path: Path,
) -> None:
    spec = DesignFixtureSpec(
        design_name="without-design-evidence",
        components=[
            FixtureComponentSpec(
                refdes="R1",
                part_request=ComponentPartRequest(
                    kind="resistor",
                    value="1k",
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
    assert "cpl_rotation_basis" not in component["attrs"]


def test_fixture_builder_emits_machine_linked_requirement_graph(tmp_path: Path) -> None:
    spec = DesignFixtureSpec(
        design_name="demo",
        requirements=[RequirementRecord(requirement_id="r1", statement="電源を供給する")],
    )
    build_design_fixture(spec, tmp_path / "fixture")
    graph = json.loads(
        (tmp_path / "fixture" / "graph.json").read_text(encoding="utf-8")
    )
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
