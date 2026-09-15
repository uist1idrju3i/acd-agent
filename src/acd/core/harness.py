"""Deterministic checks for an opt-in declared wire-harness contract."""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import combinations, pairwise
from typing import cast

from acd.core.electrical import ElectricalLane
from acd.core.structural_safety import INCOMPATIBLE_SIGNAL_CLASS_PAIRS, SIGNAL_CLASSES
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.dfa_review import DfaFinding
from acd.schema.harness import (
    HarnessCheckResult,
    HarnessConnector,
    HarnessContract,
    HarnessResult,
    HarnessStatus,
    HarnessWire,
    HarnessWireType,
)


def _node_map(graph: DesignGraph) -> dict[str, GraphNode]:
    return {node.id: node for node in graph.nodes}


def _number(attrs: Mapping[str, object], key: str) -> float | None:
    value = attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _check(
    check_id: str,
    status: str,
    reason: str,
    subject_ids: list[str],
    details: dict[str, object] | None = None,
) -> HarnessCheckResult:
    return HarnessCheckResult(
        check_id=check_id,
        status=cast(HarnessStatus, status),
        reason=reason,
        subject_ids=sorted(set(subject_ids)),
        details=details or {},
    )


def _graph_pin_for_cavity(
    graph: DesignGraph,
    lane: ElectricalLane,
    component_id: str,
    cavity: str,
) -> tuple[str, str] | None:
    for pin in lane.pins_of_component(component_id):
        node = next((item for item in graph.nodes if item.id == pin.node_id), None)
        if pin.pad == cavity or (
            node is not None and node.attrs.get("name") == cavity
        ):
            return pin.node_id, pin.net_id or ""
    return None


def _wire_type(contract: HarnessContract, wire: HarnessWire) -> HarnessWireType:
    return next(item for item in contract.wire_types if item.wire_type_id == wire.wire_type_id)


def _wire_map(contract: HarnessContract) -> dict[str, HarnessWire]:
    return {wire.wire_id: wire for wire in contract.wires}


def _net_attrs(graph: DesignGraph, net_id: str) -> Mapping[str, object] | None:
    node = next((item for item in graph.nodes if item.id == net_id), None)
    return node.attrs if node is not None and node.kind == "electrical.net" else None


def _signal_class(graph: DesignGraph, net_id: str) -> str | None:
    attrs = _net_attrs(graph, net_id)
    value = attrs.get("signal_class") if attrs is not None else None
    return value if isinstance(value, str) and value in SIGNAL_CLASSES else None


def _route_wire_pairs(contract: HarnessContract) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for route in contract.routes:
        for left, right in combinations(sorted(route.wire_ids), 2):
            pairs.add((left, right))
    return pairs


def _connector_wire_pairs(contract: HarnessContract) -> set[tuple[str, str]]:
    by_connector: dict[str, list[str]] = {}
    for wire in contract.wires:
        for endpoint in (wire.from_, wire.to):
            by_connector.setdefault(endpoint.connector_id, []).append(wire.wire_id)
    pairs: set[tuple[str, str]] = set()
    for wire_ids in by_connector.values():
        for left, right in combinations(sorted(set(wire_ids)), 2):
            pairs.add((left, right))
    return pairs


