"""Deterministic lane preflight over declared design graphs.

The preflight reports every missing required node and attribute of every lane in
one pass, so a design iteration does not have to discover the declarations one
failure at a time. The result is diagnostic: it carries no gate authority, and a
`declarations_complete` status only means the declarations exist; it does not
mean that the lane gates pass or that the design is ready for ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from acd.schema.design_graph import DesignGraph
from acd.schema.lane_preflight import (
    LanePreflightLaneReport,
    LanePreflightMissingAttr,
    LanePreflightMissingNode,
    LanePreflightReport,
)


@dataclass(frozen=True)
class LaneNodeRequirement:
    """Declared node kind a lane needs, with the attributes it reads."""

    kind: str
    minimum_count: int
    attrs: tuple[str, ...]


_BOARD_ATTRS: Final[tuple[str, ...]] = (
    "width_mm",
    "height_mm",
    "layers",
    "thickness_mm",
    "unit",
    "origin",
    "y_axis",
    "min_track_mm",
    "min_clearance_mm",
    "via_drill_mm",
    "via_diameter_mm",
    "edge_copper_clearance_mm",
    "antenna_keepout",
)

_COMPONENT_ATTRS: Final[tuple[str, ...]] = (
    "refdes",
    "value",
    "mpn",
    "lcsc",
    "jlcpcb_class",
    "assembly",
    "symbol",
    "symbol_file",
    "symbol_source",
    "symbol_source_ref",
    "symbol_sha256",
    "footprint",
    "footprint_file",
    "footprint_source",
    "footprint_source_ref",
    "footprint_sha256",
)

_OUTLINE_ATTRS: Final[tuple[str, ...]] = (
    "width_mm",
    "depth_mm",
    "thickness_mm",
    "corner_radius_mm",
    "unit",
    "origin",
    "y_axis",
    "position_source",
    "position_source_ref",
)

_ENCLOSURE_ATTRS: Final[tuple[str, ...]] = (
    "material",
    "unit",
    "wall_thickness_mm",
    "min_wall_thickness_mm",
    "internal_clearance_mm",
    "lid_fit_gap_mm",
    "standoff_height_mm",
    "standoff_radius_mm",
    "fastener_method",
    "standoff_pilot_hole_diameter_mm",
    "lid_screw_hole_diameter_mm",
    "tolerance_mm",
    "interference_tolerance_mm3",
    "tolerance_source",
    "tolerance_source_ref",
)

LANE_REQUIREMENTS: Final[dict[str, tuple[LaneNodeRequirement, ...]]] = {
    "board-pipeline": (
        LaneNodeRequirement("electrical.board", 1, _BOARD_ATTRS),
        LaneNodeRequirement("electrical.component", 1, _COMPONENT_ATTRS),
        LaneNodeRequirement("electrical.net", 1, ("name", "width_basis")),
        LaneNodeRequirement("electrical.pin", 1, ("component", "pad", "no_connect")),
    ),
    "silkscreen-resolve": (
        LaneNodeRequirement(
            "mechanical.silk_text",
            1,
            (
                "layer",
                "role",
                "text",
                "stroke_width_mm",
                "height_mm",
                "placement_basis",
                "placement_search_order",
                "placement_reference",
            ),
        ),
    ),
    "enclosure-pipeline": (
        LaneNodeRequirement("mechanical.outline", 1, _OUTLINE_ATTRS),
        LaneNodeRequirement("mechanical.enclosure", 1, _ENCLOSURE_ATTRS),
    ),
    "firmware-pipeline": (
        LaneNodeRequirement(
            "firmware.module",
            1,
            # led_blink_period_ms, log_period_ms, and boot_log_message stay
            # optional: the firmware consistency check declares defaults for
            # them, so a missing declaration is not a lane blocker.
            ("module_name", "mcu_component", "entry_state"),
        ),
        LaneNodeRequirement("firmware.state", 1, ("state_name", "initial")),
        LaneNodeRequirement(
            "firmware.state_transition", 1, ("from_state", "to_state", "trigger")
        ),
        LaneNodeRequirement(
            "firmware.sequence_step", 1, ("step_index", "actor", "target", "action")
        ),
        LaneNodeRequirement("firmware.pin_assignment", 1, ("gpio", "net")),
    ),
}

LANE_IDS: Final[tuple[str, ...]] = tuple(sorted(LANE_REQUIREMENTS))
PREFLIGHT_CHECKED_PREDICATES: Final[tuple[str, ...]] = (
    "node.declared",
    "attribute.declared",
)
PREFLIGHT_UNCHECKED_PREDICATES: Final[tuple[str, ...]] = (
    "attribute.type",
    "attribute.value",
    "reference.resolved",
    "rationale.coverage",
    "tool.available",
    "gate.executed",
    "evidence.authoritative",
)


def _lane_report(
    graph: DesignGraph, lane: str, requirements: tuple[LaneNodeRequirement, ...]
) -> LanePreflightLaneReport:
    missing_nodes: list[LanePreflightMissingNode] = []
    missing_attrs: list[LanePreflightMissingAttr] = []
    for requirement in requirements:
        nodes = [node for node in graph.nodes if node.kind == requirement.kind]
        if len(nodes) < requirement.minimum_count:
            missing_nodes.append(
                LanePreflightMissingNode(
                    kind=requirement.kind,
                    required_count=requirement.minimum_count,
                    present_count=len(nodes),
                    reason=(
                        f"lane {lane} requires at least "
                        f"{requirement.minimum_count} {requirement.kind} node(s)"
                    ),
                )
            )
        for node in sorted(nodes, key=lambda item: item.id):
            for attr in requirement.attrs:
                if attr in node.attrs:
                    continue
                missing_attrs.append(
                    LanePreflightMissingAttr(
                        node_id=node.id,
                        kind=node.kind,
                        attr=attr,
                        reason=f"lane {lane} reads this attribute from the graph",
                    )
                )
    status = (
        "declarations_complete"
        if not missing_nodes and not missing_attrs
        else "declarations_incomplete"
    )
    return LanePreflightLaneReport(
        lane=lane,
        status=status,
        missing_nodes=missing_nodes,
        missing_attrs=missing_attrs,
    )


def run_lane_preflight(
    graph: DesignGraph, lanes: tuple[str, ...] | None = None
) -> LanePreflightReport:
    """Report the declaration gaps of every requested lane in one result."""
    selected = LANE_IDS if lanes is None else tuple(sorted(set(lanes)))
    unknown = [lane for lane in selected if lane not in LANE_REQUIREMENTS]
    if unknown:
        raise ValueError("unknown preflight lanes: " + ", ".join(sorted(unknown)))
    reports = [
        _lane_report(graph, lane, LANE_REQUIREMENTS[lane]) for lane in selected
    ]
    status = (
        "declarations_complete"
        if all(report.status == "declarations_complete" for report in reports)
        else "declarations_incomplete"
    )
    return LanePreflightReport(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        checked_predicates=list(PREFLIGHT_CHECKED_PREDICATES),
        unchecked_predicates=list(PREFLIGHT_UNCHECKED_PREDICATES),
        lanes=reports,
    )


__all__ = [
    "LANE_IDS",
    "LANE_REQUIREMENTS",
    "PREFLIGHT_CHECKED_PREDICATES",
    "PREFLIGHT_UNCHECKED_PREDICATES",
    "LaneNodeRequirement",
    "run_lane_preflight",
]
