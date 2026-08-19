"""Deterministic GD1 design predicates."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.placement import rotate_point
from acd.core.electrical import ComponentView, ElectricalLane
from acd.pipeline.repository import repository_root
from acd.schema.design_graph import DesignGraph, GraphNode

PredicateStatus = Literal["pass", "fail", "unknown"]

CC_EXPECTED_KOHM = "5.1k"
I2C_EXPECTED_KOHM = "4.7k"
BOOT_PULLUP_KOHM = "10k"
STRAPPING_GPIOS = frozenset({2, 8, 9})
LDO_INPUT_V = 5.0
LDO_OUTPUT_V = 3.3
LARGE_DECOUPLING_UF = 10.0
SMALL_DECOUPLING_UF = 0.1
SMALL_DECOUPLING_TOLERANCE_UF = 0.02
SMALL_CAP_DISTANCE_MM = 3.0
LARGE_CAP_DISTANCE_MM = 8.0


class PredicateResult(BaseModel):
    """One deterministic predicate outcome."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: PredicateStatus
    detail: str


class SafetyBoundaryResult(BaseModel):
    """Aggregate safety-boundary predicates with fail-closed precedence."""

    model_config = ConfigDict(frozen=True)

    predicates: tuple[PredicateResult, ...]
    status: PredicateStatus

    @classmethod
    def from_predicates(cls, predicates: tuple[PredicateResult, ...]) -> SafetyBoundaryResult:
        statuses = {predicate.status for predicate in predicates}
        status: PredicateStatus
        if "unknown" in statuses:
            status = "unknown"
        elif "fail" in statuses:
            status = "fail"
        else:
            status = "pass"
        return cls(predicates=predicates, status=status)


def _result(name: str, status: PredicateStatus, detail: str) -> PredicateResult:
    return PredicateResult(name=name, status=status, detail=detail)


def _nodes(graph: DesignGraph, kind: str) -> tuple[GraphNode, ...]:
    return tuple(node for node in graph.nodes if node.kind == kind)


def _net_id(graph: DesignGraph, *names: str) -> str | None:
    expected = {name.casefold() for name in names}
    for node in _nodes(graph, "electrical.net"):
        name = node.attrs.get("name")
        if isinstance(name, str) and name.casefold() in expected:
            return node.id
    return None


def _component_by_refdes(lane: ElectricalLane, refdes: str) -> ComponentView | None:
    matches = tuple(component for component in lane.components if component.refdes == refdes)
    return matches[0] if len(matches) == 1 else None


def _parse_capacitance(value: str) -> float | None:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([unp]?F)\s*", value, re.IGNORECASE)
    if match is None:
        return None
    number = float(match.group(1))
    unit = match.group(2).casefold()
    scale = {"uf": 1.0, "nf": 0.001, "pf": 0.000001}[unit]
    result = number * scale
    return result if math.isfinite(result) and result > 0 else None


def _resistor_matches(
    lane: ElectricalLane, target_net: str, rail_net: str, value: str
) -> tuple[ComponentView, ...]:
    matches: list[ComponentView] = []
    for component in lane.components:
        if not component.refdes.upper().startswith("R"):
            continue
        pins = lane.pins_of_component(component.node_id)
        connected = {pin.net_id for pin in pins if pin.net_id is not None}
        if (
            connected == {target_net, rail_net}
            and component.value.strip().casefold() == value.casefold()
        ):
            matches.append(component)
    return tuple(matches)


def _evaluate_pullups(
    graph: DesignGraph,
    lane: ElectricalLane,
    name: str,
    target_names: tuple[str, ...],
    rail_names: tuple[str, ...],
    expected_value: str,
    require_mpn: bool,
) -> PredicateResult:
    failures: list[str] = []
    unknowns: list[str] = []
    for target_name in target_names:
        target_net = _net_id(graph, target_name)
        rail_net = _net_id(graph, *rail_names)
        ground_net = _net_id(graph, "GND")
        if target_net is None or rail_net is None or ground_net is None:
            unknowns.append(target_name)
            continue
        candidates = _resistor_matches(lane, target_net, ground_net, expected_value)
        if rail_names != ("GND",):
            candidates = _resistor_matches(lane, target_net, rail_net, expected_value)
        if len(candidates) != 1:
            failures.append(f"{target_name} has {len(candidates)} matching resistors")
            continue
        if require_mpn and not candidates[0].mpn.strip():
            failures.append(f"{target_name} resistor MPN is empty")
    if unknowns:
        return _result(name, "unknown", "required net resolution failed: " + ", ".join(unknowns))
    if failures:
        return _result(name, "fail", "; ".join(failures))
    return _result(name, "pass", f"{name} topology and values match the GD1 contract")


