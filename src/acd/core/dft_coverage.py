"""Deterministic opt-in design-for-test coverage checks."""

from __future__ import annotations

import math
import re
from itertools import combinations
from typing import Any

from acd.core.electrical import ComponentView, ElectricalLane
from acd.schema import DftCheckResult, DftCoverageResult, DftCoverageSet, DftPolicy
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.dft_coverage import DftCoverageStatus

_DIAMETER_RE = re.compile(r"(?:^|_)D([0-9]+(?:\.[0-9]+)?)mm(?:$|_)", re.IGNORECASE)
_USB_NAMES = frozenset({"D+", "D-", "DP", "DN", "USB_D+", "USB_D-", "USB_DP", "USB_DN"})


def _net_ids_from_assignments(graph: DesignGraph) -> set[str]:
    return {
        value
        for node in graph.nodes
        if node.kind == "firmware.pin_assignment"
        for value in (node.attrs.get("net"),)
        if isinstance(value, str)
    }


def _assignment_has_uart(node: GraphNode) -> bool:
    values = (
        node.id,
        node.attrs.get("role"),
        node.attrs.get("peripheral"),
        node.attrs.get("function"),
    )
    return any(isinstance(value, str) and "uart" in value.lower() for value in values)


def _classify_nets(graph: DesignGraph, lane: ElectricalLane) -> dict[str, set[str]]:
    power = {net.node_id for net in lane.nets if net.power_rail}
    ground = {
        net.node_id
        for net in lane.nets
        if net.name == "GND" or net.node_id == lane.board.ground_plane_net
    }
    i2c: set[str] = set()
    for component in lane.components:
        for pin in lane.pins_of_component(component.node_id):
            function = component.cpl_rotation_pin_functions.get(pin.pad, "").lower()
            if pin.net_id is not None and ("sda" in function or "scl" in function):
                i2c.add(pin.net_id)
    assignments = tuple(
        node for node in graph.nodes if node.kind == "firmware.pin_assignment"
    )
    firmware = _net_ids_from_assignments(graph)
    uart = {
        value
        for node in assignments
        if _assignment_has_uart(node)
        for value in (node.attrs.get("net"),)
        if isinstance(value, str)
    }
    usb = {
        net.node_id
        for net in lane.nets
        if net.name.upper() in _USB_NAMES
        or ("usb" in (net.differential_pair or "").lower())
    }
    non_power_ground = power | ground
    all_signals = {
        net.node_id for net in lane.nets if net.node_id not in non_power_ground
    }
    return {
        "power_rail": power,
        "ground": ground,
        "i2c": i2c,
        "uart": uart,
        "gpio_firmware": firmware,
        "usb_data": usb,
        "all_signals": all_signals,
    }


def _test_points(lane: ElectricalLane) -> tuple[ComponentView, ...]:
    return tuple(
        component
        for component in lane.components
        if component.test_point
        or component.library.footprint.lower().startswith("testpoint:")
        or component.library.symbol.lower() == "connector:testpoint"
    )


