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
    LanePreflightMissingDeclaration,
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

# Where each required node kind is declared in the design input
# (DesignFixtureSpec). The preflight reports these paths so that a missing
# declaration can be added at its source instead of being invented downstream.
SPEC_DECLARATION_PATHS: Final[dict[str, str]] = {
    "electrical.board": "board_attrs",
    "electrical.component": "components[]",
    "electrical.net": "nets[]",
    "electrical.pin": "components[].pads",
    "mechanical.outline": "mechanical_outline.attrs",
    "mechanical.silk_text": "silk_texts[].attrs",
    "mechanical.silk_graphic": "silk_graphics[].attrs",
    "firmware.module": "firmware_module.attrs",
    "firmware.state": "firmware_module.states[]",
    "firmware.state_transition": "firmware_module.transitions[]",
    "firmware.sequence_step": "firmware_module.sequence_steps[]",
    "firmware.pin_assignment": "firmware_pin_assignments[]",
}

# Node kinds without a design-input path cannot be declared through the fixture
# builder yet; the preflight says so instead of guessing a location.
UNDECLARABLE_SPEC_PATH: Final[str] = "<no DesignFixtureSpec path; declare in graph.json>"

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


def missing_declarations(
    report: LanePreflightReport,
) -> list[LanePreflightMissingDeclaration]:
    """List every declaration the design input must add, grouped per lane/kind.

    Nothing is auto-completed: the list is the exact set of declarations a human
    or agent has to write into the design input before the lanes can run.
    """
    entries: list[LanePreflightMissingDeclaration] = []
    for lane in report.lanes:
        if lane.status == "declarations_complete":
            continue
        requirements = {item.kind: item for item in LANE_REQUIREMENTS[lane.lane]}
        kinds = sorted(
            {node.kind for node in lane.missing_nodes}
            | {attr.kind for attr in lane.missing_attrs}
        )
        for kind in kinds:
            requirement = requirements[kind]
            missing_node = next(
                (node for node in lane.missing_nodes if node.kind == kind), None
            )
            required = requirement.minimum_count
            present_count = (
                missing_node.present_count if missing_node is not None else None
            )
            entries.append(
                LanePreflightMissingDeclaration(
                    lane=lane.lane,
                    kind=kind,
                    spec_path=SPEC_DECLARATION_PATHS.get(kind, UNDECLARABLE_SPEC_PATH),
                    required_count=required,
                    present_count=present_count,
                    missing_count=(
                        required - present_count if present_count is not None else 0
                    ),
                    required_attrs=list(requirement.attrs),
                    missing_attrs=[
                        attr for attr in lane.missing_attrs if attr.kind == kind
                    ],
                )
            )
    return entries


def missing_declaration_action(report: LanePreflightReport) -> str | None:
    """Render the declarations to add to the design input as one instruction."""
    entries = missing_declarations(report)
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        if entry.missing_count > 0:
            attrs = ", ".join(f"{entry.kind}.{attr}" for attr in entry.required_attrs)
            parts.append(
                f"{entry.lane}: declare {entry.missing_count} more {entry.kind} "
                f"node(s) under `{entry.spec_path}` with attrs [{attrs}]"
            )
        if entry.missing_attrs:
            names = ", ".join(
                sorted({f"{entry.kind}.{item.attr}" for item in entry.missing_attrs})
            )
            nodes = ", ".join(sorted({item.node_id for item in entry.missing_attrs}))
            parts.append(
                f"{entry.lane}: add attrs [{names}] to existing node(s) [{nodes}] "
                f"under `{entry.spec_path}`"
            )
    return (
        "Add the missing declarations to the design input spec "
        "(DesignFixtureSpec) and rebuild the fixture; declarations are never "
        "auto-completed. " + "; ".join(parts)
    )


__all__ = [
    "LANE_IDS",
    "LANE_REQUIREMENTS",
    "PREFLIGHT_CHECKED_PREDICATES",
    "PREFLIGHT_UNCHECKED_PREDICATES",
    "SPEC_DECLARATION_PATHS",
    "UNDECLARABLE_SPEC_PATH",
    "LaneNodeRequirement",
    "missing_declaration_action",
    "missing_declarations",
    "run_lane_preflight",
]
