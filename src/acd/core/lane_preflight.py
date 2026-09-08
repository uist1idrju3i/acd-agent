"""Deterministic lane preflight over declared design graphs.

The preflight reports every missing required node and attribute of every lane in
one pass, so a design iteration does not have to discover the declarations one
failure at a time. For the enclosure lane the preflight also runs the graph-only
mechanical structure checks (missing component bodies, outline/enclosure
structure, unresolved references) so those gaps surface in the same report. The
result is diagnostic: it carries no gate authority, and a
`declarations_complete` status only means the declarations exist and the
mechanical structure checks found no finding; it does not mean that the lane
gates pass or that the design is ready for ordering. For the board lane the
preflight additionally resolves declared evidence attributes (confirmed CPL
rotation records and fab order-intent provenance) against measured records on
disk; an unresolved declaration is reported as `declared_unverified`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from acd.core.declaration_vocabulary import (
    NET_WIDTH_BASIS,
    SAFETY_BOUNDARY_HAZARD_KEYS,
    SAFETY_BOUNDARY_INTENDED_USE,
    SAFETY_BOUNDARY_MODULE_CERTIFIED,
)
from acd.core.electrical import GraphExtractionError
from acd.core.evidence_declarations import collect_evidence_declaration_findings
from acd.core.firmware_capability import load_firmware_capability_registry
from acd.core.firmware_coverage import check_firmware_coverage
from acd.core.mechanical_preflight import collect_mechanical_findings
from acd.schema.design_graph import DesignGraph
from acd.schema.lane_preflight import (
    LanePreflightLaneReport,
    LanePreflightMissingAttr,
    LanePreflightMissingDeclaration,
    LanePreflightMissingNode,
    LanePreflightReport,
    LanePreflightUnsupportedCode,
    LanePreflightUnsupportedValue,
)


@dataclass(frozen=True)
class LaneNodeRequirement:
    """Declared node kind a lane needs, with the attributes it reads."""

    kind: str
    minimum_count: int
    attrs: tuple[str, ...]
    all_or_none_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class LaneAttrValueRule:
    """Allowed-value contract for one free-form declared attribute.

    ``boolean`` rules require a bool value; ``allowed`` rules require a string
    member of the vocabulary. ``required`` rules also fire when the attribute is
    absent; non-required rules only fire on a present-but-unsupported value
    (absence is reported through the missing-attribute path instead).
    """

    kind: str
    attr: str
    code: LanePreflightUnsupportedCode
    allowed: tuple[str, ...] = ()
    boolean: bool = False
    required: bool = True


_STITCH_VIA_BASIS_ATTRS: Final[tuple[str, ...]] = (
    "stitch_via_max_frequency_hz",
    "stitch_via_dielectric_constant",
    "stitch_via_wavelength_fraction",
    "stitch_via_basis_source",
)

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
    "allowable_temperature_rise_k",
    "width_basis_equation",
    "width_basis_source",
    "width_measurement_tolerance_mm",
    "outer_copper_thickness_um",
    "ipc2221_external_k",
    "ipc2221_external_b",
    "ipc2221_external_c",
    "ipc2221_internal_k",
    "ipc2221_internal_b",
    "ipc2221_internal_c",
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

_COMPONENT_BODY_ATTRS: Final[tuple[str, ...]] = (
    "body_type",
    "height_mm",
    "x_mm",
    "y_mm",
    "width_mm",
    "depth_mm",
    "mounting_side",
    "rotation_deg",
    "position_source",
    "position_source_ref",
    "dimensions_source",
    "dimensions_source_ref",
    "dimensions_checked_at",
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

_ORDER_INTENT_ATTRS: Final[tuple[str, ...]] = (
    "fab_profile",
    "pcba_class_target",
    "quantity_pcs",
    "assembly_sides",
    "delivery_format",
    "soldermask_color",
    "surface_finish",
    "profile_source",
    "profile_fetched_at",
)

LANE_REQUIREMENTS: Final[dict[str, tuple[LaneNodeRequirement, ...]]] = {
    "board-pipeline": (
        LaneNodeRequirement("electrical.board", 1, _BOARD_ATTRS, (_STITCH_VIA_BASIS_ATTRS,)),
        LaneNodeRequirement("electrical.component", 1, _COMPONENT_ATTRS),
        LaneNodeRequirement("electrical.net", 1, ("name", "width_basis", "width_basis_source")),
        LaneNodeRequirement("electrical.pin", 1, ("component", "pad", "no_connect")),
        LaneNodeRequirement("fab.order_intent", 1, _ORDER_INTENT_ATTRS),
        # Values are checked by LANE_VALUE_RULES below, not by the
        # missing-attribute path.
        LaneNodeRequirement("safety.boundary", 1, ()),
    ),
    "silkscreen-resolve": (
        LaneNodeRequirement("fab.order_intent", 1, _ORDER_INTENT_ATTRS),
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
                # The resolver reads these too; placement_rotation_degrees has
                # a declared default and stays optional.
                "rotation_deg",
                "placement_offset_step_mm",
                "placement_search_limit_mm",
                "placement_safety_margin_mm",
                "board_edge_margin_mm",
                "board_edge_margin_source",
            ),
        ),
    ),
    "enclosure-pipeline": (
        LaneNodeRequirement("mechanical.outline", 1, _OUTLINE_ATTRS),
        LaneNodeRequirement("mechanical.component_body", 1, _COMPONENT_BODY_ATTRS),
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
        LaneNodeRequirement("firmware.state_transition", 1, ("from_state", "to_state", "trigger")),
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
    "mechanical.component_body": "component_bodies[].attrs",
    "mechanical.connector_opening": "connector_openings[].attrs",
    "mechanical.board_edge_overhang": "board_edge_overhangs[].attrs",
    "mechanical.enclosure": "enclosure.attrs",
    "safety.boundary": "safety_boundary.attrs",
    "fab.order_intent": "fab_order_intent.attrs",
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

# Node kinds a lane needs at an exact count; a wrong count is a vocabulary
# finding (`code`), and an absent kind is additionally a missing node.
LANE_NODE_EXACT_COUNTS: Final[
    dict[str, tuple[tuple[str, int, LanePreflightUnsupportedCode], ...]]
] = {
    "board-pipeline": (("safety.boundary", 1, "safety.boundary.missing"),),
}

_SAFETY_BOUNDARY_VALUE_RULES: Final[tuple[LaneAttrValueRule, ...]] = (
    LaneAttrValueRule(
        "safety.boundary",
        "intended_use",
        "safety.boundary.intended_use_unsupported",
        allowed=SAFETY_BOUNDARY_INTENDED_USE,
    ),
    LaneAttrValueRule(
        "safety.boundary",
        "module_certified",
        "safety.boundary.module_certified_unsupported",
        allowed=SAFETY_BOUNDARY_MODULE_CERTIFIED,
    ),
    *(
        LaneAttrValueRule(
            "safety.boundary",
            key,
            "safety.boundary.hazard_flag_invalid",
            boolean=True,
        )
        for key in SAFETY_BOUNDARY_HAZARD_KEYS
    ),
)

LANE_VALUE_RULES: Final[dict[str, tuple[LaneAttrValueRule, ...]]] = {
    "board-pipeline": (
        *_SAFETY_BOUNDARY_VALUE_RULES,
        LaneAttrValueRule(
            "electrical.net",
            "width_basis",
            "net.width_basis_unsupported",
            allowed=NET_WIDTH_BASIS,
        ),
    ),
}

LANE_IDS: Final[tuple[str, ...]] = tuple(sorted(LANE_REQUIREMENTS))
PREFLIGHT_CHECKED_PREDICATES: Final[tuple[str, ...]] = (
    "node.declared",
    "attribute.declared",
    "mechanical.structure",
    "evidence.declaration",
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
    graph: DesignGraph,
    lane: str,
    requirements: tuple[LaneNodeRequirement, ...],
    root: Path | None = None,
) -> LanePreflightLaneReport:
    missing_nodes: list[LanePreflightMissingNode] = []
    missing_attrs: list[LanePreflightMissingAttr] = []
    unsupported_values: list[LanePreflightUnsupportedValue] = []
    for kind, expected, code in LANE_NODE_EXACT_COUNTS.get(lane, ()):
        nodes = sorted(
            (node for node in graph.nodes if node.kind == kind),
            key=lambda item: item.id,
        )
        if len(nodes) != expected:
            unsupported_values.append(
                LanePreflightUnsupportedValue(
                    code=code,
                    node_id=nodes[0].id if nodes else "<undeclared>",
                    kind=kind,
                    attr="count",
                    reason=(
                        f"lane {lane} requires exactly {expected} {kind} "
                        f"node(s); {len(nodes)} declared under "
                        f"`{SPEC_DECLARATION_PATHS.get(kind, UNDECLARABLE_SPEC_PATH)}`"
                    ),
                )
            )
    for rule in LANE_VALUE_RULES.get(lane, ()):
        nodes = sorted(
            (node for node in graph.nodes if node.kind == rule.kind),
            key=lambda item: item.id,
        )
        allowed = ", ".join(rule.allowed)
        for node in nodes:
            value = node.attrs.get(rule.attr)
            if rule.boolean:
                if isinstance(value, bool):
                    continue
                if value is None and not rule.required:
                    continue
                reason = (
                    f"{rule.kind}.{rule.attr} on node {node.id} must be a "
                    "declared boolean (true or false)"
                )
            elif (isinstance(value, str) and value in rule.allowed) or (
                value is None and not rule.required
            ):
                continue
            elif value is None:
                reason = (
                    f"{rule.kind}.{rule.attr} on node {node.id} is not "
                    f"declared; allowed values: {allowed}"
                )
            else:
                reason = (
                    f"{rule.kind}.{rule.attr} on node {node.id} has "
                    f"unsupported value {value!r}; allowed values: {allowed}"
                )
            unsupported_values.append(
                LanePreflightUnsupportedValue(
                    code=rule.code,
                    node_id=node.id,
                    kind=rule.kind,
                    attr=rule.attr,
                    reason=reason,
                )
            )
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
            for group in requirement.all_or_none_groups:
                declared = [attr for attr in group if attr in node.attrs]
                if not declared or len(declared) == len(group):
                    continue
                for attr in group:
                    if attr in node.attrs:
                        continue
                    missing_attrs.append(
                        LanePreflightMissingAttr(
                            node_id=node.id,
                            kind=node.kind,
                            attr=attr,
                            reason=(
                                f"lane {lane} requires the whole group "
                                f"{', '.join(group)} once any member is declared"
                            ),
                        )
                    )
    if lane == "enclosure-pipeline":
        _apply_mechanical_findings(graph, missing_nodes, missing_attrs, unsupported_values)
    if lane == "board-pipeline":
        _apply_evidence_declaration_findings(graph, unsupported_values, root)
    status = (
        "declarations_complete"
        if not missing_nodes and not missing_attrs and not unsupported_values
        else "declarations_incomplete"
    )
    return LanePreflightLaneReport(
        lane=lane,
        status=status,
        missing_nodes=missing_nodes,
        missing_attrs=missing_attrs,
        unsupported_values=unsupported_values,
        firmware_coverage=(
            _firmware_coverage_diagnostic(graph)
            if lane == "firmware-pipeline"
            else None
        ),
    )


def _apply_mechanical_findings(
    graph: DesignGraph,
    missing_nodes: list[LanePreflightMissingNode],
    missing_attrs: list[LanePreflightMissingAttr],
    unsupported_values: list[LanePreflightUnsupportedValue],
) -> None:
    """Fold the graph-only mechanical structure findings into the lane report.

    Missing nodes/attributes dedupe against declarations already reported by
    the requirement loop; every other mechanical finding code surfaces as an
    unsupported value so a structural gap can never pass silently.
    """
    reported_nodes = {(item.kind, item.reason) for item in missing_nodes}
    reported_attrs = {(item.node_id, item.attr) for item in missing_attrs}
    for finding in collect_mechanical_findings(graph):
        if finding.code == "mechanical.node.missing":
            key = (finding.node_kind, finding.detail)
            if key in reported_nodes:
                continue
            reported_nodes.add(key)
            missing_nodes.append(
                LanePreflightMissingNode(
                    kind=finding.node_kind or finding.code,
                    required_count=1,
                    present_count=0,
                    reason=finding.detail,
                )
            )
        elif finding.code == "mechanical.attribute.missing":
            key = (finding.node_id, finding.attribute)
            if key in reported_attrs:
                continue
            reported_attrs.add(key)
            missing_attrs.append(
                LanePreflightMissingAttr(
                    node_id=finding.node_id or finding.code,
                    kind=finding.node_kind or finding.code,
                    attr=finding.attribute or finding.code,
                    reason=finding.detail,
                )
            )
        else:
            unsupported_values.append(
                LanePreflightUnsupportedValue(
                    # collect_mechanical_findings is graph-only, so only the
                    # mechanical.* codes reachable here need the cast.
                    code=cast(LanePreflightUnsupportedCode, finding.code),
                    node_id=finding.node_id or finding.code,
                    kind=finding.node_kind or finding.code,
                    attr=finding.attribute or finding.code,
                    reason=finding.detail,
                )
            )


def _apply_evidence_declaration_findings(
    graph: DesignGraph,
    unsupported_values: list[LanePreflightUnsupportedValue],
    root: Path | None,
) -> None:
    """Fold declared-but-unresolved evidence attributes into the lane report.

    A declared evidence attribute that does not resolve to a measured record
    surfaces as ``declared_unverified``; the L3 report never grants it
    confirmed status.
    """
    for finding in collect_evidence_declaration_findings(graph, root=root):
        unsupported_values.append(
            LanePreflightUnsupportedValue(
                code=finding.code,
                node_id=finding.node_id or finding.code,
                kind=finding.kind or finding.code,
                attr=finding.attr or finding.code,
                reason=finding.detail,
            )
        )


def _firmware_coverage_diagnostic(graph: DesignGraph) -> dict[str, Any] | None:
    """Evaluate firmware coverage for the preflight diagnostic surface.

    Only a graph that declares ``firmware.module`` is covered at all; a
    registry load failure or an extraction failure degrades the entry to
    ``"unknown"`` — it is never recorded as a pass it did not earn.
    """
    if not any(node.kind == "firmware.module" for node in graph.nodes):
        return None
    try:
        registry = load_firmware_capability_registry()
    except Exception as exc:  # diagnostic degrades to "unknown", never raises
        return {
            "status": "unknown",
            "reason": f"firmware capability registry could not be loaded: {exc}",
            "findings": [],
        }
    try:
        report = check_firmware_coverage(graph, registry.document)
    except GraphExtractionError as exc:
        return {
            "status": "unknown",
            "reason": f"firmware lane extraction failed: {exc}",
            "findings": [],
        }
    return report.to_dict()


def run_lane_preflight(
    graph: DesignGraph,
    lanes: tuple[str, ...] | None = None,
    *,
    root: Path | None = None,
) -> LanePreflightReport:
    """Report the declaration gaps of every requested lane in one result."""
    selected = LANE_IDS if lanes is None else tuple(sorted(set(lanes)))
    unknown = [lane for lane in selected if lane not in LANE_REQUIREMENTS]
    if unknown:
        raise ValueError("unknown preflight lanes: " + ", ".join(sorted(unknown)))
    reports = [
        _lane_report(graph, lane, LANE_REQUIREMENTS[lane], root)
        for lane in selected
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
            {node.kind for node in lane.missing_nodes} | {attr.kind for attr in lane.missing_attrs}
        )
        for kind in kinds:
            requirement = requirements.get(kind)
            missing_node = next(
                (node for node in lane.missing_nodes if node.kind == kind), None
            )
            required = requirement.minimum_count if requirement is not None else 0
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
                    required_attrs=(
                        list(requirement.attrs) if requirement is not None else []
                    ),
                    missing_attrs=[
                        attr for attr in lane.missing_attrs if attr.kind == kind
                    ],
                )
            )
    return entries


def missing_declaration_action(report: LanePreflightReport) -> str | None:
    """Render the declarations to add to the design input as one instruction."""
    entries = missing_declarations(report)
    unsupported_parts: list[str] = [
        f"{lane_report.lane}: {item.reason} [{item.code}]"
        for lane_report in report.lanes
        for item in lane_report.unsupported_values
    ]
    if not entries and not unsupported_parts:
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
            names = ", ".join(sorted({f"{entry.kind}.{item.attr}" for item in entry.missing_attrs}))
            nodes = ", ".join(sorted({item.node_id for item in entry.missing_attrs}))
            parts.append(
                f"{entry.lane}: add attrs [{names}] to existing node(s) [{nodes}] "
                f"under `{entry.spec_path}`"
            )
    action = (
        "Add the missing declarations to the design input spec "
        "(DesignFixtureSpec) and rebuild the fixture; declarations are never "
        "auto-completed. " + "; ".join(parts)
    ) if parts else (
        "Fix the unsupported declaration values in the design input spec "
        "(DesignFixtureSpec) and rebuild the fixture; declarations are never "
        "auto-completed."
    )
    if unsupported_parts:
        action += (
            " Unsupported declared values: " + "; ".join(unsupported_parts)
        )
    return action


__all__ = [
    "LANE_IDS",
    "LANE_NODE_EXACT_COUNTS",
    "LANE_REQUIREMENTS",
    "LANE_VALUE_RULES",
    "PREFLIGHT_CHECKED_PREDICATES",
    "PREFLIGHT_UNCHECKED_PREDICATES",
    "SPEC_DECLARATION_PATHS",
    "UNDECLARABLE_SPEC_PATH",
    "LaneAttrValueRule",
    "LaneNodeRequirement",
    "missing_declaration_action",
    "missing_declarations",
    "run_lane_preflight",
]