def evaluate_usb_cc(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    """Check one 5.1 kOhm Rd from each CC net to GND."""
    return _evaluate_pullups(
        graph,
        lane,
        "usb_cc",
        ("CC1", "CC2"),
        ("GND",),
        CC_EXPECTED_KOHM,
        require_mpn=True,
    )


def evaluate_i2c_pullup(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    """Check the SDA and SCL 4.7 kOhm pull-ups."""
    return _evaluate_pullups(
        graph,
        lane,
        "i2c_pullup",
        ("I2C_SDA", "I2C_SCL"),
        ("+3V3", "3V3"),
        I2C_EXPECTED_KOHM,
        require_mpn=True,
    )


def _u1_io_pads(lane: ElectricalLane) -> dict[int, tuple[str, ...]] | None:
    u1 = _component_by_refdes(lane, "U1")
    if u1 is None:
        return None
    resolved: dict[int, list[str]] = {}
    for pad, function in u1.cpl_rotation_pin_functions.items():
        match = re.fullmatch(r"IO([0-9]+)", function.strip(), re.IGNORECASE)
        if match is not None:
            resolved.setdefault(int(match.group(1)), []).append(pad)
    function_pads = {
        function: pad for pad, function in u1.cpl_rotation_pin_functions.items()
    }
    for alias, function in u1.cpl_rotation_pin_aliases.items():
        match = re.match(r"GPIO([0-9]+)(?:/|$)", alias, re.IGNORECASE)
        if match is None:
            continue
        pad = function_pads.get(function)
        if pad is None:
            return None
        gpio = int(match.group(1))
        if pad not in resolved.setdefault(gpio, []):
            resolved[gpio].append(pad)
    if any(len(resolved.get(gpio, ())) != 1 for gpio in STRAPPING_GPIOS):
        return None
    return {gpio: tuple(pads) for gpio, pads in resolved.items()}


def _firmware_nodes(graph: DesignGraph) -> tuple[GraphNode, ...]:
    return _nodes(graph, "firmware.pin_assignment")


def _gpio_value(node: GraphNode) -> int | None:
    value = node.attrs.get("gpio")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def evaluate_strapping_pin(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    """Check IO2/IO8/IO9 boot topology.

    ESP32-C3 boot configuration documents specify GPIO9's reset default as
    ``1 (Pull-up)`` with an approximately 45 kOhm internal pull-up; an
    external BOOT pull-up is therefore optional.
    """
    mapping = _u1_io_pads(lane)
    if mapping is None:
        return _result("strapping_pin", "unknown", "U1 IO-to-pad mapping is missing or ambiguous")
    u1 = _component_by_refdes(lane, "U1")
    boot_net = _net_id(graph, "BOOT")
    ground_net = _net_id(graph, "GND")
    p3v3_net = _net_id(graph, "+3V3", "3V3")
    led_net = _net_id(graph, "LED")
    if u1 is None or boot_net is None or ground_net is None or p3v3_net is None or led_net is None:
        return _result("strapping_pin", "unknown", "strapping net resolution is incomplete")

    failures: list[str] = []
    for gpio in (2, 8):
        pad = mapping[gpio][0]
        pin = next((item for item in lane.pins_of_component(u1.node_id) if item.pad == pad), None)
        if pin is None:
            return _result("strapping_pin", "unknown", f"IO{gpio} pad is unresolved")
        if pin.net_id is not None or not pin.no_connect:
            failures.append(f"IO{gpio} has an external connection")
    io9_pad = mapping[9][0]
    io9_pin = next(
        (item for item in lane.pins_of_component(u1.node_id) if item.pad == io9_pad), None
    )
    if io9_pin is None:
        return _result("strapping_pin", "unknown", "IO9 pad is unresolved")
    if io9_pin.net_id != boot_net:
        failures.append("IO9 is not connected to BOOT")
    boot_components = [
        component
        for component in lane.components
        if any(pin.net_id == boot_net for pin in lane.pins_of_component(component.node_id))
        and component.node_id != u1.node_id
    ]
    pullups: list[ComponentView] = []
    buttons: list[ComponentView] = []
    for component in boot_components:
        nets = {
            pin.net_id
            for pin in lane.pins_of_component(component.node_id)
            if pin.net_id is not None
        }
        if component.refdes.upper().startswith("R") and nets == {boot_net, p3v3_net}:
            pullups.append(component)
        elif component.refdes.upper().startswith("SW") and nets == {boot_net, ground_net}:
            buttons.append(component)
        elif not component.refdes.upper().startswith(("R", "SW")):
            return _result(
                "strapping_pin", "unknown", f"BOOT component type is unresolved: {component.refdes}"
            )
        else:
            failures.append(f"unexpected BOOT component: {component.refdes}")
    if len(pullups) > 1:
        failures.append(f"BOOT pull-up count is {len(pullups)}")
    if len(buttons) != 1:
        failures.append(f"BOOT button count is {len(buttons)}")
    for node in _firmware_nodes(graph):
        gpio = _gpio_value(node)
        net = node.attrs.get("net")
        if gpio is None or not isinstance(net, str):
            return _result("strapping_pin", "unknown", f"malformed firmware assignment: {node.id}")
        if gpio in (2, 8) or (gpio == 9 and net != boot_net):
            failures.append(f"unexpected strapping firmware assignment: {node.id}")
        if gpio == 9 and net == boot_net and node.id != "fw.pin.boot":
            failures.append(f"unexpected BOOT assignment identity: {node.id}")
    if any(
        pin.net_id == led_net
        for gpio in STRAPPING_GPIOS
        for pad_number in mapping[gpio]
        for pin in lane.pins_of_component(u1.node_id)
        if pin.pad == pad_number
    ):
        failures.append("LED net is connected to a strapping pad")
    if failures:
        return _result("strapping_pin", "fail", "; ".join(failures))
    return _result("strapping_pin", "pass", "IO2/IO8/IO9 preserve the permitted GD1 boot topology")


def evaluate_pin_firmware_alignment(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    """Check every firmware GPIO assignment against the U1 pad map."""
    mapping = _u1_io_pads(lane)
    u1 = _component_by_refdes(lane, "U1")
    if mapping is None or u1 is None:
        return _result("pin_firmware_alignment", "unknown", "U1 IO-to-pad mapping is missing")
    failures: list[str] = []
    for node in _firmware_nodes(graph):
        gpio = _gpio_value(node)
        net_id = node.attrs.get("net")
        if gpio is None or not isinstance(net_id, str):
            return _result(
                "pin_firmware_alignment", "unknown", f"malformed firmware assignment: {node.id}"
            )
        pads = mapping.get(gpio)
        if pads is None or len(pads) != 1:
            return _result("pin_firmware_alignment", "unknown", f"GPIO{gpio} pad is unresolved")
        if _net_id(graph, net_id) is None and not any(net.node_id == net_id for net in lane.nets):
            return _result(
                "pin_firmware_alignment", "unknown", f"firmware net is unresolved: {net_id}"
            )
        pin = next(
            (item for item in lane.pins_of_component(u1.node_id) if item.pad == pads[0]), None
        )
        if pin is None or pin.net_id != net_id:
            failures.append(f"{node.id} does not match U1 pad {pads[0]}")
    if failures:
        return _result("pin_firmware_alignment", "fail", "; ".join(failures))
    return _result(
        "pin_firmware_alignment", "pass", "firmware pin assignments match the U1 electrical pads"
    )


def _component_net_ids(lane: ElectricalLane, component: ComponentView) -> set[str]:
    return {
        pin.net_id for pin in lane.pins_of_component(component.node_id) if pin.net_id is not None
    }


def _rail_capacitors(
    lane: ElectricalLane, rail_net: str, ground_net: str
) -> tuple[tuple[ComponentView, float], ...] | None:
    result: list[tuple[ComponentView, float]] = []
    for component in lane.components:
        nets = _component_net_ids(lane, component)
        if nets != {rail_net, ground_net}:
            continue
        value = _parse_capacitance(component.value)
        if value is None:
            return None
        result.append((component, value))
    return tuple(result)


def _resolve_path(path_value: str, fixture_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    candidate = fixture_dir / path
    if candidate.is_file():
        return candidate
    return repository_root() / path


def _component_pad_positions(
    graph: DesignGraph,
    lane: ElectricalLane,
    component: ComponentView,
    net_id: str,
    fixture_dir: Path,
    library: FootprintLibrary,
) -> tuple[tuple[float, float], ...]:
    shape = library.load(
        component.library.footprint,
        _resolve_path(component.library.footprint_file, fixture_dir),
        component.library.footprint_sha256,
    )
    node_position = next(
        node for node in _nodes(graph, "electrical.component") if node.id == component.node_id
    )
    x = node_position.attrs.get("placement_x_mm")
    y = node_position.attrs.get("placement_y_mm")
    rotation = node_position.attrs.get("placement_rotation_deg")
    if (
        not isinstance(x, (int, float))
        or isinstance(x, bool)
        or not isinstance(y, (int, float))
        or isinstance(y, bool)
        or not isinstance(rotation, (int, float))
        or isinstance(rotation, bool)
    ):
        raise ValueError(f"{component.refdes}: placement is missing")
    x_value = float(x)
    y_value = float(y)
    rotation_value = float(rotation)
    pads = [pin.pad for pin in lane.pins_of_component(component.node_id) if pin.net_id == net_id]
    positions: list[tuple[float, float]] = []
    for pad_number in pads:
        for pad in shape.pads:
            if pad.number != pad_number:
                continue
            px, py = rotate_point(pad.x_mm, pad.y_mm, rotation_value)
            positions.append((x_value + px, y_value + py))
    if not positions:
        raise ValueError(f"{component.refdes}: net pad geometry is missing")
    return tuple(positions)


def _minimum_pad_distance(
    graph: DesignGraph,
    lane: ElectricalLane,
    capacitor: ComponentView,
    target: ComponentView,
    net_id: str,
    fixture_dir: Path,
) -> float:
    library = FootprintLibrary()
    cap_positions = _component_pad_positions(graph, lane, capacitor, net_id, fixture_dir, library)
    target_positions = _component_pad_positions(graph, lane, target, net_id, fixture_dir, library)
    return min(
        math.dist(cap_position, target_position)
        for cap_position in cap_positions
        for target_position in target_positions
    )


def evaluate_power_decoupling(
    graph: DesignGraph, lane: ElectricalLane, fixture_dir: Path | None = None
) -> PredicateResult:
    """Check LDO rails and pinned capacitor-to-target distances."""
    fixture = fixture_dir or repository_root() / "fixtures" / "golden-design-1"
    ground_net = _net_id(graph, "GND")
    input_net = _net_id(graph, "VBUS_5V")
    output_net = _net_id(graph, "+3V3", "3V3")
    if ground_net is None or input_net is None or output_net is None:
        return _result("power_decoupling", "unknown", "power rail resolution is incomplete")
    ldos = tuple(
        component
        for component in lane.components
        if {input_net, output_net} <= _component_net_ids(lane, component)
    )
    if len(ldos) != 1:
        return _result("power_decoupling", "unknown", "LDO resolution is missing or ambiguous")
    for rail in (input_net, output_net):
        capacitors = _rail_capacitors(lane, rail, ground_net)
        if capacitors is None:
            return _result("power_decoupling", "unknown", "capacitor value parsing failed")
        if not any(value >= LARGE_DECOUPLING_UF for _, value in capacitors):
            return _result("power_decoupling", "fail", f"rail {rail} lacks a 10 uF capacitor")
        if not any(
            abs(value - SMALL_DECOUPLING_UF) <= SMALL_DECOUPLING_TOLERANCE_UF
            for _, value in capacitors
        ):
            return _result("power_decoupling", "fail", f"rail {rail} lacks a 100 nF capacitor")
    for capacitor in lane.components:
        if capacitor.decoupling_target is None:
            continue
        target = _component_by_refdes(lane, capacitor.decoupling_target)
        if target is None:
            return _result(
                "power_decoupling",
                "unknown",
                f"target is unresolved: {capacitor.decoupling_target}",
            )
        value = _parse_capacitance(capacitor.value)
        if value is None:
            return _result(
                "power_decoupling", "unknown", f"{capacitor.refdes} capacitance is unparseable"
            )
        shared_nets = _component_net_ids(lane, capacitor) - {ground_net}
        target_nets = _component_net_ids(lane, target)
        shared_nets &= target_nets
        if len(shared_nets) != 1:
            return _result(
                "power_decoupling", "unknown", f"{capacitor.refdes} power pad is unresolved"
            )
        try:
            distance = _minimum_pad_distance(
                graph, lane, capacitor, target, next(iter(shared_nets)), fixture
            )
        except Exception as exc:
            return _result(
                "power_decoupling", "unknown", f"{capacitor.refdes} geometry is unresolved: {exc}"
            )
        limit = SMALL_CAP_DISTANCE_MM if value <= 1.0 else LARGE_CAP_DISTANCE_MM
        if distance > limit:
            return _result(
                "power_decoupling",
                "fail",
                f"{capacitor.refdes} distance {distance:.3f} mm exceeds {limit:.1f} mm",
            )
    return _result(
        "power_decoupling", "pass", "LDO rail capacitors and pinned decoupling distances pass"
    )


def _certification_result(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    candidates: list[tuple[ComponentView, GraphNode]] = []
    for component in lane.components:
        node = next(
            (
                item
                for item in _nodes(graph, "electrical.component")
                if item.id == component.node_id
            ),
            None,
        )
        if node is None:
            return _result("module_certification", "unknown", "component graph node is missing")
        if node.attrs.get("radio_module") is True:
            candidates.append((component, node))
    if not candidates:
        return _result("module_certification", "unknown", "radio module declaration is missing")
    for component, node in candidates:
        ids = node.attrs.get("certification_ids")
        hvin = node.attrs.get("certification_hvin")
        refs = node.attrs.get("certification_document_refs")
        checked = node.attrs.get("certification_checked_at")
        if not isinstance(ids, list) or not ids:
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification provenance is incomplete",
            )
        if not all(re.fullmatch(r"[^:]+:.+", item) for item in ids):
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification identifiers are invalid",
            )
        if not isinstance(hvin, str) or not hvin or not component.mpn.startswith(hvin):
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification HVIN is invalid",
            )
        if not isinstance(refs, list) or not refs or not all(refs):
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification documents are incomplete",
            )
        if type(checked) is not str:
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification timestamp is invalid",
            )
        try:
            datetime.fromisoformat(checked.replace("Z", "+00:00"))
        except ValueError:
            return _result(
                "module_certification",
                "unknown",
                f"{component.refdes} certification timestamp is invalid",
            )
    boundary = _nodes(graph, "safety.boundary")
    if len(boundary) != 1 or boundary[0].attrs.get("module_certified") != "certified":
        return _result(
            "module_certification",
            "unknown",
            "safety boundary certification state is not certified",
        )
    return _result(
        "module_certification", "pass", "radio-module certification provenance is complete"
    )


def evaluate_power_boundary(graph: DesignGraph, lane: ElectricalLane) -> SafetyBoundaryResult:
    """Evaluate SB2 safety predicates."""
    nets = lane.nets
    if not nets or any(net.voltage_nominal_v is None for net in nets):
        voltage_5v = _result(
            "max_net_voltage_5v", "unknown", "net voltage declaration is incomplete"
        )
        voltage_external = _result(
            "max_net_voltage_external", "unknown", "net voltage declaration is incomplete"
        )
    else:
        voltages = [
            float(net.voltage_nominal_v)
            for net in nets
            if net.voltage_nominal_v is not None
        ]
        maximum = max(voltages)
        voltage_5v = _result(
            "max_net_voltage_5v",
            "pass" if maximum <= 5.0 else "fail",
            f"maximum declared net voltage is {maximum:g} V",
        )
        voltage_external = _result(
            "max_net_voltage_external",
            "pass" if maximum <= 50.0 else "fail",
            f"maximum declared net voltage is {maximum:g} V",
        )
    unknown_basis = [
        net.name
        for net in nets
        if net.width_basis not in ("current_ipc2221", "manufacturing_minimum")
    ]
    if unknown_basis:
        current = _result(
            "max_net_current",
            "unknown",
            f"unknown net width basis: {', '.join(unknown_basis)}",
        )
    else:
        power_nets = [net for net in nets if net.width_basis == "current_ipc2221"]
        missing_power_current = [net.name for net in power_nets if net.current_max_a is None]
        if missing_power_current:
            current = _result(
                "max_net_current",
                "unknown",
                f"power net current declaration is incomplete: {', '.join(missing_power_current)}",
            )
        else:
            declared_currents = [
                float(net.current_max_a)
                for net in nets
                if net.current_max_a is not None
            ]
            if not declared_currents:
                current = _result(
                    "max_net_current",
                    "unknown",
                    "power net current declaration is missing",
                )
            else:
                maximum_current = max(declared_currents)
                current = _result(
                    "max_net_current",
                    "pass" if maximum_current <= 0.5 else "fail",
                    f"maximum declared power-boundary net current is {maximum_current:g} A",
                )
    certification = _certification_result(graph, lane)
    boundary = _nodes(graph, "safety.boundary")
    if len(boundary) != 1:
        hazard = _result(
            "hazard_exclusion", "unknown", "safety boundary node is missing or ambiguous"
        )
        intended = _result(
            "intended_use", "unknown", "safety boundary node is missing or ambiguous"
        )
    else:
        attrs = boundary[0].attrs
        hazard_keys = ("battery", "charger", "motor_actuator_laser")
        if any(key not in attrs or not isinstance(attrs[key], bool) for key in hazard_keys):
            hazard = _result(
                "hazard_exclusion", "unknown", "hazard exclusion declaration is incomplete"
            )
        else:
            hazard = _result(
                "hazard_exclusion",
                "pass" if not any(bool(attrs[key]) for key in hazard_keys) else "fail",
                "hazardous energy categories are excluded",
            )
        intended_value = attrs.get("intended_use")
        if not isinstance(intended_value, str):
            intended = _result("intended_use", "unknown", "intended use is missing")
        elif intended_value == "author_prototype":
            intended = _result("intended_use", "pass", "intended use is author_prototype")
        else:
            intended = _result(
                "intended_use", "fail", "intended use is outside the permitted boundary"
            )
    return SafetyBoundaryResult.from_predicates(
        (voltage_5v, voltage_external, current, certification, hazard, intended)
    )


def evaluate_gd1_predicates(
    graph: DesignGraph, lane: ElectricalLane, fixture_dir: Path | None = None
) -> tuple[PredicateResult, ...]:
    """Evaluate the six GD1 gates in their authoritative fixed order."""
    safety = evaluate_power_boundary(graph, lane)
    return (
        evaluate_usb_cc(graph, lane),
        evaluate_i2c_pullup(graph, lane),
        evaluate_strapping_pin(graph, lane),
        evaluate_pin_firmware_alignment(graph, lane),
        evaluate_power_decoupling(graph, lane, fixture_dir),
        _result(
            "power_boundary", safety.status, "; ".join(item.detail for item in safety.predicates)
        ),
    )


__all__ = [
    "PredicateResult",
    "PredicateStatus",
    "SafetyBoundaryResult",
    "evaluate_gd1_predicates",
    "evaluate_i2c_pullup",
    "evaluate_pin_firmware_alignment",
    "evaluate_power_boundary",
    "evaluate_power_decoupling",
    "evaluate_strapping_pin",
    "evaluate_usb_cc",
]
