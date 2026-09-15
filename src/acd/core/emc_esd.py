"""Opt-in EMC/ESD design predicates.

This module performs design screening only.  It does not determine
certification compliance or replace EMC/ESD measurements.
"""

from __future__ import annotations

import math
from typing import Any

from acd.adapters.kicad.library import FootprintLibrary
from acd.core.design_predicates import (
    component_net_pad_positions,
    parse_capacitance_uf,
)
from acd.core.electrical import ComponentView, ElectricalLane
from acd.pipeline.repository import repository_root
from acd.schema import (
    EmcEsdPredicateResult,
    EmcEsdResult,
    UseEnvironment,
)
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph

EMC_RULES: dict[str, dict[str, float]] = {
    # Screening proxy: a smaller supply-loop area reduces radiated and conducted
    # noise risk; this is not an EMC certification limit.
    "usb_host": {"max_loop_area_mm2": 50.0},
    "ac_adapter_class2": {"max_loop_area_mm2": 75.0},
    "mains_direct": {"max_loop_area_mm2": 50.0},
    "battery": {"max_loop_area_mm2": 50.0},
    "poe": {"max_loop_area_mm2": 75.0},
}


def _connector(component: ComponentView) -> bool:
    return component.refdes.startswith("J") or "Connector" in component.library.footprint


def _component_net_ids(lane: ElectricalLane, component: ComponentView) -> set[str]:
    return {
        pin.net_id
        for pin in lane.pins_of_component(component.node_id)
        if pin.net_id is not None
    }


def _net_name(lane: ElectricalLane, net_id: str) -> str:
    return lane.net_by_id(net_id).name


def _placement_center(graph: DesignGraph, component_id: str) -> tuple[float, float] | None:
    node = next(
        (
            item
            for item in graph.nodes
            if item.id == component_id and item.kind == "electrical.component"
        ),
        None,
    )
    if node is None:
        return None
    x = node.attrs.get("placement_x_mm")
    y = node.attrs.get("placement_y_mm")
    if not isinstance(x, int | float) or isinstance(x, bool):
        return None
    if not isinstance(y, int | float) or isinstance(y, bool):
        return None
    return float(x), float(y)


def _external_signal_nets(lane: ElectricalLane, component: ComponentView) -> tuple[str, ...]:
    return tuple(
        net_id
        for net_id in sorted(_component_net_ids(lane, component))
        if _net_name(lane, net_id) != "GND"
        and not lane.net_by_id(net_id).power_rail
    )


def _esd_protection_result(
    lane: ElectricalLane, environment: UseEnvironment
) -> EmcEsdPredicateResult:
    subjects = [port.connector_node_id for port in environment.external_ports]
    if not environment.external_ports:
        connectors = tuple(component for component in lane.components if _connector(component))
        if connectors:
            names = ", ".join(component.refdes for component in connectors)
            return EmcEsdPredicateResult(
                predicate_id="esd_protection_external_ports",
                status="unknown",
                reason=f"external ports not declared for connectors {names}",
                subject_node_ids=[component.node_id for component in connectors],
            )
        return EmcEsdPredicateResult(
            predicate_id="esd_protection_external_ports",
            status="pass",
            reason="no external connectors declared",
        )
    failures: list[str] = []
    unknown = False
    details: dict[str, Any] = {}
    for port in environment.external_ports:
        component = next(
            (item for item in lane.components if item.node_id == port.connector_node_id),
            None,
        )
        if component is None:
            failures.append(f"connector {port.connector_node_id} is missing")
            continue
        if port.exposure == "internal":
            details[component.refdes] = "internal port"
            continue
        if port.exposure == "unknown":
            unknown = True
            details[component.refdes] = "port exposure is unknown"
            continue
        nets = _external_signal_nets(lane, component)
        missing: list[str] = []
        for net_id in nets:
            protected = any(
                candidate.esd_protection
                and net_id in _component_net_ids(lane, candidate)
                and candidate.node_id != component.node_id
                for candidate in lane.components
            )
            if not protected:
                missing.append(_net_name(lane, net_id))
        details[component.refdes] = {"signal_nets": [_net_name(lane, net) for net in nets]}
        if missing:
            failures.append(f"{component.refdes} lacks ESD protection on {', '.join(missing)}")
    if failures:
        return EmcEsdPredicateResult(
            predicate_id="esd_protection_external_ports",
            status="fail",
            reason="; ".join(failures),
            subject_node_ids=list(dict.fromkeys(subjects)),
            details=details,
        )
    if unknown:
        return EmcEsdPredicateResult(
            predicate_id="esd_protection_external_ports",
            status="unknown",
            reason="external port exposure is unknown",
            subject_node_ids=list(dict.fromkeys(subjects)),
            details=details,
        )
    return EmcEsdPredicateResult(
        predicate_id="esd_protection_external_ports",
        status="pass",
        reason="all declared user-accessible port signal nets have ESD protection",
        subject_node_ids=list(dict.fromkeys(subjects)),
        details=details,
    )


