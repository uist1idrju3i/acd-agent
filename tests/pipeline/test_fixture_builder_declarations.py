"""Tests for declared mechanical, silkscreen, and firmware fixture projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.lane_preflight import run_lane_preflight
from acd.pipeline.fixture_builder import (
    FixtureBuilderError,
    build_design_fixture,
    build_graph,
)
from acd.schema.design_fixture import (
    DesignFixtureSpec,
    FixtureComponentSpec,
    FixtureFirmwareModuleSpec,
    FixtureFirmwarePinSpec,
    FixtureFirmwareSequenceStepSpec,
    FixtureFirmwareStateSpec,
    FixtureFirmwareTransitionSpec,
    FixtureMechanicalOutlineSpec,
    FixtureNetSpec,
    FixtureSilkGraphicSpec,
    FixtureSilkTextSpec,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.requirement import RequirementRecord

RECORDED_AT = datetime(2026, 8, 11, tzinfo=UTC)


def _spec(**overrides: object) -> DesignFixtureSpec:
    base: dict[str, object] = {
        "design_name": "declarations",
        "components": [
            FixtureComponentSpec(refdes="U1", attrs={"mpn": "MCU-1"}, pads={"1": "net.io"}),
        ],
        "nets": [FixtureNetSpec(net_id="net.io", attrs={"name": "IO"})],
        "requirements": [
            RequirementRecord(requirement_id="io", statement="Drive the IO net.")
        ],
        "rationale_recorded_at": RECORDED_AT,
    }
    base.update(overrides)
    return DesignFixtureSpec.model_validate(base)


def _mechanical_spec() -> DesignFixtureSpec:
    return _spec(
        mechanical_outline=FixtureMechanicalOutlineSpec(
            attrs={"width_mm": 30.0, "depth_mm": 25.0}
        ),
        silk_texts=[
            FixtureSilkTextSpec(node_id="mechanical.silk_text.u1", attrs={"text": "U1"})
        ],
        silk_graphics=[
            FixtureSilkGraphicSpec(
                node_id="mechanical.silk_graphic.logo", attrs={"layer": "F.SilkS"}
            )
        ],
    )


def _firmware_module() -> FixtureFirmwareModuleSpec:
    return FixtureFirmwareModuleSpec(
        attrs={
            "module_name": "app",
            "mcu_component": "comp.u1",
            "entry_state": "firmware.state.boot",
        },
        states=[
            FixtureFirmwareStateSpec(
                node_id="firmware.state.boot",
                attrs={"state_name": "boot", "initial": True},
            ),
            FixtureFirmwareStateSpec(
                node_id="firmware.state.run",
                attrs={"state_name": "run", "initial": False},
            ),
        ],
        transitions=[
            FixtureFirmwareTransitionSpec(
                node_id="firmware.state_transition.boot_run",
                attrs={
                    "from_state": "firmware.state.boot",
                    "to_state": "firmware.state.run",
                    "trigger": "boot_complete",
                },
            )
        ],
        sequence_steps=[
            FixtureFirmwareSequenceStepSpec(
                node_id="firmware.sequence_step.1",
                attrs={
                    "step_index": 1,
                    "actor": "firmware.state.boot",
                    "target": "comp.u1",
                    "action": "configure",
                },
            )
        ],
    )


def test_declared_mechanical_nodes_are_projected() -> None:
    graph = build_graph(_mechanical_spec())
    kinds = {node.kind for node in graph.nodes}
    assert {"mechanical.outline", "mechanical.silk_text", "mechanical.silk_graphic"} <= kinds
    outline = next(node for node in graph.nodes if node.kind == "mechanical.outline")
    assert outline.attrs["width_mm"] == 30.0


def test_undeclared_mechanical_and_firmware_nodes_are_absent() -> None:
    graph = build_graph(_spec())
    kinds = {node.kind for node in graph.nodes}
    assert not kinds & {
        "mechanical.outline",
        "mechanical.silk_text",
        "mechanical.silk_graphic",
        "firmware.module",
    }


def test_declared_firmware_module_is_projected_with_its_state_machine() -> None:
    graph = build_graph(_spec(firmware_module=_firmware_module()))
    by_kind = {node.kind: node for node in graph.nodes}
    assert by_kind["firmware.module"].attrs["module_name"] == "app"
    assert "firmware.state.boot" in by_kind["firmware.module"].depends_on
    assert {node.kind for node in graph.nodes} >= {
        "firmware.module",
        "firmware.state",
        "firmware.state_transition",
        "firmware.sequence_step",
    }


def test_firmware_module_referencing_an_unknown_component_is_rejected() -> None:
    module = _firmware_module().model_copy(
        update={
            "attrs": {
                "module_name": "app",
                "mcu_component": "comp.u9",
                "entry_state": "firmware.state.boot",
            }
        }
    )
    with pytest.raises(FixtureBuilderError, match="unknown component"):
        build_graph(_spec(firmware_module=module))


def test_firmware_transition_referencing_an_unknown_state_is_rejected() -> None:
    module = _firmware_module()
    broken = module.model_copy(
        update={
            "transitions": [
                FixtureFirmwareTransitionSpec(
                    node_id="firmware.state_transition.bad",
                    attrs={
                        "from_state": "firmware.state.boot",
                        "to_state": "firmware.state.missing",
                        "trigger": "boot_complete",
                    },
                )
            ]
        }
    )
    with pytest.raises(FixtureBuilderError, match="unknown states"):
        build_graph(_spec(firmware_module=broken))


def test_missing_firmware_declarations_keep_the_lane_incomplete() -> None:
    graph = build_graph(
        _spec(
            firmware_pin_assignments=[
                FixtureFirmwarePinSpec(pin_id="io", net="net.io", gpio=2)
            ]
        )
    )
    report = run_lane_preflight(graph, ("firmware-pipeline",))
    assert report.status == "declarations_incomplete"
    assert {item.kind for item in report.lanes[0].missing_nodes} >= {"firmware.module"}


def test_existing_manual_graph_data_is_not_overwritten(tmp_path: Path) -> None:
    out_dir = tmp_path / "fixture"
    build_design_fixture(_mechanical_spec(), out_dir)
    graph_path = out_dir / "graph.json"
    existing = json.loads(graph_path.read_text(encoding="utf-8"))
    for node in existing["nodes"]:
        if node["kind"] == "mechanical.outline":
            node["attrs"]["thickness_mm"] = 1.6
    existing["nodes"].append(
        {
            "id": "mechanical.mount.manual",
            "kind": "mechanical.outline",
            "attrs": {"width_mm": 1.0},
            "depends_on": [],
        }
    )
    graph_path.write_text(json.dumps(existing), encoding="utf-8")

    with pytest.raises(FixtureBuilderError, match="does not declare"):
        build_design_fixture(_mechanical_spec(), out_dir)

    preserved = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    assert any(node.id == "mechanical.mount.manual" for node in preserved.nodes)
    report = json.loads(
        (out_dir / "graph-overwrite-report.json").read_text(encoding="utf-8")
    )
    conflicts = {
        (item["node_id"], item.get("attr")) for item in report["conflicts"]
    }
    assert ("mechanical.mount.manual", None) in conflicts
    assert any(attr == "thickness_mm" for _, attr in conflicts)


def test_acknowledged_overwrite_reports_the_dropped_manual_data(tmp_path: Path) -> None:
    out_dir = tmp_path / "fixture"
    build_design_fixture(_mechanical_spec(), out_dir)
    graph_path = out_dir / "graph.json"
    existing = json.loads(graph_path.read_text(encoding="utf-8"))
    existing["nodes"].append(
        {
            "id": "mechanical.mount.manual",
            "kind": "mechanical.outline",
            "attrs": {"width_mm": 1.0},
            "depends_on": [],
        }
    )
    graph_path.write_text(json.dumps(existing), encoding="utf-8")
    build_design_fixture(_mechanical_spec(), out_dir, overwrite=True)
    rewritten = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    assert not any(node.id == "mechanical.mount.manual" for node in rewritten.nodes)
    report = json.loads(
        (out_dir / "graph-overwrite-report.json").read_text(encoding="utf-8")
    )
    assert report["conflicts"]
    backup = json.loads(Path(report["backup_path"]).read_text(encoding="utf-8"))
    assert any(node["id"] == "mechanical.mount.manual" for node in backup["nodes"])
    assert report["existing_content_hash"].startswith("sha256:")