def _netlist_consistency(
    graph: DesignGraph,
    lane: ElectricalLane,
    contract: HarnessContract,
) -> HarnessCheckResult:
    nodes = _node_map(graph)
    net_ids = {node.id for node in graph.nodes if node.kind == "electrical.net"}
    connector_map = {
        connector.connector_id: connector.graph_component_id
        for connector in contract.connectors
    }
    failures: list[str] = []
    unknowns: list[str] = []
    mismatches: list[dict[str, str]] = []
    for wire in contract.wires:
        if wire.net_id not in net_ids:
            failures.append(wire.wire_id)
            mismatches.append({"wire_id": wire.wire_id, "reason": "unknown net"})
            continue
        for endpoint in (wire.from_, wire.to):
            component_id = connector_map[endpoint.connector_id]
            if component_id is None:
                continue
            component = nodes.get(component_id)
            if component is None or component.kind != "electrical.component":
                unknowns.append(wire.wire_id)
                continue
            pin = _graph_pin_for_cavity(graph, lane, component_id, endpoint.cavity)
            if pin is None:
                unknowns.append(wire.wire_id)
            elif pin[1] != wire.net_id:
                failures.append(wire.wire_id)
                mismatches.append(
                    {
                        "wire_id": wire.wire_id,
                        "endpoint": endpoint.connector_id,
                        "cavity": endpoint.cavity,
                        "declared_net": wire.net_id,
                        "graph_net": pin[1],
                    }
                )
    off_board = [
        node.id
        for node in graph.nodes
        if node.kind == "electrical.net" and node.attrs.get("off_board") is True
    ]
    declared = {wire.net_id for wire in contract.wires}
    missing_off_board = sorted(set(off_board) - declared)
    if missing_off_board:
        failures.extend(missing_off_board)
        mismatches.extend(
            {"net_id": net_id, "reason": "off-board net has no harness wire"}
            for net_id in missing_off_board
        )
    if failures:
        return _check(
            "netlist_consistency",
            "fail",
            "harness wires do not match graph connector pins or off-board net scope",
            failures,
            {"mismatches": mismatches, "missing_off_board_nets": missing_off_board},
        )
    if unknowns:
        return _check(
            "netlist_consistency",
            "unknown",
            "connector cavity cannot be mapped to a graph pin",
            unknowns,
            {"unmappable_wires": sorted(set(unknowns))},
        )
    return _check(
        "netlist_consistency",
        "pass",
        "harness wires match graph connector pins and off-board net scope",
        list(net_ids & declared),
        {"off_board_nets": off_board},
    )


def _temperature_factor(
    wire_type: HarnessWireType,
    ambient_temperature_c: float,
) -> float | None:
    points = wire_type.temperature_derating
    if not points:
        return 1.0 if ambient_temperature_c <= wire_type.ampacity_reference_temp_c else None
    if ambient_temperature_c > points[-1].temp_c:
        return None
    if ambient_temperature_c <= points[0].temp_c:
        return points[0].factor
    for left, right in pairwise(points):
        if left.temp_c <= ambient_temperature_c <= right.temp_c:
            ratio = (ambient_temperature_c - left.temp_c) / (
                right.temp_c - left.temp_c
            )
            return left.factor + ratio * (right.factor - left.factor)
    return None


def _ampacity(
    graph: DesignGraph,
    contract: HarnessContract,
) -> HarnessCheckResult:
    failures: list[str] = []
    unknowns: list[str] = []
    values: dict[str, dict[str, float]] = {}
    bundle_factor = (
        contract.bundle_derating.factor if contract.bundle_derating is not None else 1.0
    )
    for wire in contract.wires:
        node = next((item for item in graph.nodes if item.id == wire.net_id), None)
        required = _number(node.attrs, "current_max_a") if node is not None else None
        wire_type = _wire_type(contract, wire)
        factor = _temperature_factor(wire_type, contract.ambient_temperature_c)
        if required is None or factor is None:
            unknowns.append(wire.wire_id)
            continue
        allowed = wire_type.ampacity_a * factor * bundle_factor
        values[wire.wire_id] = {
            "required_a": required,
            "base_ampacity_a": wire_type.ampacity_a,
            "temperature_factor": factor,
            "bundle_factor": bundle_factor,
            "allowed_a": allowed,
        }
        if required > allowed:
            failures.append(wire.wire_id)
    if failures:
        return _check(
            "ampacity",
            "fail",
            "required current exceeds derated wire ampacity",
            failures,
            {"wires": values},
        )
    if unknowns:
        return _check(
            "ampacity",
            "unknown",
            "current demand or applicable temperature derating is undeclared",
            unknowns,
            {"wires": values},
        )
    return _check(
        "ampacity",
        "pass",
        "all harness wires meet derated ampacity",
        [],
        {"wires": values},
    )


def _wire_length_m(wire: HarnessWire) -> float:
    return (wire.length_mm + wire.slack_mm) / 1000.0