def _power_loop_result(
    graph: DesignGraph, lane: ElectricalLane, environment: UseEnvironment
) -> EmcEsdPredicateResult:
    rule = EMC_RULES.get(environment.power_system)
    if rule is None:
        return EmcEsdPredicateResult(
            predicate_id="power_loop_area",
            status="unknown",
            reason="power system is unknown; EMC loop threshold cannot be selected",
        )
    ground = next((net.node_id for net in lane.nets if net.name == "GND"), None)
    if ground is None:
        return EmcEsdPredicateResult(
            predicate_id="power_loop_area",
            status="unknown",
            reason="ground net is not declared",
        )
    library = FootprintLibrary()
    details: dict[str, Any] = {"threshold_mm2": rule["max_loop_area_mm2"], "rails": {}}
    unknown = False
    failures: list[str] = []
    for rail in (net for net in lane.nets if net.power_rail):
        if rail.power_source_pin is None:
            unknown = True
            details["rails"][rail.name] = "power source pin is not declared"
            continue
        source_pin = next(
            (pin for pin in lane.pins if pin.node_id == rail.power_source_pin),
            None,
        )
        if source_pin is None:
            unknown = True
            details["rails"][rail.name] = "power source pin is unresolved"
            continue
        source = lane.component_by_id(source_pin.component_id)
        capacitors = tuple(
            (component, parse_capacitance_uf(component.value))
            for component in lane.components
            if _component_net_ids(lane, component) == {rail.node_id, ground}
        )
        if not capacitors:
            failures.append(f"{rail.name} has no rail-to-ground capacitor")
            continue
        rail_details: list[dict[str, Any]] = []
        rail_max = 0.0
        for capacitor, value in capacitors:
            if value is None:
                unknown = True
                rail_details.append({"component": capacitor.refdes, "status": "value unknown"})
                continue
            try:
                source_positions = component_net_pad_positions(
                    graph,
                    lane,
                    source,
                    rail.node_id,
                    repository_root(),
                    library,
                )
                cap_positions = component_net_pad_positions(
                    graph,
                    lane,
                    capacitor,
                    rail.node_id,
                    repository_root(),
                    library,
                )
                distance = min(
                    math.dist(source_position, cap_position)
                    for _, source_position in source_positions
                    for _, cap_position in cap_positions
                )
            except (OSError, ValueError, KeyError):
                unknown = True
                source_center = _placement_center(graph, source.node_id)
                capacitor_center = _placement_center(graph, capacitor.node_id)
                if source_center is not None and capacitor_center is not None:
                    area = (
                        math.dist(source_center, capacitor_center)
                        * lane.board.thickness_mm
                    )
                    rail_details.append(
                        {
                            "component": capacitor.refdes,
                            "loop_area_proxy_mm2": round(area, 6),
                            "geometry_basis": "placement centers; pad geometry unavailable",
                        }
                    )
                else:
                    rail_details.append(
                        {"component": capacitor.refdes, "status": "placement unavailable"}
                    )
                continue
            return_thickness = lane.board.thickness_mm
            if lane.stackup is not None:
                return_thickness = min(
                    layer.thickness_mm
                    for layer in lane.stackup.layers
                    if layer.kind == "dielectric"
                )
            area = distance * return_thickness
            rail_max = max(rail_max, area)
            rail_details.append(
                {
                    "component": capacitor.refdes,
                    "capacitance_uf": value,
                    "distance_mm": round(distance, 6),
                    "return_thickness_mm": return_thickness,
                    "loop_area_proxy_mm2": round(area, 6),
                }
            )
        details["rails"][rail.name] = rail_details
        if rail_max > rule["max_loop_area_mm2"]:
            failures.append(
                f"{rail.name} loop area proxy {rail_max:.3f} mm2 exceeds "
                f"{rule['max_loop_area_mm2']:.3f} mm2"
            )
    if failures:
        return EmcEsdPredicateResult(
            predicate_id="power_loop_area",
            status="fail",
            reason="; ".join(failures),
            details=details,
        )
    if unknown:
        return EmcEsdPredicateResult(
            predicate_id="power_loop_area",
            status="unknown",
            reason="power loop placement or declared geometry is incomplete",
            details=details,
        )
    return EmcEsdPredicateResult(
        predicate_id="power_loop_area",
        status="pass",
        reason="declared power loop area proxies are within threshold",
        details=details,
    )


