"""Firmware projection determinism and pin-consistency check tests.

Uses the Golden Design #1 fixture graph, including a deliberate pin-mismatch
negative test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.firmware_capability import (
    FirmwareCapabilityContractError,
    FirmwareCapabilityRegistry,
    load_firmware_capability_registry,
)
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.firmware_capability import (
    FirmwareCapabilityContract,
    FirmwareCapabilityRegistryDocument,
)
from fw_checks import (
    ESP32_C3_MINI_1_PAD_TO_GPIO,
    PinConsistencyError,
    assert_header_matches_lane,
    assert_pin_assignments_consistent,
)
from fw_graph import (
    FirmwareCapabilityPlan,
    FirmwareExtractionError,
    FirmwareLane,
    FirmwarePinView,
    FirmwareSettings,
    extract_firmware_lane,
    extract_firmware_settings,
    resolve_firmware_capability_plan,
)
from fw_project import (
    FirmwareProjectionError,
    firmware_project_name,
    render_pins_header,
    write_firmware_project,
)
from fw_qemu import assert_virtual_log_ok

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "golden-design-1" / "graph.json"


@pytest.fixture(scope="module")
def graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def fw_lane(graph: DesignGraph) -> FirmwareLane:
    return extract_firmware_lane(graph)


@pytest.fixture(scope="module")
def electrical(graph: DesignGraph) -> ElectricalLane:
    return extract_electrical_lane(graph)


@pytest.fixture(scope="module")
def plan(graph: DesignGraph, fw_lane: FirmwareLane) -> FirmwareCapabilityPlan:
    return resolve_firmware_capability_plan(graph, fw_lane)


def test_lane_extraction_matches_golden_design(fw_lane: FirmwareLane) -> None:
    assert fw_lane.gpio_for_net("net.led") == 7
    assert fw_lane.gpio_for_net("net.i2c_sda") == 4
    assert fw_lane.gpio_for_net("net.i2c_scl") == 5
    assert fw_lane.gpio_for_net("net.boot") == 9
    assert fw_lane.gpio_for_net("net.usb_dn") == 18
    assert fw_lane.gpio_for_net("net.usb_dp") == 19
    assert fw_lane.gpio_for_net("net.uart_rx") == 20
    assert fw_lane.gpio_for_net("net.uart_tx") == 21


def test_lane_extraction_fails_closed_on_duplicate_gpio() -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "gpio": 7}})
        if node.id == "fw.pin.boot"
        else node
        for node in graph.nodes
    ]
    broken = graph.model_copy(update={"nodes": nodes})
    with pytest.raises(FirmwareExtractionError, match="duplicate GPIO"):
        extract_firmware_lane(broken)


def test_pins_header_is_deterministic(
    fw_lane: FirmwareLane, plan: FirmwareCapabilityPlan, tmp_path: Path
) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    settings = extract_firmware_settings(graph)
    first = write_firmware_project(
        fw_lane,
        "r1",
        tmp_path / "a",
        "golden-design-1",
        settings,
        plan=plan,
    )
    second = write_firmware_project(
        fw_lane,
        "r1",
        tmp_path / "b",
        "golden-design-1",
        settings,
        plan=plan,
    )
    assert first.pins_header.read_bytes() == second.pins_header.read_bytes()
    assert first.main_source.read_bytes() == second.main_source.read_bytes()
    header = first.pins_header.read_text(encoding="utf-8")
    source = first.main_source.read_text(encoding="utf-8")
    assert "#define ACD_PIN_LED 7" in header
    assert "#define ACD_SHT40_I2C_ADDRESS 0x44" in header
    assert 'ACD_TARGET_REVISION "r1"' in header
    assert "ACD GD1 fw boot target_revision=%s" in source
    assert 'pins led=%d i2c_sda=%d i2c_scl=%d' in source
    assert "\n\n\n" not in source
    assert "static i2c_master_dev_handle_t s_sht40;" in source


def test_registry_provenance_path_is_repository_relative(
    plan: FirmwareCapabilityPlan,
) -> None:
    assert plan.registry_path == "contracts/firmware-capability-registry.json"


def test_firmware_settings_default_and_declared_values(graph: DesignGraph) -> None:
    defaults = extract_firmware_settings(graph)
    assert defaults.led_blink_period_ms == 1000
    assert defaults.log_period_ms == 2000
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    assert defaults.boot_log_message == module.attrs.get(
        "boot_log_message",
        f"ACD {graph.graph_id} fw boot target_revision=%s",
    )
    changed = next(node for node in graph.nodes if node.kind == "firmware.module")
    declared = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            "led_blink_period_ms": 250,
                            "log_period_ms": 750,
                            "boot_log_message": "boot %s",
                        }
                    }
                )
                if node.id == changed.id
                else node
                for node in graph.nodes
            ]
        }
    )
    settings = extract_firmware_settings(declared)
    assert settings.led_blink_period_ms == 250
    assert settings.log_period_ms == 750
    assert settings.boot_log_message == "boot %s"


def test_firmware_settings_default_is_graph_derived(
    graph: DesignGraph, tmp_path: Path
) -> None:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    key: value
                    for key, value in node.attrs.items()
                    if key != "boot_log_message"
                }
            }
        )
        if node.id == module.id
        else node
        for node in graph.nodes
    ]
    arbitrary = graph.model_copy(update={"graph_id": "custom-design", "nodes": nodes})
    settings = extract_firmware_settings(arbitrary)
    arbitrary_lane = extract_firmware_lane(arbitrary)
    arbitrary_plan = resolve_firmware_capability_plan(arbitrary, arbitrary_lane)
    assert settings.boot_log_message == "ACD custom-design fw boot target_revision=%s"
    project = write_firmware_project(
        arbitrary_lane,
        "r1",
        tmp_path,
        arbitrary.graph_id,
        plan=arbitrary_plan,
    )
    assert "ACD custom-design fw boot target_revision=%s" in project.main_source.read_text(
        encoding="utf-8"
    )


def test_malformed_firmware_settings_fail_closed(graph: DesignGraph) -> None:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    broken = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={"attrs": {**node.attrs, "log_period_ms": 0}}
                )
                if node.id == module.id
                else node
                for node in graph.nodes
            ]
        }
    )
    with pytest.raises(FirmwareExtractionError, match="log_period_ms"):
        extract_firmware_settings(broken)


@pytest.mark.parametrize(
    "boot_log_message",
    [
        "",
        "boot",
        'boot "quoted" %s',
        r"boot \\path %s",
        "boot\n%s",
        "boot %d %s",
        "boot %% %s",
        "boot %s%",
        "boot %s %s",
    ],
)
def test_malformed_boot_log_message_fails_closed(
    graph: DesignGraph, boot_log_message: str
) -> None:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    broken = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            "boot_log_message": boot_log_message,
                        }
                    }
                )
                if node.id == module.id
                else node
                for node in graph.nodes
            ]
        }
    )
    with pytest.raises(FirmwareExtractionError, match="C string literal template"):
        extract_firmware_settings(broken)


def test_missing_boot_log_placeholder_fails_closed(
    fw_lane: FirmwareLane,
    plan: FirmwareCapabilityPlan,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(FirmwareProjectionError, match="C string"):
        write_firmware_project(
            fw_lane,
            "r1",
            tmp_path,
            "custom-design",
            FirmwareSettings(boot_log_message="boot"),
            plan=plan,
        )


def test_project_name_is_derived_from_the_graph_id(
    graph: DesignGraph, fw_lane: FirmwareLane, tmp_path: Path
) -> None:
    plan = resolve_firmware_capability_plan(graph, fw_lane)
    project = write_firmware_project(
        fw_lane, "r1", tmp_path, "golden-design-1", plan=plan
    )
    assert project.name == "acd_golden_design_1_fw"
    assert project.root.name == project.name
    assert project.app_binary.name == "acd_golden_design_1_fw.bin"
    assert 'project(acd_golden_design_1_fw)' in (
        project.root / "CMakeLists.txt"
    ).read_text(encoding="utf-8")
    assert 'TAG = "acd_golden_design_1"' in project.main_source.read_text(encoding="utf-8")


@pytest.mark.parametrize("graph_id", ["", "   ", "---", "///"])
def test_unusable_graph_id_fails_closed(graph_id: str) -> None:
    with pytest.raises(FirmwareProjectionError, match="firmware project name"):
        firmware_project_name(graph_id)


def test_generated_header_matches_lane(
    fw_lane: FirmwareLane, plan: FirmwareCapabilityPlan
) -> None:
    assert_header_matches_lane(
        render_pins_header(
            fw_lane, "r1", FirmwareSettings(boot_log_message="test %s"), plan
        ),
        fw_lane,
    )


def test_header_check_rejects_tampered_gpio(
    fw_lane: FirmwareLane, plan: FirmwareCapabilityPlan
) -> None:
    header = render_pins_header(
        fw_lane, "r1", FirmwareSettings(boot_log_message="test %s"), plan
    ).replace("ACD_PIN_LED 7", "ACD_PIN_LED 6")
    with pytest.raises(PinConsistencyError, match="ACD_PIN_LED"):
        assert_header_matches_lane(header, fw_lane)


def test_pin_check_passes_on_golden_design(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    assert_pin_assignments_consistent(fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_pin_check_rejects_deliberate_pin_shift(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    """Negative test: shifting the LED assignment to another GPIO must fail."""
    shifted = FirmwareLane(
        pins=tuple(
            FirmwarePinView(
                node_id=p.node_id,
                gpio=6,
                net_id=p.net_id,
                role=p.role,
            )
            if p.net_id == "net.led"
            else p
            for p in fw_lane.pins
        )
    )
    with pytest.raises(PinConsistencyError, match=r"net\.led"):
        assert_pin_assignments_consistent(shifted, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_pin_check_rejects_pad_outside_pinned_map(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    partial_map = {k: v for k, v in ESP32_C3_MINI_1_PAD_TO_GPIO.items() if v != 7}
    with pytest.raises(PinConsistencyError, match="not in pinned pad map"):
        assert_pin_assignments_consistent(fw_lane, electrical, "U1", partial_map)


def test_pin_check_rejects_unknown_module(
    fw_lane: FirmwareLane, electrical: ElectricalLane
) -> None:
    with pytest.raises(PinConsistencyError, match="not found"):
        assert_pin_assignments_consistent(fw_lane, electrical, "U99", ESP32_C3_MINI_1_PAD_TO_GPIO)


def test_render_header_only_emits_declared_pins() -> None:
    lane = FirmwareLane(
        pins=(
            FirmwarePinView(
                node_id="fw.pin.led", gpio=7, net_id="net.led", role="led"
            ),
        )
    )
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    plan = resolve_firmware_capability_plan(graph, extract_firmware_lane(graph))
    header = render_pins_header(lane, "r1", FirmwareSettings(boot_log_message="test %s"), plan)
    assert "ACD_PIN_LED 7" in header
    assert "ACD_PIN_I2C_SDA" not in header


def test_led_only_graph_projects_without_sensor_code(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "led-only-tag" / "graph.json"
    graph = DesignGraph.model_validate(json.loads(fixture.read_text(encoding="utf-8")))
    lane = extract_firmware_lane(graph)
    plan = resolve_firmware_capability_plan(graph, lane)
    project = write_firmware_project(
        lane,
        graph.revision,
        tmp_path,
        graph.graph_id,
        extract_firmware_settings(graph),
        plan=plan,
    )
    header = project.pins_header.read_text(encoding="utf-8")
    source = project.main_source.read_text(encoding="utf-8")
    assert "#define ACD_PIN_LED 7" in header
    assert "ACD_PIN_" not in header.replace("#define ACD_PIN_LED 7", "")
    assert "driver/i2c_master.h" not in source
    assert "SHT40" not in source
    assert "ACD_LOG_PERIOD_MS" not in source
    assert "\n\n\n" not in source
    assert_header_matches_lane(header, lane)
    assert_virtual_log_ok(
        """I (1) acd_led_only_tag: ACD led-only-tag fw boot target_revision=r1