def _voltage_drop(
    graph: DesignGraph,
    contract: HarnessContract,
) -> HarnessCheckResult:
    wires = _wire_map(contract)
    failures: list[str] = []
    unknowns: list[str] = []
    values: dict[str, dict[str, float]] = {}
    for wire in contract.wires:
        net = next((item for item in graph.nodes if item.id == wire.net_id), None)
        current = _number(net.attrs, "current_max_a") if net is not None else None
        maximum = _number(net.attrs, "max_voltage_drop_v") if net is not None else None
        if current is None or maximum is None:
            unknowns.append(wire.wire_id)
            continue
        wire_type = _wire_type(contract, wire)
        resistance = wire_type.resistance_mohm_per_m * _wire_length_m(wire)
        return_resistance = 0.0
        if wire.return_wire_id is not None:
            return_wire = wires[wire.return_wire_id]
            return_type = _wire_type(contract, return_wire)
            return_resistance = (
                return_type.resistance_mohm_per_m * _wire_length_m(return_wire)
            )
        drop = current * (resistance + return_resistance) / 1000.0
        values[wire.wire_id] = {
            "current_a": current,
            "length_m": _wire_length_m(wire),
            "resistance_ohm": resistance / 1000.0,
            "return_resistance_ohm": return_resistance / 1000.0,
            "drop_v": drop,
            "max_voltage_drop_v": maximum,
        }
        if drop > maximum:
            failures.append(wire.wire_id)
    if failures:
        return _check(
            "voltage_drop",
            "fail",
            "declared harness voltage drop exceeds net limit",
            failures,
            {"wires": values},
        )
    if unknowns:
        return _check(
            "voltage_drop",
            "unknown",
            "current or maximum voltage drop is undeclared",
            unknowns,
            {"wires": values},
        )
    return _check(
        "voltage_drop",
        "pass",
        "all harness wires meet voltage-drop limits",
        [],
        {"wires": values},
    )


def _insulation_rating(
    graph: DesignGraph,
    contract: HarnessContract,
) -> HarnessCheckResult:
    failures: list[str] = []
    unknowns: list[str] = []
    details: dict[str, dict[str, float]] = {}
    for wire in contract.wires:
        net = next((item for item in graph.nodes if item.id == wire.net_id), None)
        nominal = _number(net.attrs, "voltage_nominal_v") if net is not None else None
        wire_type = _wire_type(contract, wire)
        if nominal is None:
            unknowns.append(wire.wire_id)
            continue
        details[wire.wire_id] = {
            "voltage_nominal_v": nominal,
            "insulation_rating_v": wire_type.insulation_rating_v,
            "ambient_temperature_c": contract.ambient_temperature_c,
            "insulation_temp_c": wire_type.insulation_temp_c,
        }
        if (
            nominal > wire_type.insulation_rating_v
            or contract.ambient_temperature_c > wire_type.insulation_temp_c
        ):
            failures.append(wire.wire_id)
    if failures:
        return _check(
            "insulation_rating",
            "fail",
            "wire insulation voltage or temperature rating is insufficient",
            failures,
            {"wires": details},
        )
    if unknowns:
        return _check(
            "insulation_rating",
            "unknown",
            "net nominal voltage is undeclared",
            unknowns,
            {"wires": details},
        )
    return _check(
        "insulation_rating",
        "pass",
        "all wire insulation ratings are sufficient",
        [],
        {"wires": details},
    )


def _bend_radius(contract: HarnessContract) -> HarnessCheckResult:
    if not contract.routes:
        return _check("bend_radius", "pass", "no routes declared", [])
    failures: list[str] = []
    unknowns: list[str] = []
    details: dict[str, object] = {}
    wires = _wire_map(contract)
    for route in contract.routes:
        for wire_id in route.wire_ids:
            wire = wires[wire_id]
            required = wire.bend_radius_min_mm
            declared = route.min_bend_radius_mm.get(wire_id)
            if required is None or declared is None:
                unknowns.append(wire_id)
                continue
            details[wire_id] = {
                "required_min_bend_radius_mm": required,
                "route_min_bend_radius_mm": declared,
            }
            if required > declared:
                failures.append(wire_id)
    if failures:
        return _check(
            "bend_radius",
            "fail",
            "route bend radius is below wire minimum",
            failures,
            details,
        )
    if unknowns:
        return _check(
            "bend_radius",
            "unknown",
            "route bend radius or wire minimum is undeclared",
            unknowns,
            details,
        )
    return _check(
        "bend_radius",
        "pass",
        "all declared route bend radii are sufficient",
        [],
        details,
    )