def _adjacent_ground_plane(lane: ElectricalLane, routing_layer: str) -> bool | None:
    if lane.stackup is None:
        return any(layer != routing_layer for layer in lane.board.ground_plane_layers)
    layers = lane.stackup.layers
    try:
        routing_index = next(
            index for index, layer in enumerate(layers) if layer.name == routing_layer
        )
    except StopIteration:
        return None
    for index, layer in enumerate(layers):
        if layer.name not in lane.board.ground_plane_layers or layer.kind != "plane":
            continue
        between = layers[min(index, routing_index) + 1 : max(index, routing_index)]
        if between and all(item.kind == "dielectric" for item in between):
            return True
    return False


def _return_path_result(
    lane: ElectricalLane, environment: UseEnvironment
) -> EmcEsdPredicateResult:
    if not lane.board.ground_plane_net or not lane.board.ground_plane_layers:
        return EmcEsdPredicateResult(
            predicate_id="return_path_continuity",
            status="unknown",
            reason="no ground plane declared",
        )
    subjects: list[str] = []
    unknown = False
    failures: list[str] = []
    details: dict[str, Any] = {}
    for port in environment.external_ports:
        if port.exposure != "user_accessible":
            continue
        component = next(
            (item for item in lane.components if item.node_id == port.connector_node_id),
            None,
        )
        if component is None:
            failures.append(f"connector {port.connector_node_id} is missing")
            continue
        for net_id in _external_signal_nets(lane, component):
            net = lane.net_by_id(net_id)
            subjects.extend((component.node_id, net_id))
            routing_layer = net.impedance_routing_layer or "F.Cu"
            adjacent = _adjacent_ground_plane(lane, routing_layer)
            details[_net_name(lane, net_id)] = {
                "routing_layer": routing_layer,
                "adjacent": adjacent,
            }
            if adjacent is None:
                unknown = True
            elif not adjacent:
                failures.append(
                    f"{_net_name(lane, net_id)} routing layer {routing_layer} "
                    "lacks adjacent ground plane"
                )
    if failures:
        return EmcEsdPredicateResult(
            predicate_id="return_path_continuity",
            status="fail",
            reason="; ".join(failures),
            subject_node_ids=list(dict.fromkeys(subjects)),
            details=details,
        )
    if unknown:
        return EmcEsdPredicateResult(
            predicate_id="return_path_continuity",
            status="unknown",
            reason="routing layer or stackup adjacency is unknown",
            subject_node_ids=list(dict.fromkeys(subjects)),
            details=details,
        )
    return EmcEsdPredicateResult(
        predicate_id="return_path_continuity",
        status="pass",
        reason="external signal return paths have adjacent ground planes",
        subject_node_ids=list(dict.fromkeys(subjects)),
        details=details,
    )


def _environment_result(environment: UseEnvironment) -> EmcEsdPredicateResult:
    unknown_fields = [
        name
        for name, value in (
            ("installation", environment.installation),
            ("power_system", environment.power_system),
            ("vibration", environment.vibration),
        )
        if value == "unknown"
    ]
    if unknown_fields:
        return EmcEsdPredicateResult(
            predicate_id="environment_derating_inputs",
            status="unknown",
            reason=f"environment fields are unknown: {', '.join(unknown_fields)}",
        )
    return EmcEsdPredicateResult(
        predicate_id="environment_derating_inputs",
        status="pass",
        reason="temperature, humidity, installation, power system, and vibration are declared",
        details={
            "temperature_c": environment.temperature_c.model_dump(mode="json"),
            "humidity_rh_pct": environment.humidity_rh_pct.model_dump(mode="json"),
        },
    )


def evaluate_emc_esd(
    graph: DesignGraph, lane: ElectricalLane, environment: UseEnvironment
) -> EmcEsdResult:
    """Evaluate the opt-in EMC/ESD screening predicates."""
    if environment.graph_id != graph.graph_id or environment.revision != graph.revision:
        raise ValueError("use environment graph_id/revision does not match graph")
    predicates = [
        _esd_protection_result(lane, environment),
        _power_loop_result(graph, lane, environment),
        _return_path_result(lane, environment),
        _environment_result(environment),
    ]
    statuses = {predicate.status for predicate in predicates}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return EmcEsdResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        predicates=predicates,
        input_hashes={
            "graph": canonical_sha256(graph),
            "environment": canonical_sha256(environment),
        },
    )
