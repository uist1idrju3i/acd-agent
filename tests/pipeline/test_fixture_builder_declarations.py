"""Tests for declared mechanical, silkscreen, and firmware fixture projection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.lane_preflight import missing_declarations, run_lane_preflight
from acd.pipeline.fixture_builder import (
    FixtureBuilderError,
    build_design_fixture,
    build_graph,
)
from acd.schema.design_fixture import (
    DesignFixtureSpec,
    FixtureBoardEdgeOverhangSpec,
    FixtureComponentBodySpec,
    FixtureComponentSpec,
    FixtureConnectorOpeningSpec,
    FixtureEnclosureSpec,
    FixtureFabOrderIntentSpec,
    FixtureFabProcessAllowanceSpec,
    FixtureFirmwareModuleSpec,
    FixtureFirmwarePinSpec,
    FixtureFirmwareSequenceStepSpec,
    FixtureFirmwareStateSpec,
    FixtureFirmwareTransitionSpec,
    FixtureMechanicalOutlineSpec,
    FixtureNetSpec,
    FixtureSafetyBoundarySpec,
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
        "requirements": [RequirementRecord(requirement_id="io", statement="Drive the IO net.")],
        "rationale_recorded_at": RECORDED_AT,
    }
    base.update(overrides)
    return DesignFixtureSpec.model_validate(base)


def _mechanical_spec() -> DesignFixtureSpec:
    return _spec(
        mechanical_outline=FixtureMechanicalOutlineSpec(attrs={"width_mm": 30.0, "depth_mm": 25.0}),
        silk_texts=[FixtureSilkTextSpec(node_id="mechanical.silk_text.u1", attrs={"text": "U1"})],
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
            nets=[
                FixtureNetSpec(net_id="net.io", attrs={"name": "IO"}),
                FixtureNetSpec(net_id="net.led", attrs={"name": "LED"}),
            ],
            firmware_pin_assignments=[
                FixtureFirmwarePinSpec(pin_id="io", net="net.led", gpio=2)
            ],
        )
    )
    report = run_lane_preflight(graph, ("firmware-pipeline",))
    assert report.status == "declarations_incomplete"
    assert {item.kind for item in report.lanes[0].missing_nodes} >= {"firmware.module"}


def test_unregistered_firmware_pin_role_reports_candidates() -> None:
    spec = _spec(
        nets=[
            FixtureNetSpec(net_id="net.io", attrs={"name": "IO"}),
            FixtureNetSpec(net_id="net.sda", attrs={"name": "SDA"}),
        ],
        firmware_pin_assignments=[
            FixtureFirmwarePinSpec(pin_id="io", net="net.sda", gpio=2)
        ],
    )
    with pytest.raises(FixtureBuilderError, match="registered:") as exc_info:
        build_graph(spec)
    assert "i2c_sda" in str(exc_info.value)
    assert "'sda'" in str(exc_info.value)


def test_registered_firmware_pin_role_builds() -> None:
    graph = build_graph(
        _spec(
            nets=[
                FixtureNetSpec(net_id="net.io", attrs={"name": "IO"}),
                FixtureNetSpec(net_id="net.i2c_sda", attrs={"name": "SDA"}),
            ],
            firmware_pin_assignments=[
                FixtureFirmwarePinSpec(pin_id="io", net="net.i2c_sda", gpio=2)
            ],
        )
    )
    pins = [node for node in graph.nodes if node.kind == "firmware.pin_assignment"]
    assert [pin.attrs["net"] for pin in pins] == ["net.i2c_sda"]


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
    report = json.loads((out_dir / "graph-overwrite-report.json").read_text(encoding="utf-8"))
    conflicts = {(item["node_id"], item.get("attr")) for item in report["conflicts"]}
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
    report = json.loads((out_dir / "graph-overwrite-report.json").read_text(encoding="utf-8"))
    assert report["conflicts"]
    backup = json.loads(Path(report["backup_path"]).read_text(encoding="utf-8"))
    assert any(node["id"] == "mechanical.mount.manual" for node in backup["nodes"])
    assert report["existing_content_hash"].startswith("sha256:")


def _enclosure_spec(**overrides: object) -> DesignFixtureSpec:
    declarations: dict[str, object] = {
        "component_bodies": [
            FixtureComponentBodySpec(
                node_id="mechanical.component_body.u1",
                refdes="U1",
                attrs={"body_type": "solid", "height_mm": 2.4},
            )
        ],
        "connector_openings": [
            FixtureConnectorOpeningSpec(
                node_id="mechanical.connector_opening.u1",
                refdes="U1",
                attrs={"face": "front"},
            )
        ],
        "board_edge_overhangs": [
            FixtureBoardEdgeOverhangSpec(
                node_id="mechanical.board_edge_overhang.u1",
                refdes="U1",
                requirement_id="io",
                attrs={"edge": "top", "overhang_mm": 1.0},
            )
        ],
        "enclosure": FixtureEnclosureSpec(attrs={"material": "PA12"}),
        "safety_boundary": FixtureSafetyBoundarySpec(attrs={"profile": "hobby"}),
    }
    declarations.update(overrides)
    return _spec(**declarations)


def test_declared_enclosure_nodes_are_projected_from_refdes_references() -> None:
    graph = build_graph(_enclosure_spec())
    nodes = {node.id: node for node in graph.nodes}
    body = nodes["mechanical.component_body.u1"]
    assert body.kind == "mechanical.component_body"
    assert body.depends_on == ["comp.u1"]
    opening = nodes["mechanical.connector_opening.u1"]
    assert opening.attrs["connector"] == "comp.u1"
    assert opening.depends_on == ["comp.u1"]
    enclosure = nodes["mechanical.enclosure.declarations"]
    assert enclosure.kind == "mechanical.enclosure"
    assert enclosure.attrs == {"material": "PA12"}
    assert enclosure.depends_on == [
        "mechanical.component_body.u1",
        "mechanical.connector_opening.u1",
    ]
    overhang = nodes["mechanical.board_edge_overhang.u1"]
    assert overhang.attrs["component_refdes"] == "U1"
    assert overhang.attrs["requirement_id"] == "req.io"
    assert overhang.depends_on == ["comp.u1", "req.io"]
    boundary = nodes["sb.declarations"]
    assert boundary.kind == "safety.boundary"
    assert boundary.attrs == {"profile": "hobby"}


def test_enclosure_declarations_referencing_unknown_components_are_rejected() -> None:
    with pytest.raises(FixtureBuilderError, match="unknown component refdes: U9"):
        build_graph(
            _enclosure_spec(
                component_bodies=[
                    FixtureComponentBodySpec(node_id="mechanical.component_body.u9", refdes="U9")
                ]
            )
        )
    with pytest.raises(FixtureBuilderError, match="unknown requirement: nope"):
        build_graph(
            _enclosure_spec(
                board_edge_overhangs=[
                    FixtureBoardEdgeOverhangSpec(
                        node_id="mechanical.board_edge_overhang.u1",
                        refdes="U1",
                        requirement_id="nope",
                    )
                ]
            )
        )


def test_declared_order_intent_extends_the_fab_profile_node() -> None:
    graph = build_graph(
        _spec(
            fab_profile_id="profile-1",
            fab_order_intent=FixtureFabOrderIntentSpec(
                requirement_id="io", attrs={"quantity_pcs": 5, "pcba_class_target": "economic"}
            ),
        )
    )
    node = next(node for node in graph.nodes if node.kind == "fab.order_intent")
    assert node.attrs == {
        "fab_profile": "profile-1",
        "quantity_pcs": 5,
        "pcba_class_target": "economic",
    }
    assert node.depends_on == ["board.declarations", "req.io"]


def test_order_intent_without_a_profile_or_with_an_unknown_requirement_is_rejected() -> None:
    with pytest.raises(FixtureBuilderError, match="requires fab_profile_id"):
        build_graph(_spec(fab_order_intent=FixtureFabOrderIntentSpec(attrs={"quantity_pcs": 1})))
    with pytest.raises(FixtureBuilderError, match="unknown requirement: nope"):
        build_graph(
            _spec(
                fab_profile_id="profile-1",
                fab_order_intent=FixtureFabOrderIntentSpec(requirement_id="nope"),
            )
        )


def test_order_intent_preflight_reports_the_declaration_path() -> None:
    report = run_lane_preflight(build_graph(_spec(fab_profile_id="profile-1")))
    items = {
        (item.lane, item.kind): item
        for item in missing_declarations(report)
        if item.kind == "fab.order_intent"
    }
    for lane in ("board-pipeline", "silkscreen-resolve"):
        item = items[(lane, "fab.order_intent")]
        assert item.spec_path == "fab_order_intent.attrs"
        assert "pcba_class_target" in {attr.attr for attr in item.missing_attrs}


def test_enclosure_preflight_reports_component_body_declaration_path() -> None:
    report = run_lane_preflight(build_graph(_spec()))
    kinds = {
        (item.lane, item.kind): item
        for item in missing_declarations(report)
        if item.lane == "enclosure-pipeline"
    }
    body = kinds[("enclosure-pipeline", "mechanical.component_body")]
    assert body.spec_path == "component_bodies[].attrs"
    assert kinds[("enclosure-pipeline", "mechanical.enclosure")].spec_path == "enclosure.attrs"


def _allowance(**overrides: object) -> FixtureFabProcessAllowanceSpec:
    base: dict[str, object] = {
        "rule_id": "pth-annular-ring-prefer-025",
        "requirement_id": "io",
        "reason": "Accepted for the prototype lot.",
        "impact_accepted": ["quality"],
    }
    base.update(overrides)
    return FixtureFabProcessAllowanceSpec.model_validate(base)


def test_declared_process_allowance_is_projected_with_rationale(tmp_path: Path) -> None:
    spec = _spec(fab_profile_id="profile-1", fab_process_allowances=[_allowance()])
    graph = build_graph(spec)
    node = graph.node_by_id("fab.process_allowance.pth-annular-ring-prefer-025")
    assert node.kind == "fab.process_allowance"
    assert node.attrs == {
        "rule_id": "pth-annular-ring-prefer-025",
        "reason": "Accepted for the prototype lot.",
        "requirement": "req.io",
        "impact_accepted": ["quality"],
    }
    assert node.depends_on == ["req.io", "board.declarations"]
    build_design_fixture(spec, tmp_path / "fixture")
    rationale = json.loads((tmp_path / "fixture" / "rationale.json").read_text(encoding="utf-8"))
    subjects = {
        (node_id, attr)
        for record in rationale["records"]
        for node_id in record["subject_nodes"]
        for attr in record["subject_attrs"]
    }
    assert ("fab.process_allowance.pth-annular-ring-prefer-025", "rule_id") in subjects
    assert ("fab.process_allowance.pth-annular-ring-prefer-025", "impact_accepted") in subjects


def test_process_allowance_without_profile_or_with_unknown_requirement_is_rejected() -> None:
    with pytest.raises(FixtureBuilderError, match="require fab_profile_id"):
        build_graph(_spec(fab_process_allowances=[_allowance()]))
    with pytest.raises(FixtureBuilderError, match="unknown requirement: nope"):
        build_graph(
            _spec(
                fab_profile_id="profile-1",
                fab_process_allowances=[_allowance(requirement_id="nope")],
            )
        )


def _overlay_spec(overlay_sha256: str) -> DesignFixtureSpec:
    return _spec(
        components=[
            FixtureComponentSpec(
                refdes="U1",
                attrs={
                    "mpn": "MCU-1",
                    "overlay_file": "overlays/u1.json",
                    "overlay_sha256": overlay_sha256,
                },
                pads={"1": "net.io"},
            )
        ]
    )


def test_declared_overlay_is_copied_only_when_its_declared_hash_matches(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    (spec_dir / "overlays").mkdir(parents=True)
    overlay = spec_dir / "overlays" / "u1.json"
    overlay.write_text('{"ops": []}\n', encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(overlay.read_bytes()).hexdigest()

    build_design_fixture(_overlay_spec(digest), tmp_path / "ok", spec_dir=spec_dir)
    assert (tmp_path / "ok" / "overlays" / "u1.json").read_bytes() == overlay.read_bytes()

    with pytest.raises(FixtureBuilderError, match="overlay hash mismatch"):
        build_design_fixture(
            _overlay_spec("sha256:" + "0" * 64), tmp_path / "bad-hash", spec_dir=spec_dir
        )
    assert not (tmp_path / "bad-hash" / "overlays" / "u1.json").exists()
    with pytest.raises(FixtureBuilderError, match="requires the design input directory"):
        build_design_fixture(_overlay_spec(digest), tmp_path / "no-dir")
    with pytest.raises(FixtureBuilderError, match="overlay file missing"):
        build_design_fixture(
            _overlay_spec(digest), tmp_path / "missing", spec_dir=tmp_path / "elsewhere"
        )