def _shield_requirement(
    graph: DesignGraph, contract: HarnessContract
) -> HarnessCheckResult:
    required = [
        wire
        for wire in contract.wires
        if _signal_class(graph, wire.net_id) in {"analog_sensitive", "high_speed"}
    ]
    if not required:
        return _check(
            "shield_requirement",
            "pass",
            "no analog-sensitive or high-speed harness nets require shielding",
            [],
        )
    wires = _wire_map(contract)
    failures: list[str] = []
    for wire in required:
        wire_type = _wire_type(contract, wire)
        paired = (
            wires.get(wire.return_wire_id)
            if wire.return_wire_id is not None
            else None
        )
        if wire_type.shield == "none" and not (
            wire.twisted_pair_group is not None
            and paired is not None
            and paired.twisted_pair_group == wire.twisted_pair_group
        ):
            failures.append(wire.wire_id)
    if failures:
        return _check(
            "shield_requirement",
            "fail",
            "analog-sensitive and high-speed harness nets require a shield "
            "or declared twisted return pair",
            failures,
            {"required_wires": [wire.wire_id for wire in required]},
        )
    return _check(
        "shield_requirement",
        "pass",
        "all analog-sensitive and high-speed harness nets have shield or twisted return protection",
        [wire.wire_id for wire in required],
    )


def _signal_class_segregation(
    graph: DesignGraph, contract: HarnessContract
) -> HarnessCheckResult:
    pairs = _connector_wire_pairs(contract) | _route_wire_pairs(contract)
    wires = _wire_map(contract)
    failures: list[str] = []
    unknowns: list[str] = []
    for left_id, right_id in sorted(pairs):
        left_class = _signal_class(graph, wires[left_id].net_id)
        right_class = _signal_class(graph, wires[right_id].net_id)
        if left_class is None and right_class is None:
            continue
        if left_class is None or right_class is None:
            unknowns.extend((left_id, right_id))
            continue
        if frozenset({left_class, right_class}) in INCOMPATIBLE_SIGNAL_CLASS_PAIRS:
            failures.append(
                f"{left_id}/{right_id}: {left_class}/{right_class}"
            )
    if failures:
        return _check(
            "signal_class_segregation",
            "fail",
            "incompatible signal classes share a connector or harness route",
            sorted(
                {
                    wire_id
                    for pair in failures
                    for wire_id in pair.split(":", 1)[0].split("/")
                }
            ),
            {"pairs": failures},
        )
    if unknowns:
        return _check(
            "signal_class_segregation",
            "unknown",
            "signal class is missing for a connector or route wire pair",
            sorted(set(unknowns)),
        )
    return _check(
        "signal_class_segregation",
        "pass",
        "declared harness signal classes satisfy connector and route segregation rules",
        [],
        {
            "min_spacing_mm": (
                contract.segregation_policy.min_spacing_mm
                if contract.segregation_policy is not None
                else None
            )
        },
    )


def _flex_cycles(
    contract: HarnessContract,
) -> HarnessCheckResult:
    moving = [route for route in contract.routes if route.moving_section]
    if not moving:
        return _check(
            "flex_cycles",
            "pass",
            "no moving harness section is declared",
            [],
        )
    wires = _wire_map(contract)
    unknowns: list[str] = []
    failures: list[str] = []
    details: dict[str, object] = {}
    for route in moving:
        for wire_id in route.wire_ids:
            wire = wires[wire_id]
            wire_type = _wire_type(contract, wire)
            if (
                route.expected_flex_cycles is None
                or wire_type.flex_rated_cycles is None
                or route.bend_radius_dynamic_mm is None
                or wire.bend_radius_min_mm is None
            ):
                unknowns.append(wire_id)
                continue
            details[wire_id] = {
                "expected_flex_cycles": route.expected_flex_cycles,
                "flex_rated_cycles": wire_type.flex_rated_cycles,
                "bend_radius_dynamic_mm": route.bend_radius_dynamic_mm,
                "wire_bend_radius_min_mm": wire.bend_radius_min_mm,
            }
            if (
                route.expected_flex_cycles > wire_type.flex_rated_cycles
                or route.bend_radius_dynamic_mm < wire.bend_radius_min_mm
            ):
                failures.append(wire_id)
    if failures:
        return _check(
            "flex_cycles",
            "fail",
            "moving-section flex cycles or dynamic bend radius are insufficient",
            failures,
            details,
        )
    if unknowns:
        return _check(
            "flex_cycles",
            "unknown",
            "moving-section flex-cycle or dynamic bend declarations are incomplete",
            sorted(set(unknowns)),
            details,
        )
    return _check(
        "flex_cycles",
        "pass",
        "moving-section flex-cycle and dynamic bend declarations are sufficient",
        [],
        details,
    )