def _body_by_component(graph: DesignGraph) -> dict[str, GraphNode]:
    component_ids = {node.id for node in graph.nodes if node.kind == "electrical.component"}
    return {
        dependency: node
        for node in graph.nodes
        if node.kind == "mechanical.component_body"
        for dependency in node.depends_on
        if dependency in component_ids
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _center(graph: DesignGraph, component_id: str) -> tuple[float, float] | None:
    node = next(
        (item for item in graph.nodes if item.id == component_id),
        None,
    )
    if node is None:
        return None
    x = _number(node.attrs.get("placement_x_mm"))
    y = _number(node.attrs.get("placement_y_mm"))
    if x is None or y is None:
        return None
    offset_x = _number(node.attrs.get("pad_offset_x_mm")) or 0.0
    offset_y = _number(node.attrs.get("pad_offset_y_mm")) or 0.0
    rotation = math.radians(_number(node.attrs.get("placement_rotation_deg")) or 0.0)
    x += offset_x * math.cos(rotation) - offset_y * math.sin(rotation)
    y += offset_x * math.sin(rotation) + offset_y * math.cos(rotation)
    return x, y


def _pad_diameter_info(
    graph: DesignGraph,
    component: ComponentView,
) -> tuple[float | None, str]:
    node = next((item for item in graph.nodes if item.id == component.node_id), None)
    if node is None:
        return None, "component node unavailable"
    declared = _number(node.attrs.get("pad_diameter_mm"))
    if declared is not None and declared > 0:
        return declared, "component attr pad_diameter_mm"
    match = _DIAMETER_RE.search(component.library.footprint.rsplit(":", 1)[-1])
    if match is None:
        return None, "unparseable footprint"
    return float(match.group(1)), "footprint name"


def _side(
    graph: DesignGraph,
    component: ComponentView,
    bodies: dict[str, GraphNode],
) -> str | None:
    node = next((item for item in graph.nodes if item.id == component.node_id), None)
    if node is None:
        return None
    for key in ("side", "layer"):
        value = node.attrs.get(key)
        if isinstance(value, str) and value:
            return _normalize_side(value)
    body = bodies.get(component.node_id)
    if body is not None:
        value = body.attrs.get("mounting_side")
        if isinstance(value, str) and value:
            return _normalize_side(value)
    return None


def _normalize_side(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"top", "front", "f.cu"}:
        return "top"
    if lowered in {"bottom", "back", "b.cu"}:
        return "bottom"
    return lowered


def _body_rectangles(
    graph: DesignGraph,
    lane: ElectricalLane,
    test_point_ids: set[str],
) -> dict[str, tuple[float, float, float, float]]:
    component_ids = {component.node_id for component in lane.components}
    components = {
        component.id: component
        for component in graph.nodes
        if component.kind == "electrical.component"
    }
    rectangles: dict[str, tuple[float, float, float, float]] = {}
    for body in graph.nodes:
        if body.kind != "mechanical.component_body":
            continue
        if body.attrs.get("body_type") == "none":
            continue
        component_id = next(
            (dependency for dependency in body.depends_on if dependency in component_ids),
            None,
        )
        if component_id is None or component_id in test_point_ids:
            continue
        width = _number(body.attrs.get("width_mm"))
        height = _number(body.attrs.get("depth_mm"))
        component = components[component_id]
        x = _number(component.attrs.get("placement_x_mm"))
        y = _number(component.attrs.get("placement_y_mm"))
        rotation = _number(component.attrs.get("placement_rotation_deg"))
        x = x if x is not None else _number(body.attrs.get("x_mm"))
        y = y if y is not None else _number(body.attrs.get("y_mm"))
        rotation = (
            rotation if rotation is not None else _number(body.attrs.get("rotation_deg"))
        )
        if width is None or height is None or x is None or y is None or rotation is None:
            continue
        if round(rotation) % 180 == 90:
            width, height = height, width
        rectangles[component_id] = (x, y, width, height)
    return rectangles


def _point_to_rect_distance(
    point: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float:
    x, y = point
    rx, ry, width, height = rect
    return math.hypot(
        max(abs(x - rx) - width / 2.0, 0.0),
        max(abs(y - ry) - height / 2.0, 0.0),
    )


def _check(
    check_id: str,
    status: DftCoverageStatus,
    reason: str,
    subjects: list[str] | tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
) -> DftCheckResult:
    return DftCheckResult(
        check_id=check_id,
        status=status,
        reason=reason,
        subject_node_ids=sorted(set(subjects)),
        details=details or {},
    )


def evaluate_dft_coverage(
    graph: DesignGraph,
    lane: ElectricalLane,
    policy: DftPolicy,
) -> DftCoverageResult:
    """Evaluate declared test-point coverage and probe accessibility."""
    if graph.graph_id != policy.graph_id or graph.revision != policy.revision:
        raise ValueError("DFT policy graph_id/revision does not match graph")

    classifications = _classify_nets(graph, lane)
    required: set[str] = set(policy.required_net_ids)
    unresolved_classes: list[str] = []
    for net_class in policy.required_net_classes:
        selected = classifications[net_class]
        if not selected:
            unresolved_classes.append(net_class)
        required.update(selected)
    required_nets = sorted(required)
    test_points = _test_points(lane)
    test_point_ids = {component.node_id for component in test_points}
    covered = sorted(
        net_id
        for net_id in required_nets
        if any(
            pin.net_id == net_id
            for component in test_points
            for pin in lane.pins_of_component(component.node_id)
        )
    )
    uncovered = sorted(set(required_nets) - set(covered))
    no_pin_nets = sorted(
        net_id
        for net_id in required_nets
        if not any(pin.net_id == net_id for pin in lane.pins)
    )
    coverage_ratio = len(covered) / len(required_nets) if required_nets else 0.0
    coverage = DftCoverageSet(
        required_nets=required_nets,
        covered_nets=covered,
        uncovered_nets=uncovered,
        ratio=coverage_ratio,
    )
    coverage_details = {
        "required_net_classes": list(policy.required_net_classes),
        "unresolved_classes": unresolved_classes,
        "net_names": {
            net.node_id: net.name for net in lane.nets if net.node_id in required
        },
    }
    if no_pin_nets:
        coverage_check = _check(
            "net_coverage",
            "unknown",
            "required nets have no connected pins: " + ", ".join(no_pin_nets),
            no_pin_nets,
            {**coverage_details, "no_pin_nets": no_pin_nets},
        )
    elif unresolved_classes:
        coverage_check = _check(
            "net_coverage",
            "unknown",
            "required net classes could not be classified: "
            + ", ".join(unresolved_classes),
            details=coverage_details,
        )
    elif uncovered:
        coverage_check = _check(
            "net_coverage",
            "fail",
            "test point coverage is missing for: " + ", ".join(uncovered),
            uncovered,
            coverage_details,
        )
    else:
        coverage_check = _check(
            "net_coverage",
            "pass",
            "all required nets have at least one test point",
            covered,
            coverage_details,
        )

    centers = {component.node_id: _center(graph, component.node_id) for component in test_points}
    missing_centers = sorted(
        component_id for component_id, center in centers.items() if center is None
    )
    pairs: list[dict[str, Any]] = []
    pitch_failures: list[dict[str, Any]] = []
    if missing_centers:
        pitch_check = _check(
            "probe_pitch",
            "unknown",
            "test point placement is missing for: " + ", ".join(missing_centers),
            missing_centers,
        )
    else:
        for (left_id, left), (right_id, right) in combinations(
            sorted(centers.items()), 2
        ):
            assert left is not None and right is not None
            distance = math.dist(left, right)
            pair = {"first": left_id, "second": right_id, "distance_mm": distance}
            pairs.append(pair)
            if distance < policy.min_probe_pitch_mm:
                pitch_failures.append(pair)
        pitch_check = _check(
            "probe_pitch",
            "fail" if pitch_failures else "pass",
            (
                "test point spacing is below the minimum pitch"
                if pitch_failures
                else "all test point centers meet the minimum probe pitch"
            ),
            [item for pair in pitch_failures for item in (pair["first"], pair["second"])],
            {"min_probe_pitch_mm": policy.min_probe_pitch_mm, "pairs": pairs},
        )

    diameter_info = {
        component.node_id: _pad_diameter_info(graph, component) for component in test_points
    }
    diameters = {component_id: value for component_id, (value, _) in diameter_info.items()}
    diameter_sources = {
        component_id: source for component_id, (_, source) in diameter_info.items()
    }
    missing_diameters = sorted(
        component_id for component_id, diameter in diameters.items() if diameter is None
    )
    diameter_failures = sorted(
        (component_id, diameter)
        for component_id, diameter in diameters.items()
        if diameter is not None and diameter < policy.min_pad_diameter_mm
    )
    if missing_diameters:
        diameter_check = _check(
            "pad_diameter",
            "unknown",
            "test point pad diameter is not declared for: " + ", ".join(missing_diameters),
            missing_diameters,
            {
                "min_pad_diameter_mm": policy.min_pad_diameter_mm,
                "diameters_mm": diameters,
                "diameter_sources": diameter_sources,
            },
        )
    elif diameter_failures:
        diameter_check = _check(
            "pad_diameter",
            "fail",
            "test point pad diameter is below the minimum",
            [item[0] for item in diameter_failures],
            {
                "min_pad_diameter_mm": policy.min_pad_diameter_mm,
                "diameters_mm": diameters,
                "diameter_sources": diameter_sources,
            },
        )
    else:
        diameter_check = _check(
            "pad_diameter",
            "pass",
            "all test point pads meet the minimum diameter",
            details={
                "min_pad_diameter_mm": policy.min_pad_diameter_mm,
                "diameters_mm": diameters,
                "diameter_sources": diameter_sources,
            },
        )

    bodies = _body_by_component(graph)
    side_values = {component.node_id: _side(graph, component, bodies) for component in test_points}
    missing_sides = sorted(
        component_id for component_id, side in side_values.items() if side is None
    )
    side_failures = sorted(
        component_id
        for component_id, side in side_values.items()
        if side is not None and policy.probe_side != "either" and side.lower() != policy.probe_side
    )
    if missing_sides:
        side_check = _check(
            "probe_side",
            "unknown",
            "test point side is not declared for: " + ", ".join(missing_sides),
            missing_sides,
            {"probe_side": policy.probe_side, "test_point_sides": side_values},
        )
    elif side_failures:
        side_check = _check(
            "probe_side",
            "fail",
            "test points do not match the declared probe side",
            side_failures,
            {"probe_side": policy.probe_side, "test_point_sides": side_values},
        )
    else:
        side_check = _check(
            "probe_side",
            "pass",
            "all test points have a declared compatible probe side",
            details={"probe_side": policy.probe_side, "test_point_sides": side_values},
        )

    rectangles = _body_rectangles(graph, lane, test_point_ids)
    missing_keepout_centers = sorted(
        component_id for component_id, center in centers.items() if center is None
    )
    if missing_keepout_centers or not rectangles:
        keepout_check = _check(
            "component_keepout",
            "unknown",
            "test point or non-test-point component body geometry is not declared",
            missing_keepout_centers,
            {"keepout_from_components_mm": policy.keepout_from_components_mm},
        )
    else:
        nearest: dict[str, tuple[float, str]] = {}
        for component_id, center in centers.items():
            assert center is not None
            nearest[component_id] = min(
                (
                    _point_to_rect_distance(center, rect),
                    body_component_id,
                )
                for body_component_id, rect in rectangles.items()
            )
        distances = {component_id: item[0] for component_id, item in nearest.items()}
        keepout_failures = sorted(
            (component_id, distance)
            for component_id, distance in distances.items()
            if distance < policy.keepout_from_components_mm
        )
        keepout_check = _check(
            "component_keepout",
            "fail" if keepout_failures else "pass",
            (
                "test points are inside the declared component keepout"
                if keepout_failures
                else "all test points meet the component keepout"
            ),
            [item[0] for item in keepout_failures],
            {
                "keepout_from_components_mm": policy.keepout_from_components_mm,
                "nearest_body_distance_mm": distances,
                "nearest_body_component_ids": {
                    component_id: item[1] for component_id, item in nearest.items()
                },
            },
        )

    checks = [
        coverage_check,
        pitch_check,
        diameter_check,
        side_check,
        keepout_check,
    ]
    statuses = {check.status for check in checks}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return DftCoverageResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        checks=checks,
        coverage=coverage,
        input_hashes={
            "graph": canonical_sha256(graph),
            "policy": canonical_sha256(policy),
        },
    )
