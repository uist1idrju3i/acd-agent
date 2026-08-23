"""Pure deterministic validation for design decision rationale."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Final

from acd.schema import (
    DesignGraph,
    RationaleCoverageReport,
    RationaleDocument,
    RationaleOrphan,
    RationaleRecordSubject,
    RationaleSubject,
    RationaleUnclassified,
    RationaleUnknownProvenance,
    RationaleUntraceable,
)
from acd.schema.common import Sha256

REQUIRED_RATIONALE_ATTRS: Final[dict[str, frozenset[str]]] = {
    "electrical.board": frozenset(
        {
            "layers",
            "material",
            "thickness_mm",
            "copper_oz",
            "finish",
            "width_mm",
            "height_mm",
            "assembly_side",
            "antenna_keepout",
            "min_track_mm",
            "min_clearance_mm",
            "edge_copper_clearance_mm",
            "via_diameter_mm",
            "via_drill_mm",
            "allowable_temperature_rise_k",
            "width_basis_equation",
            "width_measurement_tolerance_mm",
            "ground_plane_net",
            "ground_plane_layers",
            "ground_plane_min_island_area_mm2",
            "stitch_via_wavelength_fraction",
            "stitch_via_max_frequency_hz",
            "stitch_via_refill_max_iterations",
        }
    ),
    "electrical.component": frozenset(
        {
            "mpn",
            "lcsc",
            "value",
            "footprint",
            "assembly",
            "placement_x_mm",
            "placement_y_mm",
            "placement_rotation_deg",
            "radio_module",
        }
    ),
    "electrical.placement_group": frozenset(),
    "electrical.net": frozenset(
        {
            "width_basis",
            "voltage_nominal_v",
            "current_max_a",
            "manufacturing_margin_mm",
            "power_rail",
            "power_source_pin",
        }
    ),
    "fab.order_intent": frozenset(
        {
            "fab_profile",
            "quantity_pcs",
            "surface_finish",
            "soldermask_color",
            "assembly_sides",
            "pcba_class_target",
            "delivery_format",
        }
    ),
    "firmware.module": frozenset({"mcu_component", "entry_state"}),
    "firmware.state": frozenset({"initial"}),
    "firmware.state_transition": frozenset({"from_state", "to_state", "trigger"}),
    "firmware.sequence_step": frozenset(
        {"step_index", "actor", "target", "action"}
    ),
    "firmware.pin_assignment": frozenset({"gpio", "net"}),
    "mechanical.board_edge_overhang": frozenset({"edge", "overhang_mm"}),
    "mechanical.component_body": frozenset(
        {"body_type", "mounting_side", "x_mm", "y_mm", "rotation_deg"}
    ),
    "mechanical.connector_opening": frozenset(
        {"face", "center_x_mm", "center_y_mm", "width_mm", "height_mm", "margin_mm"}
    ),
    "mechanical.enclosure": frozenset(
        {
            "material",
            "wall_thickness_mm",
            "min_wall_thickness_mm",
            "internal_clearance_mm",
            "standoff_height_mm",
            "standoff_radius_mm",
            "lid_fit_gap_mm",
            "tolerance_mm",
            "interference_tolerance_mm3",
        }
    ),
    "mechanical.outline": frozenset(
        {
            "width_mm",
            "depth_mm",
            "thickness_mm",
            "corner_radius_mm",
            "mount_hole_count",
            "mount_hole_1_x_mm",
            "mount_hole_1_y_mm",
            "mount_hole_1_diameter_mm",
            "mount_hole_2_x_mm",
            "mount_hole_2_y_mm",
            "mount_hole_2_diameter_mm",
            "mount_hole_3_x_mm",
            "mount_hole_3_y_mm",
            "mount_hole_3_diameter_mm",
            "mount_hole_4_x_mm",
            "mount_hole_4_y_mm",
            "mount_hole_4_diameter_mm",
        }
    ),
    "mechanical.silk_graphic": frozenset(
        {
            "layer",
            "stroke_width_mm",
            "polygon_points",
            "graphic_parts",
            "source_path",
            "source_sha256",
            "source_viewbox_mm",
            "source_scale",
            "placed_size_mm",
            "board_edge_margin_mm",
            "placement_search_order",
            "placement_center_mm",
            "rotation_degrees",
            "qr_module_matrix",
            "qr_source_module_pitch_mm",
            "qr_module_pitch_mm",
            "qr_quiet_zone_modules",
        }
    ),
    "mechanical.silk_text": frozenset(
        {
            "x_mm",
            "y_mm",
            "rotation_deg",
            "layer",
            "text",
            "height_mm",
            "stroke_width_mm",
            "board_edge_margin_mm",
            "placement_search_order",
            "placement_offset_step_mm",
            "placement_search_limit_mm",
            "placement_safety_margin_mm",
        }
    ),
    "safety.boundary": frozenset(
        {
            "profile",
            "intended_use",
            "max_net_voltage_v",
            "max_current_a",
            "module_certified",
        }
    ),
}

RATIONALE_EXEMPT_ATTRS: Final[dict[str, dict[str, str]]] = {
    "electrical.placement_group": {
        "primary_refdes": (
            "Placement group membership is an L2 search constraint; "
            "L1 gates remain authoritative."
        ),
        "coupled_refdes": (
            "Placement group membership is an L2 search constraint; "
            "L1 gates remain authoritative."
        ),
        "max_distance_mm": (
            "Placement coupling is a bounded L2 search input; "
            "the decoupling-distance gate remains authoritative."
        ),
        "move_together": (
            "Move-together semantics steer candidate generation and do not "
            "grant pass authority."
        ),
    },
    "design.functional_block": {
        "block_id": (
            "This declaration is a requirement-derived selection of the applicable "
            "predicate contract rather than a physical design parameter; rationale "
            "records are held by the nets and components forming the topology."
        )
    },
    "electrical.board": {
        "copper_thickness_source": (
            "Manufacturing copper thickness is sourced from the fab "
            "capability declaration."
        ),
        "fab_capability_checked_at": (
            "Fab capability metadata records when the profile was "
            "checked."
        ),
        "fab_capability_source": (
            "Fab capability metadata identifies the external "
            "manufacturing source."
        ),
        "mounting_hole_m2_count": (
            "M2 hole count is justified by the required outline hole "
            "dimensions."
        ),
        "ipc2221_external_b": (
            "IPC-2221 external-layer constant is a standard-defined "
            "calculation input."
        ),
        "ipc2221_external_c": (
            "IPC-2221 external-layer constant is a standard-defined "
            "calculation input."
        ),
        "ipc2221_external_k": (
            "IPC-2221 external-layer constant is a standard-defined "
            "calculation input."
        ),
        "ipc2221_internal_b": (
            "IPC-2221 internal-layer constant is a standard-defined "
            "calculation input."
        ),
        "ipc2221_internal_c": (
            "IPC-2221 internal-layer constant is a standard-defined "
            "calculation input."
        ),
        "ipc2221_internal_k": (
            "IPC-2221 internal-layer constant is a standard-defined "
            "calculation input."
        ),
        "outer_copper_thickness_um": (
            "Outer copper thickness is a manufacturing capability "
            "value derived from copper weight."
        ),
        "origin": "Origin is the graph coordinate convention.",
        "unit": "Unit is the graph coordinate convention.",
        "y_axis": "The y-axis direction is the graph coordinate convention.",
        "stitch_via_basis_source": (
            "Stitch-via basis metadata identifies the source of the "
            "calculation."
        ),
        "stitch_via_cost_note": (
            "Stitch-via cost metadata records manufacturing context "
            "rather than a design choice."
        ),
        "stitch_via_dielectric_constant": (
            "The dielectric constant is a source-model input "
            "for the stitch-via calculation."
        ),
        "width_basis_source": (
            "Trace-width basis metadata identifies the source of the width "
            "calculation."
        ),
    },
    "electrical.component": {
        "certification_checked_at": (
            "Certification check time records external verification provenance."
        ),
        "certification_document_refs": (
            "Certification document references identify external source material."
        ),
        "certification_grant_dates": (
            "Certification grant dates record external certification provenance."
        ),
        "certification_hvin": (
            "Certification HVIN records the externally certified module identifier."
        ),
        "certification_ids": (
            "Certification identifiers record external regulatory provenance."
        ),
        "certification_source": (
            "Certification source identifies the external certification publisher."
        ),
        "certification_source_ref": (
            "Certification source reference identifies the external source location."
        ),
        "cpl_position_basis": (
            "CPL position basis records the evidence basis for an already "
            "selected placement."
        ),
        "cpl_position_evidence_at": "CPL position evidence timestamp is provenance metadata.",
        "cpl_position_evidence_basis": "CPL position evidence describes the verification basis.",
        "cpl_position_evidence_method": "CPL position evidence records the verification method.",
        "cpl_position_evidence_note": "CPL position evidence notes are provenance metadata.",
        "cpl_position_evidence_revision": (
            "CPL position evidence revision identifies the "
            "checked graph revision."
        ),
        "cpl_position_source_url": (
            "CPL position source URL identifies the primary placement "
            "source."
        ),
        "cpl_rotation_basis": (
            "CPL rotation basis records the evidence basis for an already "
            "selected rotation."
        ),
        "cpl_rotation_evidence_at": "CPL rotation evidence timestamp is provenance metadata.",
        "cpl_rotation_evidence_basis": "CPL rotation evidence describes the verification basis.",
        "cpl_rotation_evidence_method": "CPL rotation evidence records the verification method.",
        "cpl_rotation_evidence_note": "CPL rotation evidence notes are provenance metadata.",
        "cpl_rotation_evidence_revision": (
            "CPL rotation evidence revision identifies the "
            "checked graph revision."
        ),
        "cpl_rotation_geometry_exception": (
            "CPL geometry exception records a "
            "source-footprint geometry fact."
        ),
        "cpl_rotation_geometry_exception_reason": (
            "CPL geometry exception reason explains a "
            "source-footprint fact."
        ),
        "cpl_rotation_geometry_exception_source": (
            "CPL geometry exception source identifies "
            "its evidence."
        ),
        "cpl_rotation_offset_deg": (
            "CPL rotation offset is a footprint transformation "
            "metadata value."
        ),
        "cpl_rotation_pin_aliases": "CPL rotation pin aliases are symbol-library metadata.",
        "cpl_rotation_pin_functions": "CPL rotation pin functions are symbol-library metadata.",
        "cpl_rotation_polarized": "CPL polarization is a footprint fact used during verification.",
        "cpl_rotation_source_url": (
            "CPL rotation source URL identifies the primary footprint "
            "source."
        ),
        "cpl_rotation_unverified_pad_reason": (
            "CPL unverified-pad reason records an evidence "
            "limitation."
        ),
        "cpl_rotation_unverified_pad_source": "CPL unverified-pad source identifies its evidence.",
        "cpl_rotation_unverified_pads": "CPL unverified-pad data records footprint evidence.",
        "decoupling_target": (
            "Decoupling target identifies the component relationship "
            "justified by the power design."
        ),
        "footprint_file": "Footprint file metadata identifies the library artifact.",
        "footprint_sha256": "Footprint hash is provenance metadata for the library artifact.",
        "footprint_source": "Footprint source identifies the library provenance.",
        "footprint_source_ref": "Footprint source reference identifies the library provenance.",
        "jlcpcb_class": "JLCPCB class is a supplier availability fact.",
        "overlay_file": "Overlay file metadata identifies the project-local library artifact.",
        "overlay_sha256": "Overlay hash is provenance metadata for the library artifact.",
        "placement_source": "Placement source identifies the deterministic placement procedure.",
        "placement_source_ref": (
            "Placement source reference identifies the placement "
            "procedure version."
        ),
        "refdes": "Reference designator is an identifier, not an engineering choice.",
        "stock_checked_at": "Stock check timestamp is supplier provenance metadata.",
        "symbol": "Symbol name is library metadata.",
        "symbol_file": "Symbol file metadata identifies the library artifact.",
        "symbol_sha256": "Symbol hash is provenance metadata for the library artifact.",
        "symbol_source": "Symbol source identifies the library provenance.",
        "symbol_source_ref": "Symbol source reference identifies the library provenance.",
    },
    "electrical.net": {
        "name": "Net name is an identifier used by the connectivity model.",
        "width_basis_source": (
            "Trace-width basis metadata identifies the source of the width "
            "calculation."
        ),
    },
    "fab.order_intent": {
        "profile_fetched_at": "Fab profile fetch time is manufacturing-source provenance.",
        "profile_source": "Fab profile source identifies the manufacturing capability declaration.",
    },
    "electrical.pin": {
        "component": "Pin component connectivity is justified by the component and net decisions.",
        "net": "Pin net connectivity is justified by the net and firmware decisions.",
        "pad": "Pad mapping is footprint connectivity metadata.",
        "no_connect": (
            "No-connect state is connectivity metadata justified by the "
            "surrounding net design."
        ),
    },
    "firmware.module": {
        "module_name": "Module name is a human-readable display label, not a design decision.",
    },
    "firmware.state": {
        "state_name": "State name is a human-readable display label, not a design decision.",
    },
    "firmware.pin_assignment": {},
    "mechanical.board_edge_overhang": {
        "component_refdes": "Component reference is an identifier for the overhang subject.",
        "requirement_id": "Requirement identifier records the source requirement.",
    },
    "mechanical.component_body": {
        "depth_mm": "Body depth is a datasheet geometry fact.",
        "dimensions_checked_at": "Body dimension check time is evidence provenance.",
        "dimensions_source": "Body dimensions source identifies the datasheet or library evidence.",
        "dimensions_source_ref": "Body dimensions source reference identifies the evidence.",
        "height_mm": "Body height is a datasheet geometry fact.",
        "position_source": "Body position source identifies the placement evidence.",
        "position_source_ref": "Body position source reference identifies the placement evidence.",
        "width_mm": "Body width is a datasheet geometry fact.",
    },
    "mechanical.connector_opening": {
        "connector": "Connector identifier is a mechanical mapping fact.",
        "dimensions_checked_at": "Opening dimension check time is evidence provenance.",
        "dimensions_source": (
            "Opening dimensions source identifies the datasheet or library "
            "evidence."
        ),
        "dimensions_source_ref": "Opening dimensions source reference identifies the evidence.",
    },
    "mechanical.enclosure": {
        "tolerance_source": "Enclosure tolerance source identifies the manufacturing or CAD basis.",
        "tolerance_source_ref": "Enclosure tolerance source reference identifies the evidence.",
        "unit": "Unit is the graph coordinate convention.",
    },
    "mechanical.outline": {
        "mounting_hole_m2_count": (
            "M2 hole count is a connectivity/mechanical requirement "
            "already represented by the hole dimensions."
        ),
        "origin": "Origin is the graph coordinate convention.",
        "position_source": "Outline position source identifies the mechanical evidence.",
        "position_source_ref": (
            "Outline position source reference identifies the mechanical "
            "evidence."
        ),
        "unit": "Unit is the graph coordinate convention.",
        "y_axis": "The y-axis direction is the graph coordinate convention.",
    },
    "mechanical.silk_graphic": {
        "board_edge_margin_source": (
            "Graphic edge-margin source identifies the manufacturing "
            "evidence."
        ),
        "placement_basis": "Graphic placement basis records the resolver input provenance.",
        "role": "Graphic role is an identifier for the declared artwork.",
    },
    "mechanical.silk_text": {
        "board_edge_margin_source": (
            "Text edge-margin source identifies the manufacturing "
            "evidence."
        ),
        "placement_basis": "Text placement basis records the resolver input provenance.",
        "placement_evidence": (
            "Placement evidence records resolver output rather than an "
            "independent design choice."
        ),
        "placement_evidence_input_sha256": "Placement evidence input hash is provenance metadata.",
        "placement_evidence_output_sha256": (
            "Placement evidence output hash is provenance "
            "metadata."
        ),
        "placement_reference": "Placement reference identifies the associated component.",
        "placement_rotation_deg": (
            "Silkscreen placement rotation is a derived alias of "
            "rotation_deg."
        ),
        "placement_rotation_degrees": (
            "Silkscreen placement rotation is a derived alias of "
            "rotation_deg."
        ),
        "placement_source": "Placement source identifies the deterministic silkscreen procedure.",
        "placement_source_ref": (
            "Placement source reference identifies the silkscreen "
            "procedure version."
        ),
        "role": "Text role is an identifier for the declared label.",
    },
    "requirement": {
        "text": "Requirement text is the primary requirement fact used as rationale evidence.",
    },
    "safety.boundary": {
        "battery": (
            "Battery exclusion is a dependent safety flag justified by the "
            "safety-scope decision."
        ),
        "charger": (
            "Charger exclusion is a dependent safety flag justified by the "
            "safety-scope decision."
        ),
        "motor_actuator_laser": (
            "Actuator exclusion is a dependent safety flag justified by "
            "the safety-scope decision."
        ),
    },
}


def subject_hash_for(
    graph: DesignGraph, subject_nodes: list[str], subject_attrs: list[str]
) -> Sha256:
    values: list[list[object]] = []
    for node_id in sorted(subject_nodes):
        node = graph.node_by_id(node_id)
        for attr in sorted(subject_attrs):
            if attr not in node.attrs:
                raise KeyError(f"node {node_id!r} has no attribute {attr!r}")
            values.append([node_id, attr, node.attrs[attr]])
    encoded = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _subject(node_id: str, attr: str) -> RationaleSubject:
    return RationaleSubject(node_id=node_id, attr=attr)


def check_rationale_coverage(
    graph: DesignGraph, document: RationaleDocument
) -> RationaleCoverageReport:
    graph_id_match = document.graph_id == graph.graph_id
    revision_match = document.revision == graph.revision
    nodes = {node.id: node for node in graph.nodes}
    required = [
        (node.id, attr)
        for node in graph.nodes
        for attr in sorted(REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset()))
        if attr in node.attrs
    ]
    required_set = set(required)
    unclassified = [
        RationaleUnclassified(
            node_id=node.id,
            node_kind=node.kind,
            attr=attr,
            reason="attribute is absent from both rationale classification tables",
        )
        for node in graph.nodes
        for attr in sorted(node.attrs)
        if attr not in REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset())
        and attr not in RATIONALE_EXEMPT_ATTRS.get(node.kind, {})
    ]
    covered: dict[tuple[str, str], list[str]] = defaultdict(list)
    stale: list[RationaleRecordSubject] = []
    unknown: list[RationaleUnknownProvenance] = []
    orphan: list[RationaleOrphan] = []
    untraceable: list[RationaleUntraceable] = []

    for record in document.records:
        record_subjects = [
            (node_id, attr)
            for node_id in record.subject_nodes
            for attr in record.subject_attrs
        ]
        if not record.driving_requirements and not record.driving_requirement_refs:
            untraceable.extend(
                RationaleUntraceable(
                    rationale_id=record.rationale_id,
                    subject=_subject(node_id, attr),
                )
                for node_id, attr in record_subjects
                if (node_id, attr) in required_set
            )
        record_stale = record.target_revision != graph.revision
        record_orphan = False
        for node_id, attr in record_subjects:
            subject = _subject(node_id, attr)
            node = nodes.get(node_id)
            if node is None:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id, subject=subject, reason="unknown node"
                ))
                record_orphan = True
                continue
            if attr not in node.attrs:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id, subject=subject, reason="unknown attribute"
                ))
                record_orphan = True
                continue
            if record_stale:
                stale.append(RationaleRecordSubject(
                    rationale_id=record.rationale_id, subject=subject
                ))
        for requirement_id in record.driving_requirements:
            requirement = nodes.get(requirement_id)
            if requirement is None or requirement.kind not in {"requirement", "safety.boundary"}:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id,
                    subject=_subject(record.subject_nodes[0], record.subject_attrs[0]),
                    reason=f"invalid driving requirement {requirement_id!r}",
                ))
                record_orphan = True
        hash_matches = False
        if not record_stale and not record_orphan:
            try:
                hash_matches = record.subject_hash == subject_hash_for(
                    graph, record.subject_nodes, record.subject_attrs
                )
            except KeyError:
                hash_matches = False
        if not hash_matches and not record_stale and not record_orphan:
            stale.extend(
                RationaleRecordSubject(
                    rationale_id=record.rationale_id,
                    subject=_subject(node_id, attr),
                )
                for node_id, attr in record_subjects
            )
        if record.provenance.script_hash == "unknown":
            unknown.append(RationaleUnknownProvenance(rationale_id=record.rationale_id))
        if (
            not record_stale
            and not record_orphan
            and hash_matches
            and record.provenance.script_hash != "unknown"
        ):
            for subject in record_subjects:
                covered[subject].append(record.rationale_id)

    missing = [
        _subject(node_id, attr)
        for node_id, attr in required
        if not covered[(node_id, attr)]
    ]
    conflicting = [
        RationaleRecordSubject(rationale_id=record_id, subject=_subject(*subject))
        for subject, record_ids in sorted(covered.items())
        if len(record_ids) > 1
        for record_id in record_ids
    ]
    failed = (
        not graph_id_match
        or not revision_match
        or bool(missing or stale or unknown or orphan or untraceable or conflicting)
        or bool(unclassified)
    )
    return RationaleCoverageReport(
        status="fail" if failed else "pass",
        graph_id=graph.graph_id,
        revision=graph.revision,
        graph_id_match=graph_id_match,
        revision_match=revision_match,
        missing=missing,
        stale=stale,
        unknown_provenance=unknown,
        orphan=orphan,
        untraceable=untraceable,
        conflicting=conflicting,
        unclassified=unclassified,
        required_count=len(required_set),
        covered_count=sum(1 for subject in required_set if covered[subject]),
        record_count=len(document.records),
    )