def _mating_cycles(contract: HarnessContract) -> HarnessCheckResult:
    expectation = contract.service_expectation
    if expectation is None:
        return _check(
            "mating_cycles",
            "pass",
            "no mating-cycle or retention-force service expectation is declared",
            [],
        )
    failures: list[str] = []
    unknowns: list[str] = []
    details: dict[str, object] = {}
    for connector in contract.connectors:
        if expectation.expected_mating_cycles is not None:
            if connector.mating_cycles_rated is None:
                unknowns.append(connector.connector_id)
                continue
            connector_details = cast(
                dict[str, object],
                details.setdefault(connector.connector_id, {}),
            )
            connector_details["mating_cycles_rated"] = connector.mating_cycles_rated
            if expectation.expected_mating_cycles > connector.mating_cycles_rated:
                failures.append(connector.connector_id)
        if expectation.min_retention_force_n is not None:
            if connector.retention_force_n is None:
                unknowns.append(connector.connector_id)
                continue
            connector_details = cast(
                dict[str, object],
                details.setdefault(connector.connector_id, {}),
            )
            connector_details["retention_force_n"] = connector.retention_force_n
            if connector.retention_force_n < expectation.min_retention_force_n:
                failures.append(connector.connector_id)
    if failures:
        return _check(
            "mating_cycles",
            "fail",
            "connector mating-cycle or retention-force rating is insufficient",
            failures,
            details,
        )
    if unknowns:
        return _check(
            "mating_cycles",
            "unknown",
            "connector mating-cycle or retention-force rating is undeclared",
            sorted(set(unknowns)),
            details,
        )
    return _check(
        "mating_cycles",
        "pass",
        "connector mating-cycle and retention-force ratings meet the service expectation",
        [],
        details,
    )


def _keying_polarity(contract: HarnessContract) -> HarnessCheckResult:
    by_housing: dict[str, list[HarnessConnector]] = {}
    for connector in contract.connectors:
        if connector.housing_mpn is not None:
            by_housing.setdefault(connector.housing_mpn, []).append(connector)
    failures: list[str] = []
    for housing, connectors in sorted(by_housing.items()):
        for left, right in combinations(connectors, 2):
            if left.keying != right.keying and left.keying is not None and right.keying is not None:
                continue
            if left.polarity_guard is True or right.polarity_guard is True:
                continue
            failures.append(f"{housing}: {left.connector_id}/{right.connector_id}")
    if failures:
        return _check(
            "keying_polarity",
            "fail",
            "connectors sharing a housing lack distinct keying or a polarity guard",
            [
                connector_id
                for pair in failures
                for connector_id in pair.split(":", 1)[1].strip().split("/")
            ],
            {"shared_housings": failures},
        )
    return _check(
        "keying_polarity",
        "pass",
        "connectors sharing a housing have distinct keying or a polarity guard",
        [],
    )


def _member_net_ids(
    graph: DesignGraph, lane: ElectricalLane, member_id: str
) -> set[str] | None:
    node = next((item for item in graph.nodes if item.id == member_id), None)
    if node is None:
        return None
    if node.kind == "electrical.net":
        return {member_id}
    if node.kind == "electrical.component":
        return {pin.net_id for pin in lane.pins if pin.component_id == member_id and pin.net_id}
    return set()