I (2) acd_led_only_tag: pins led=7
I (3) acd_led_only_tag: LED gpio=7 state=1
I (4) acd_led_only_tag: LED gpio=7 state=0
""",
        target_revision="r1",
        boot_log_message="ACD led-only-tag fw boot target_revision=%s",
        lane=lane,
        plan=plan,
    )


def _graph_with_step_change(graph: DesignGraph, step_id: str, **changes: object) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, **changes}})
                if node.id == step_id
                else node
                for node in graph.nodes
            ]
        }
    )


def test_capability_plan_rejects_unregistered_action(
    graph: DesignGraph, fw_lane: FirmwareLane
) -> None:
    broken = _graph_with_step_change(graph, "fw.sequence.003", action="not_registered")
    with pytest.raises(FirmwareExtractionError, match=r"not_registered.*registry"):
        resolve_firmware_capability_plan(broken, fw_lane)


def test_capability_plan_rejects_missing_required_role(
    graph: DesignGraph, fw_lane: FirmwareLane
) -> None:
    broken = graph.model_copy(
        update={"nodes": [node for node in graph.nodes if node.id != "fw.pin.i2c_scl"]}
    )
    broken_lane = extract_firmware_lane(broken)
    with pytest.raises(
        FirmwareExtractionError, match=r"initialize_sht40.*i2c_scl"
    ):
        resolve_firmware_capability_plan(broken, broken_lane)


@pytest.mark.parametrize(
    ("attrs", "message"),
    [
        ({"target": "comp.u3"}, "has no mpn"),
        ({"target": "comp.u3", "mpn": "UNREGISTERED"}, "not registered"),
        ({"target": "comp.missing"}, "not an electrical component"),
        ({}, "requires a target device"),
    ],
)
def test_capability_plan_rejects_bad_device_resolution(
    graph: DesignGraph,
    fw_lane: FirmwareLane,
    attrs: dict[str, object],
    message: str,
) -> None:
    nodes: list[GraphNode] = []
    for node in graph.nodes:
        if node.id == "comp.u3":
            if attrs == {"target": "comp.u3"}:
                node = node.model_copy(
                    update={
                        "attrs": {
                            key: value
                            for key, value in node.attrs.items()
                            if key != "mpn"
                        }
                    }
                )
            elif "mpn" in attrs:
                node = node.model_copy(
                    update={"attrs": {**node.attrs, "mpn": attrs["mpn"]}}
                )
        if node.id == "fw.sequence.004":
            updated_attrs = (
                {key: value for key, value in node.attrs.items() if key != "target"}
                if not attrs
                else {**node.attrs, **attrs}
            )
            node = node.model_copy(update={"attrs": updated_attrs})
        nodes.append(node)
    broken = graph.model_copy(update={"nodes": nodes})
    with pytest.raises(FirmwareExtractionError, match=message):
        resolve_firmware_capability_plan(broken, extract_firmware_lane(broken))


def test_capability_plan_rejects_duplicate_step_index(
    graph: DesignGraph, fw_lane: FirmwareLane
) -> None:
    broken = _graph_with_step_change(graph, "fw.sequence.004", step_index=3)
    with pytest.raises(FirmwareExtractionError, match="duplicate"):
        resolve_firmware_capability_plan(broken, fw_lane)


def test_capability_plan_rejects_non_contiguous_step_index(
    graph: DesignGraph, fw_lane: FirmwareLane
) -> None:
    broken = _graph_with_step_change(graph, "fw.sequence.003", step_index=9)
    with pytest.raises(
        FirmwareExtractionError, match="contiguous 1-based"
    ):
        resolve_firmware_capability_plan(broken, fw_lane)


def test_registry_schema_violation_fails_closed(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[5] / "contracts" / "firmware-capability-registry.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    value["capabilities"].append(value["capabilities"][0])
    path = tmp_path / "invalid-registry.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(FirmwareCapabilityContractError, match="capability_id"):
        load_firmware_capability_registry(path)


def test_missing_fragment_provider_fails_closed(
    graph: DesignGraph, fw_lane: FirmwareLane, tmp_path: Path
) -> None:
    document = load_firmware_capability_registry().document
    custom = FirmwareCapabilityContract(
        capability_id="custom_capability",
        actions=["custom_action"],
    )
    registry = FirmwareCapabilityRegistry(
        document=FirmwareCapabilityRegistryDocument.model_validate(
            document.model_dump(mode="json")
            | {"capabilities": [*document.capabilities, custom.model_dump(mode="json")]}
        ),
        registry_hash="sha256:" + "1" * 64,
        path=tmp_path / "custom-registry.json",
    )
    broken = _graph_with_step_change(graph, "fw.sequence.003", action="custom_action")
    plan = resolve_firmware_capability_plan(broken, fw_lane, registry)
    with pytest.raises(FirmwareProjectionError, match="no fragment provider"):
        write_firmware_project(
            fw_lane,
            "r1",
            tmp_path,
            "custom-design",
            plan=plan,
        )


def test_mcu_component_resolution_fails_closed(graph: DesignGraph) -> None:
    from run_fw_pipeline import resolve_mcu_refdes

    broken = _graph_with_step_change(
        graph, "fw.sequence.003", target="comp.missing"
    )
    module = next(node for node in broken.nodes if node.kind == "firmware.module")
    broken = broken.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={"attrs": {**node.attrs, "mcu_component": "comp.missing"}}
                )
                if node.id == module.id
                else node
                for node in broken.nodes
            ]
        }
    )
    with pytest.raises(ValueError, match="does not resolve"):
        resolve_mcu_refdes(broken)
