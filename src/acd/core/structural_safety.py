"""Deterministic structural-safety predicates."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from itertools import combinations, pairwise
from typing import cast

from acd.core.design_predicates import (
    PredicateMeasurement,
    PredicateResult,
    PredicateStatus,
    PredicateSubject,
)
from acd.core.electrical import ElectricalLane
from acd.schema.design_graph import DesignGraph, GraphNode

FORBIDDEN_RESOURCES = frozenset(
    {"connector", "harness", "power_bus", "ic", "via", "thermal_path", "protection_device"}
)
SIGNAL_CLASSES = frozenset(
    {
        "safety_extra_low_voltage",
        "mains",
        "analog_sensitive",
        "high_speed",
        "power",
        "digital",
    }
)
# Fixed incompatibilities are deliberately conservative connector/placement rules.
INCOMPATIBLE_SIGNAL_CLASS_PAIRS = frozenset(
    {
        frozenset({"mains", signal_class})
        for signal_class in SIGNAL_CLASSES
        if signal_class != "mains"
    }
    | {
        frozenset({"analog_sensitive", "high_speed"}),
        frozenset({"analog_sensitive", "power"}),
    }
)
PROTECTION_ROLES = frozenset({"fuse", "efuse", "polyfuse", "tvs", "current_limit"})
PASSIVE_FAMILY_RE = re.compile(r"(?:resistor|capacitor|diode|^r\d|^c\d|^d\d)", re.I)
# IPC-2221 empirical constants for external and internal conductors. These
# approximations are engineering estimates, not certification evidence.
IPC2221_K = {"external": 0.048, "internal": 0.024}


def _nodes(graph: DesignGraph, kind: str) -> tuple[GraphNode, ...]:
    return tuple(node for node in graph.nodes if node.kind == kind)


def _node(graph: DesignGraph, node_id: str) -> GraphNode | None:
    return next((node for node in graph.nodes if node.id == node_id), None)


def _attrs(graph: DesignGraph, node_id: str) -> Mapping[str, object]:
    node = _node(graph, node_id)
    return node.attrs if node is not None else {}


def _pins(graph: DesignGraph, lane: ElectricalLane, member: str):
    node = _node(graph, member)
    if node is None:
        return ()
    if node.kind == "electrical.net":
        return tuple(pin for pin in lane.pins if pin.net_id == member)
    if node.kind == "electrical.component":
        return tuple(pin for pin in lane.pins if pin.component_id == member)
    return ()


def _member_net_ids(graph: DesignGraph, lane: ElectricalLane, member: str) -> set[str]:
    node = _node(graph, member)
    if node is None:
        return set()
    if node.kind == "electrical.net":
        return {member}
    return {pin.net_id for pin in _pins(graph, lane, member) if pin.net_id is not None}


def _is_connector(node: GraphNode) -> bool:
    refdes = node.attrs.get("refdes")
    footprint = node.attrs.get("footprint")
    symbol = node.attrs.get("symbol")
    return (
        isinstance(refdes, str)
        and refdes.upper().startswith("J")
    ) or any(
        isinstance(value, str) and value.startswith("Connector")
        for value in (footprint, symbol)
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    values: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            return None
        values.append(item)
    return tuple(values)


def _result(
    name: str,
    status: PredicateStatus,
    detail: str,
    *,
    measurements: tuple[PredicateMeasurement, ...] = (),
    subjects: tuple[PredicateSubject, ...] = (),
) -> PredicateResult:
    return PredicateResult(
        name=name,
        status=status,
        detail=detail,
        measurements=measurements,
        subjects=subjects,
    )


def _resource_ids(
    resource: str,
    member: str,
    graph: DesignGraph,
    lane: ElectricalLane,
) -> tuple[set[str], bool]:
    """Return resource IDs and whether the resource is graph-observable."""
    if resource in {"harness", "via"}:
        return set(), False
    net_ids = _member_net_ids(graph, lane, member)
    member_node = _node(graph, member)
    component_ids = {
        pin.component_id
        for net_id in net_ids
        for pin in lane.pins
        if pin.net_id == net_id
    }
    if member_node is not None and member_node.kind == "electrical.component":
        component_ids.add(member)
    if resource == "connector":
        return {
            component_id
            for component_id in component_ids
            if (component := _node(graph, component_id)) is not None
            and _is_connector(component)
        }, True
    if resource == "power_bus":
        return {
            net_id
            for net_id in net_ids
            if _attrs(graph, net_id).get("power_rail") is True
        }, True
    if resource == "ic":
        return {
            component_id
            for component_id in component_ids
            if (component := _node(graph, component_id)) is not None
            and not _is_connector(component)
            and (
                str(component.attrs.get("refdes", "")).upper().startswith("U")
                or "ic" in str(component.attrs.get("value", "")).casefold()
            )
        }, True
    if resource == "thermal_path":
        values = {
            value
            for node_id in (member, *sorted(component_ids), *sorted(net_ids))
            if isinstance(value := _attrs(graph, node_id).get("thermal_path_id"), str)
        }
        return values, True
    if resource == "protection_device":
        return {
            component_id
            for component_id in component_ids
            if _attrs(graph, component_id).get("protection_role") in PROTECTION_ROLES
            or _attrs(graph, component_id).get("protection_device") is True
        }, True
    return set(), False


def evaluate_single_point_of_failure(
    graph: DesignGraph, lane: ElectricalLane
) -> PredicateResult:
    groups = _nodes(graph, "safety.redundant_group")
    if not groups:
        return _result(
            "single_point_of_failure",
            "unknown",
            "redundant group scope is not declared",
        )
    failures: list[str] = []
    unknowns: list[str] = []
    for group in groups:
        members = _string_list(group.attrs.get("members"))
        forbidden = _string_list(group.attrs.get("resources_shared_forbidden"))
        if not members or not forbidden or any(
            item not in FORBIDDEN_RESOURCES for item in forbidden
        ):
            unknowns.append(f"{group.id} has an invalid resource declaration")
            continue
        missing = sorted(member for member in members if _node(graph, member) is None)
        if missing:
            failures.append(f"{group.id} members not found: {', '.join(missing)}")
            continue
        for resource in forbidden:
            for left, right in combinations(members, 2):
                left_ids, left_known = _resource_ids(resource, left, graph, lane)
                right_ids, right_known = _resource_ids(resource, right, graph, lane)
                if not left_known or not right_known:
                    unknowns.append(f"{group.id} cannot observe shared {resource} data")
                    continue
                shared = sorted(left_ids & right_ids)
                if shared:
                    failures.append(
                        f"{group.id} members {left}/{right} share {resource}: {', '.join(shared)}"
                    )
    if failures:
        return _result("single_point_of_failure", "fail", "; ".join(sorted(failures)))
    if unknowns:
        return _result("single_point_of_failure", "unknown", "; ".join(sorted(set(unknowns))))
    return _result(
        "single_point_of_failure",
        "pass",
        "declared redundant paths have no forbidden shared resources",
    )


def _protection_components(graph: DesignGraph) -> tuple[GraphNode, ...]:
    return tuple(
        node
        for node in _nodes(graph, "electrical.component")
        if node.attrs.get("protection_role") in PROTECTION_ROLES
    )


def _component_power_net(node: GraphNode, key: str) -> str | None:
    value = node.attrs.get(key)
    return value if isinstance(value, str) and value else None


def evaluate_protection_selectivity(
    graph: DesignGraph, lane: ElectricalLane
) -> PredicateResult:
    protections = _protection_components(graph)
    required_rails = [
        node
        for node in _nodes(graph, "electrical.net")
        if node.attrs.get("power_rail") is True
        and node.attrs.get("requires_protection") is True
    ]
    if not protections:
        if required_rails:
            return _result(
                "protection_selectivity",
                "fail",
                "rails require protection but no protection devices are declared: "
                + ", ".join(sorted(node.id for node in required_rails)),
            )
        return _result(
            "protection_selectivity",
            "unknown",
            "protection device scope is not declared",
        )
    missing_trip = [
        node.id
        for node in protections
        if _number(node.attrs.get("trip_current_a")) is None
    ]
    if missing_trip:
        return _result(
            "protection_selectivity",
            "unknown",
            "trip_current_a is missing for: " + ", ".join(sorted(missing_trip)),
        )
    failures: list[str] = []
    for node in protections:
        if node.attrs.get("protects_component_id") == node.id:
            failures.append(
                f"protection device {node.id} and protected function are the same component"
            )
    rail_nodes = [
        node for node in _nodes(graph, "electrical.net") if node.attrs.get("power_rail") is True
    ]
    for rail in rail_nodes:
        if rail.attrs.get("requires_protection") is not True:
            continue
        candidates = [
            node
            for node in protections
            if _component_power_net(node, "power_input_net") == rail.id
            or rail.id in {
                pin.net_id
                for pin in lane.pins
                if pin.component_id == node.id and pin.net_id is not None
            }
        ]
        if not candidates:
            failures.append(f"rail {rail.id} requires protection but has no upstream protection")
    for upstream, downstream in combinations(protections, 2):
        upstream_out = _component_power_net(upstream, "power_output_net")
        downstream_in = _component_power_net(downstream, "power_input_net")
        if upstream_out is None or downstream_in is None or upstream_out != downstream_in:
            continue
        upstream_trip = _number(upstream.attrs.get("trip_current_a"))
        downstream_trip = _number(downstream.attrs.get("trip_current_a"))
        assert upstream_trip is not None and downstream_trip is not None
        if downstream_trip >= upstream_trip:
            failures.append(
                f"downstream {downstream.id} trip {downstream_trip:g} A is not below "
                f"upstream {upstream.id} trip {upstream_trip:g} A"
            )
    if failures:
        return _result("protection_selectivity", "fail", "; ".join(sorted(failures)))
    return _result(
        "protection_selectivity",
        "pass",
        "declared protection devices have selective downstream trip values",
    )


def _component_net_classes(
    graph: DesignGraph, lane: ElectricalLane, component_id: str
) -> set[str]:
    return {
        str(_attrs(graph, pin.net_id).get("signal_class"))
        for pin in lane.pins
        if pin.component_id == component_id
        and pin.net_id is not None
        and _attrs(graph, pin.net_id).get("signal_class") in SIGNAL_CLASSES
    }


def _position(node: GraphNode) -> tuple[float, float] | None:
    x = _number(node.attrs.get("placement_x_mm"))
    y = _number(node.attrs.get("placement_y_mm"))
    return (x, y) if x is not None and y is not None else None


def evaluate_signal_class_segregation(
    graph: DesignGraph, lane: ElectricalLane
) -> PredicateResult:
    classes: dict[str, str] = {}
    for node in _nodes(graph, "electrical.net"):
        signal_class = node.attrs.get("signal_class")
        if isinstance(signal_class, str) and signal_class in SIGNAL_CLASSES:
            classes[node.id] = signal_class
    if not classes:
        return _result(
            "signal_class_segregation",
            "unknown",
            "signal classes are not declared",
        )
    failures: list[str] = []
    for connector in (
        node for node in _nodes(graph, "electrical.component") if _is_connector(node)
    ):
        connector_classes = [
            (pin.pad, classes[pin.net_id])
            for pin in lane.pins
            if pin.component_id == connector.id and pin.net_id in classes
        ]
        if any(signal_class == "mains" for _, signal_class in connector_classes) and any(
            signal_class != "mains" for _, signal_class in connector_classes
        ):
            failures.append(f"connector {connector.id} mixes mains and non-mains nets")
        ordered = sorted(connector_classes, key=lambda item: item[0])
        for (left_pad, left_class), (right_pad, right_class) in pairwise(ordered):
            if frozenset({left_class, right_class}) in INCOMPATIBLE_SIGNAL_CLASS_PAIRS:
                failures.append(
                    f"connector {connector.id} adjacent pads {left_pad}/{right_pad} "
                    f"mix {left_class}/{right_class}"
                )
    mains = {
        component.id
        for component in _nodes(graph, "electrical.component")
        if _component_net_classes(graph, lane, component.id) == {"mains"}
    }
    selv = {
        component.id
        for component in _nodes(graph, "electrical.component")
        if "safety_extra_low_voltage" in _component_net_classes(graph, lane, component.id)
        and _component_net_classes(graph, lane, component.id) <= {"safety_extra_low_voltage"}
    }
    if mains and selv:
        boundary = next(iter(_nodes(graph, "safety.boundary")), None)
        threshold = _number(boundary.attrs.get("min_segregation_mm")) if boundary else None
        if threshold is None:
            return _result(
                "signal_class_segregation",
                "unknown",
                "min_segregation_mm is missing for mains/SELV placement segregation",
            )
        for left, right in combinations(sorted(mains), 2):
            _ = (left, right)
        for mains_id in sorted(mains):
            for selv_id in sorted(selv):
                mains_node = _node(graph, mains_id)
                selv_node = _node(graph, selv_id)
                left = _position(mains_node) if mains_node else None
                right = _position(selv_node) if selv_node else None
                if left is None or right is None:
                    return _result(
                        "signal_class_segregation",
                        "unknown",
                        "component placement is missing for mains/SELV segregation",
                    )
                distance = math.dist(left, right)
                if distance < threshold:
                    failures.append(
                        f"mains component {mains_id} is {distance:.3f} mm from SELV {selv_id}"
                    )
    if failures:
        return _result("signal_class_segregation", "fail", "; ".join(sorted(failures)))
    return _result(
        "signal_class_segregation",
        "pass",
        "declared signal classes satisfy connector and placement segregation rules",
    )


def _is_passive(node: GraphNode) -> bool:
    values = (
        str(node.attrs.get("refdes", "")),
        str(node.attrs.get("value", "")),
        str(node.attrs.get("footprint", "")),
        str(node.attrs.get("symbol", "")),
    )
    return any(PASSIVE_FAMILY_RE.search(value) for value in values)


def evaluate_sneak_path(graph: DesignGraph, lane: ElectricalLane) -> PredicateResult:
    critical = [
        node for node in _nodes(graph, "electrical.net") if node.attrs.get("critical") is True
    ]
    if not critical:
        return _result("sneak_path", "unknown", "critical net scope is not declared")
    failures: list[str] = []
    unknowns: list[str] = []
    state_names: set[str] = set()
    for node in _nodes(graph, "firmware.state"):
        state_name = node.attrs.get("state_name")
        if isinstance(state_name, str):
            state_names.add(state_name)
    for net in critical:
        intended = _string_list(net.attrs.get("intended_coupling")) or ()
        for component in _nodes(graph, "electrical.component"):
            connected = sorted(
                {
                    pin.net_id
                    for pin in lane.pins
                    if pin.component_id == component.id and pin.net_id is not None
                }
            )
            other = [net_id for net_id in connected if net_id != net.id]
            if (
                net.id not in connected
                or not other
                or len(connected) < 2
                or not _is_passive(component)
            ):
                continue
            undeclared = [net_id for net_id in other if net_id not in intended]
            if undeclared:
                failures.append(
                    f"critical net {net.id} bridges through {component.id} "
                    f"without intended_coupling: {', '.join(undeclared)}"
                )
        for component in _nodes(graph, "electrical.component"):
            if not (
                component.attrs.get("led_indicator") is True
                or str(component.attrs.get("refdes", "")).upper().startswith("D")
            ):
                continue
            if not any(
                pin.component_id == component.id and pin.net_id == net.id for pin in lane.pins
            ):
                continue
            label = component.attrs.get("indicator_state_label")
            if not isinstance(label, str) or not label:
                unknowns.append(f"{component.id} indicator_state_label is missing")
            elif label not in state_names:
                failures.append(
                    f"critical net {net.id} indicator {component.id} has unknown state {label}"
                )
    critical_components = {
        pin.component_id
        for net in critical
        for pin in lane.pins
        if pin.net_id == net.id
    }
    for connector_id in sorted(
        component_id
        for component_id in critical_components
        if (component := _node(graph, component_id)) is not None and _is_connector(component)
    ):
        labels = [
            node
            for node in _nodes(graph, "mechanical.silk_text")
            if node.attrs.get("placement_reference") == _attrs(graph, connector_id).get("refdes")
        ]
        if not labels:
            unknowns.append(f"critical connector {connector_id} has no declared silk label")
        for label_node in labels:
            label = label_node.attrs.get("label")
            expected = _attrs(graph, connector_id).get("refdes")
            if not isinstance(label, str) or not isinstance(expected, str):
                unknowns.append(f"critical connector {connector_id} silk label is undeclared")
            elif label != expected:
                failures.append(
                    f"critical connector {connector_id} silk label {label!r} "
                    f"does not match {expected!r}"
                )
    if failures:
        return _result("sneak_path", "fail", "; ".join(sorted(failures)))
    if unknowns:
        return _result("sneak_path", "unknown", "; ".join(sorted(set(unknowns))))
    return _result("sneak_path", "pass", "critical nets have declared coupling and indicator paths")


def _copper_um(graph: DesignGraph, lane: ElectricalLane, net: GraphNode) -> float | None:
    route_layer = net.attrs.get("routing_layer") or net.attrs.get("impedance_routing_layer")
    if isinstance(route_layer, str) and lane.stackup is not None:
        for layer in lane.stackup.layers:
            if layer.name == route_layer:
                return float(layer.copper_um) if layer.copper_um is not None else None
    board = _node(graph, lane.board.node_id)
    if board is None:
        return None
    return _number(
        board.attrs.get("copper_um") or board.attrs.get("outer_copper_thickness_um")
    )


def evaluate_trapezoid_current_capacity(
    graph: DesignGraph, lane: ElectricalLane
) -> PredicateResult:
    targets = [
        node
        for node in _nodes(graph, "electrical.net")
        if _number(node.attrs.get("current_max_a")) is not None
        and node.attrs.get("width_basis") == "current_ipc2221"
    ]
    if not targets:
        return _result(
            "trapezoid_current_capacity",
            "unknown",
            "current capacity scope is not declared",
        )
    failures: list[str] = []
    unknowns: list[str] = []
    measurements: list[PredicateMeasurement] = []
    calculation_details: list[str] = []
    board = _node(graph, lane.board.node_id)
    for net in targets:
        current = _number(net.attrs.get("current_max_a"))
        width = _number(net.attrs.get("min_trace_width_mm") or net.attrs.get("trace_width_mm"))
        copper = _copper_um(graph, lane, net)
        etch = _number(net.attrs.get("etch_factor"))
        if etch is None and board is not None:
            etch = _number(board.attrs.get("etch_factor"))
        delta_t = _number(net.attrs.get("max_temperature_rise_c"))
        if current is None or width is None or copper is None or etch is None or delta_t is None:
            unknowns.append(
                f"{net.id} requires current, trace width, copper, etch factor, and temperature rise"
            )
            continue
        top_width_mm = width - 2.0 * etch * (copper / 1000.0)
        if top_width_mm <= 0:
            failures.append(f"{net.id} has non-positive etched conductor width")
            continue
        area_mil2 = top_width_mm * 39.37007874 * (copper / 25.4)
        route_layer = net.attrs.get("routing_layer") or net.attrs.get("impedance_routing_layer")
        layer_kind = "external"
        if isinstance(route_layer, str) and route_layer not in {"F.Cu", "B.Cu"}:
            layer_kind = "internal"
        capacity = IPC2221_K[layer_kind] * delta_t**0.44 * area_mil2**0.725
        measurements.append(
            PredicateMeasurement(
                measured=capacity,
                limit=current,
                quantity=f"{net.id} trapezoid capacity",
                comparison=">=",
                unit="A",
                margin=capacity - current,
                excess=max(0.0, current - capacity),
                subject=PredicateSubject(net=net.id),
            )
        )
        calculation_details.append(
            f"{net.id}: width={width:.3f} mm, copper={copper:.1f} um, "
            f"etch_factor={etch:.3f}, deltaT={delta_t:.3f} C, "
            f"area={area_mil2:.3f} mil2, capacity={capacity:.3f} A, "
            f"required={current:.3f} A"
        )
        if capacity < current:
            failures.append(
                f"{net.id} capacity {capacity:.3f} A is below required {current:.3f} A"
            )
    if failures:
        return _result(
            "trapezoid_current_capacity",
            "fail",
            "; ".join([*sorted(failures), *calculation_details]),
            measurements=tuple(measurements),
        )
    if unknowns:
        return _result(
            "trapezoid_current_capacity",
            "unknown",
            "; ".join([*sorted(unknowns), *calculation_details]),
            measurements=tuple(measurements),
        )
    return _result(
        "trapezoid_current_capacity",
        "pass",
        "; ".join(
            [
                "all declared current-carrying conductors meet IPC-2221 trapezoid capacity",
                *calculation_details,
            ]
        ),
        measurements=tuple(measurements),
    )


__all__ = [
    "evaluate_protection_selectivity",
    "evaluate_signal_class_segregation",
    "evaluate_single_point_of_failure",
    "evaluate_sneak_path",
    "evaluate_trapezoid_current_capacity",
]