def _redundant_group_harness(
    graph: DesignGraph, lane: ElectricalLane, contract: HarnessContract
) -> HarnessCheckResult:
    groups = [
        node
        for node in graph.nodes
        if node.kind == "safety.redundant_group"
        and isinstance(node.attrs.get("resources_shared_forbidden"), list)
        and "harness" in cast(
            list[object], node.attrs["resources_shared_forbidden"]
        )
    ]
    if not groups:
        return _check(
            "redundant_group_harness",
            "pass",
            "no redundant group forbids harness resource sharing",
            [],
        )
    route_nets = [
        {wire.net_id for wire in contract.wires if wire.wire_id in route.wire_ids}
        for route in contract.routes
    ]
    failures: list[str] = []
    unknowns: list[str] = []
    for group in groups:
        members = group.attrs.get("members")
        if not isinstance(members, list) or len(members) < 2:
            unknowns.append(group.id)
            continue
        member_nets: list[set[str]] = []
        for member in members:
            if not isinstance(member, str):
                unknowns.append(group.id)
                break
            nets = _member_net_ids(graph, lane, member)
            if nets is None or not nets:
                unknowns.append(group.id)
                break
            member_nets.append(nets)
        if len(member_nets) != len(members):
            continue
        if any(
            all(nets & route_nets_item for nets in member_nets)
            for route_nets_item in route_nets
        ):
            failures.append(group.id)
        elif any(
            not any(route_nets_item & nets for route_nets_item in route_nets)
            for nets in member_nets
        ):
            unknowns.append(group.id)
    if failures:
        return _check(
            "redundant_group_harness",
            "fail",
            "redundant-group members share a declared harness route",
            failures,
        )
    if unknowns:
        return _check(
            "redundant_group_harness",
            "unknown",
            "redundant-group member routing is incomplete for harness independence",
            sorted(set(unknowns)),
        )
    return _check(
        "redundant_group_harness",
        "pass",
        "redundant-group members do not share a declared harness route",
        [group.id for group in groups],
    )


def _dfa_findings(contract: HarnessContract) -> list[DfaFinding]:
    findings: list[DfaFinding] = []
    number = 1
    for connector in contract.connectors:
        if connector.keying is None:
            findings.append(
                DfaFinding(
                    finding_id=f"DFA-H-{number:03d}",
                    aspect="connector_cable_order",
                    severity="advisory",
                    status="observed",
                    subject_node_ids=[connector.connector_id],
                    basis=(
                        "L2 non-authoritative DFA observation: connector keying is not declared."
                    ),
                )
            )
            number += 1
    for wire in contract.wires:
        if wire.slack_mm < wire.length_mm * 0.05:
            findings.append(
                DfaFinding(
                    finding_id=f"DFA-H-{number:03d}",
                    aspect="connector_cable_order",
                    severity="advisory",
                    status="observed",
                    subject_node_ids=[wire.wire_id],
                    basis=(
                        "L2 non-authoritative DFA observation: wire slack is below 5% "
                        "of declared length."
                    ),
                )
            )
            number += 1
    return findings


def evaluate_harness(
    graph: DesignGraph,
    lane: ElectricalLane,
    contract: HarnessContract,
) -> HarnessResult:
    if graph.graph_id != contract.graph_id or graph.revision != contract.revision:
        raise ValueError("harness graph_id/revision does not match graph")
    checks = [
        _netlist_consistency(graph, lane, contract),
        _ampacity(graph, contract),
        _voltage_drop(graph, contract),
        _insulation_rating(graph, contract),
        _bend_radius(contract),
        _shield_requirement(graph, contract),
        _signal_class_segregation(graph, contract),
        _flex_cycles(contract),
        _mating_cycles(contract),
        _keying_polarity(contract),
        _redundant_group_harness(graph, lane, contract),
    ]
    statuses = {check.status for check in checks}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return HarnessResult(
        harness_id=contract.harness_id,
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        checks=checks,
        input_hashes={
            "graph": canonical_sha256(graph),
            "harness": canonical_sha256(contract),
        },
        dfa_findings=_dfa_findings(contract),
    )
