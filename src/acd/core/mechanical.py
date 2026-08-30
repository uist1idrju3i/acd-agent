"""Typed extraction of the mechanical lane from a design graph."""

from __future__ import annotations

import math
from dataclasses import dataclass

from acd.core.electrical import GraphExtractionError, extract_electrical_lane
from acd.schema.design_graph import DesignGraph, GraphNode

REQUIRED_MECHANICAL_ATTRS: dict[str, tuple[str, ...]] = {
    "mechanical.outline": (
        "width_mm",
        "depth_mm",
        "thickness_mm",
        "corner_radius_mm",
        "mount_hole_count",
        "unit",
        "origin",
        "y_axis",
        "position_source",
        "position_source_ref",
    ),
    "mechanical.component_body": (
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
    ),
    "mechanical.connector_opening": (
        "face",
        "center_x_mm",
        "center_y_mm",
        "width_mm",
        "height_mm",
        "margin_mm",
        "dimensions_source",
        "dimensions_source_ref",
        "dimensions_checked_at",
    ),
    "mechanical.board_edge_overhang": (
        "component_refdes",
        "edge",
        "overhang_mm",
        "requirement_id",
    ),
    "mechanical.enclosure": (
        "wall_thickness_mm",
        "min_wall_thickness_mm",
        "internal_clearance_mm",
        "lid_fit_gap_mm",
        "standoff_height_mm",
        "standoff_radius_mm",
        "fastener_method",
        "standoff_pilot_hole_diameter_mm",
        "lid_screw_hole_diameter_mm",
        "material",
        "unit",
        "tolerance_mm",
        "interference_tolerance_mm3",
        "tolerance_source",
        "tolerance_source_ref",
    ),
}


@dataclass(frozen=True)
class MountHoleView:
    index: int
    x_mm: float
    y_mm: float
    diameter_mm: float


@dataclass(frozen=True)
class OutlineView:
    node_id: str
    width_mm: float
    depth_mm: float
    thickness_mm: float
    corner_radius_mm: float
    unit: str
    origin: str
    y_axis: str
    mount_holes: tuple[MountHoleView, ...]
    position_source: str
    position_source_ref: str


@dataclass(frozen=True)
class ComponentBodyView:
    node_id: str
    component_id: str
    x_mm: float
    y_mm: float
    width_mm: float
    depth_mm: float
    height_mm: float
    body_type: str
    mounting_side: str
    rotation_deg: float
    position_source: str
    position_source_ref: str
    dimensions_source: str
    dimensions_source_ref: str
    dimensions_checked_at: str


@dataclass(frozen=True)
class ConnectorOpeningView:
    node_id: str
    component_id: str
    face: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    height_mm: float
    margin_mm: float
    dimensions_source: str
    dimensions_source_ref: str
    dimensions_checked_at: str


@dataclass(frozen=True)
class BoardEdgeOverhangView:
    node_id: str
    component_id: str
    component_refdes: str
    edge: str
    overhang_mm: float
    requirement_id: str


@dataclass(frozen=True)
class EnclosureView:
    node_id: str
    wall_thickness_mm: float
    min_wall_thickness_mm: float
    internal_clearance_mm: float
    lid_fit_gap_mm: float
    standoff_height_mm: float
    standoff_radius_mm: float
    fastener_method: str
    standoff_pilot_hole_diameter_mm: float
    lid_screw_hole_diameter_mm: float
    material: str
    unit: str
    tolerance_mm: float
    interference_tolerance_mm3: float
    tolerance_source: str
    tolerance_source_ref: str


@dataclass(frozen=True)
class MechanicalLane:
    outline: OutlineView
    component_bodies: tuple[ComponentBodyView, ...]
    connector_openings: tuple[ConnectorOpeningView, ...]
    board_edge_overhangs: tuple[BoardEdgeOverhangView, ...]
    enclosure: EnclosureView

    def body_for_component(self, component_id: str) -> ComponentBodyView:
        for body in self.component_bodies:
            if body.component_id == component_id:
                return body
        raise KeyError(component_id)


def _str_attr(node: GraphNode, key: str) -> str:
    value = node.attrs.get(key)
    if not isinstance(value, str) or not value:
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not a string")
    return value


def _float_attr(node: GraphNode, key: str) -> float:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not a number")
    return float(value)


def _mount_holes(node: GraphNode) -> tuple[MountHoleView, ...]:
    count_value = node.attrs.get("mount_hole_count")
    if isinstance(count_value, bool) or not isinstance(count_value, int) or count_value < 1:
        raise GraphExtractionError(f"node {node.id!r}: attr 'mount_hole_count' is invalid")
    holes: list[MountHoleView] = []
    for index in range(1, count_value + 1):
        holes.append(
            MountHoleView(
                index=index,
                x_mm=_float_attr(node, f"mount_hole_{index}_x_mm"),
                y_mm=_float_attr(node, f"mount_hole_{index}_y_mm"),
                diameter_mm=_float_attr(node, f"mount_hole_{index}_diameter_mm"),
            )
        )
    return tuple(holes)


def extract_mechanical_lane(graph: DesignGraph) -> MechanicalLane:
    electrical = extract_electrical_lane(graph)
    components = {component.node_id for component in electrical.components}
    outlines: list[OutlineView] = []
    bodies: list[ComponentBodyView] = []
    openings: list[ConnectorOpeningView] = []
    overhangs: list[BoardEdgeOverhangView] = []
    enclosures: list[EnclosureView] = []

    for node in graph.nodes:
        if node.kind == "mechanical.outline":
            depends_on_board = [dep for dep in node.depends_on if dep == electrical.board.node_id]
            if len(depends_on_board) != 1:
                raise GraphExtractionError(
                    f"node {node.id!r} must depend on electrical board {electrical.board.node_id!r}"
                )
            width_mm = _float_attr(node, "width_mm")
            depth_mm = _float_attr(node, "depth_mm")
            thickness_mm = _float_attr(node, "thickness_mm")
            if (
                width_mm != electrical.board.width_mm
                or depth_mm != electrical.board.height_mm
                or thickness_mm != electrical.board.thickness_mm
            ):
                raise GraphExtractionError(
                    f"node {node.id!r}: outline does not match electrical board declaration"
                )
            unit = _str_attr(node, "unit")
            origin = _str_attr(node, "origin")
            y_axis = _str_attr(node, "y_axis")
            if (unit, origin, y_axis) != (
                electrical.board.unit,
                electrical.board.origin,
                electrical.board.y_axis,
            ):
                raise GraphExtractionError(f"node {node.id!r}: coordinate declaration mismatch")
            outlines.append(
                OutlineView(
                    node_id=node.id,
                    width_mm=width_mm,
                    depth_mm=depth_mm,
                    thickness_mm=thickness_mm,
                    corner_radius_mm=_float_attr(node, "corner_radius_mm"),
                    unit=unit,
                    origin=origin,
                    y_axis=y_axis,
                    mount_holes=_mount_holes(node),
                    position_source=_str_attr(node, "position_source"),
                    position_source_ref=_str_attr(node, "position_source_ref"),
                )
            )
        elif node.kind == "mechanical.component_body":
            component_ids = [dep for dep in node.depends_on if dep in components]
            if len(component_ids) != 1:
                raise GraphExtractionError(
                    f"node {node.id!r} must depend on exactly one electrical component"
                )
            body_type = _str_attr(node, "body_type")
            height_mm = _float_attr(node, "height_mm")
            if body_type not in {"solid", "none"}:
                raise GraphExtractionError(
                    f"node {node.id!r}: body_type must be 'solid' or 'none'"
                )
            if body_type == "none" and height_mm != 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: body_type=none requires height_mm=0"
                )
            if body_type == "solid" and height_mm <= 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: solid body requires positive height_mm"
                )
            bodies.append(
                ComponentBodyView(
                    node_id=node.id,
                    component_id=component_ids[0],
                    x_mm=_float_attr(node, "x_mm"),
                    y_mm=_float_attr(node, "y_mm"),
                    width_mm=_float_attr(node, "width_mm"),
                    depth_mm=_float_attr(node, "depth_mm"),
                    height_mm=height_mm,
                    body_type=body_type,
                    mounting_side=_str_attr(node, "mounting_side"),
                    rotation_deg=_float_attr(node, "rotation_deg"),
                    position_source=_str_attr(node, "position_source"),
                    position_source_ref=_str_attr(node, "position_source_ref"),
                    dimensions_source=_str_attr(node, "dimensions_source"),
                    dimensions_source_ref=_str_attr(node, "dimensions_source_ref"),
                    dimensions_checked_at=_str_attr(node, "dimensions_checked_at"),
                )
            )
        elif node.kind == "mechanical.connector_opening":
            component_ids = [dep for dep in node.depends_on if dep in components]
            if len(component_ids) != 1:
                raise GraphExtractionError(
                    f"node {node.id!r} must depend on exactly one electrical component"
                )
            openings.append(
                ConnectorOpeningView(
                    node_id=node.id,
                    component_id=component_ids[0],
                    face=_str_attr(node, "face"),
                    center_x_mm=_float_attr(node, "center_x_mm"),
                    center_y_mm=_float_attr(node, "center_y_mm"),
                    width_mm=_float_attr(node, "width_mm"),
                    height_mm=_float_attr(node, "height_mm"),
                    margin_mm=_float_attr(node, "margin_mm"),
                    dimensions_source=_str_attr(node, "dimensions_source"),
                    dimensions_source_ref=_str_attr(node, "dimensions_source_ref"),
                    dimensions_checked_at=_str_attr(node, "dimensions_checked_at"),
                )
            )
        elif node.kind == "mechanical.board_edge_overhang":
            component_ids = [dep for dep in node.depends_on if dep in components]
            if len(component_ids) != 1:
                raise GraphExtractionError(
                    f"node {node.id!r} must depend on exactly one electrical component"
                )
            component = electrical.component_by_id(component_ids[0])
            component_refdes = _str_attr(node, "component_refdes")
            if component_refdes != component.refdes:
                raise GraphExtractionError(
                    f"node {node.id!r}: component_refdes does not match depended component"
                )
            edge = _str_attr(node, "edge")
            if edge not in {"top", "bottom", "left", "right"}:
                raise GraphExtractionError(
                    f"node {node.id!r}: edge must be top, bottom, left, or right"
                )
            overhang_mm = _float_attr(node, "overhang_mm")
            if not math.isfinite(overhang_mm) or overhang_mm <= 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: overhang_mm must be finite and positive"
                )
            requirement_id = _str_attr(node, "requirement_id")
            overhangs.append(
                BoardEdgeOverhangView(
                    node_id=node.id,
                    component_id=component_ids[0],
                    component_refdes=component_refdes,
                    edge=edge,
                    overhang_mm=overhang_mm,
                    requirement_id=requirement_id,
                )
            )
        elif node.kind == "mechanical.enclosure":
            fastener_method = _str_attr(node, "fastener_method")
            if fastener_method != "self_tapping_screw_m2":
                raise GraphExtractionError(
                    f"node {node.id!r}: fastener_method must be 'self_tapping_screw_m2'"
                )
            pilot_diameter = _float_attr(node, "standoff_pilot_hole_diameter_mm")
            if not math.isfinite(pilot_diameter) or pilot_diameter <= 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: standoff_pilot_hole_diameter_mm must be finite and positive"
                )
            lid_diameter = _float_attr(node, "lid_screw_hole_diameter_mm")
            if not math.isfinite(lid_diameter) or lid_diameter <= 0:
                raise GraphExtractionError(
                    f"node {node.id!r}: lid_screw_hole_diameter_mm must be finite and positive"
                )
            standoff_radius = _float_attr(node, "standoff_radius_mm")
            if standoff_radius - pilot_diameter / 2 < _float_attr(
                node, "min_wall_thickness_mm"
            ):
                raise GraphExtractionError(
                    f"node {node.id!r}: standoff pilot hole leaves less than min_wall_thickness_mm"
                )
            if lid_diameter < pilot_diameter:
                raise GraphExtractionError(
                    f"node {node.id!r}: lid screw hole diameter must be at least the pilot diameter"
                )
            enclosures.append(
                EnclosureView(
                    node_id=node.id,
                    wall_thickness_mm=_float_attr(node, "wall_thickness_mm"),
                    min_wall_thickness_mm=_float_attr(node, "min_wall_thickness_mm"),
                    internal_clearance_mm=_float_attr(node, "internal_clearance_mm"),
                    lid_fit_gap_mm=_float_attr(node, "lid_fit_gap_mm"),
                    standoff_height_mm=_float_attr(node, "standoff_height_mm"),
                    standoff_radius_mm=standoff_radius,
                    fastener_method=fastener_method,
                    standoff_pilot_hole_diameter_mm=pilot_diameter,
                    lid_screw_hole_diameter_mm=lid_diameter,
                    material=_str_attr(node, "material"),
                    unit=_str_attr(node, "unit"),
                    tolerance_mm=_float_attr(node, "tolerance_mm"),
                    interference_tolerance_mm3=_float_attr(
                        node, "interference_tolerance_mm3"
                    ),
                    tolerance_source=_str_attr(node, "tolerance_source"),
                    tolerance_source_ref=_str_attr(node, "tolerance_source_ref"),
                )
            )

    if len(outlines) != 1:
        raise GraphExtractionError(
            f"expected exactly one mechanical.outline node, got {len(outlines)}"
        )
    if len(enclosures) != 1:
        raise GraphExtractionError(
            f"expected exactly one mechanical.enclosure node, got {len(enclosures)}"
        )
    body_component_ids = {body.component_id for body in bodies}
    missing_body_components = sorted(components - body_component_ids)
    if missing_body_components:
        raise GraphExtractionError(
            "missing mechanical.component_body nodes for electrical components: "
            + ", ".join(missing_body_components)
        )
    for overhang in overhangs:
        matching_bodies = [body for body in bodies if body.component_id == overhang.component_id]
        if not matching_bodies:
            raise GraphExtractionError(
                f"node {overhang.node_id!r}: depended component has no mechanical.component_body"
            )
        body = matching_bodies[0]
        if body.body_type != "solid":
            raise GraphExtractionError(
                f"node {overhang.node_id!r}: overhang component body must be solid"
            )
        if body.rotation_deg != 0:
            raise GraphExtractionError(
                f"node {overhang.node_id!r}: overhang component body rotation_deg must be 0"
            )
    seen_overhangs: set[tuple[str, str]] = set()
    for overhang in overhangs:
        key = (overhang.component_id, overhang.edge)
        if key in seen_overhangs:
            raise GraphExtractionError(
                "duplicate board edge overhang declaration for "
                f"component {overhang.component_id!r} edge {overhang.edge!r}"
            )
        seen_overhangs.add(key)
    return MechanicalLane(
        outline=outlines[0],
        component_bodies=tuple(bodies),
        connector_openings=tuple(openings),
        board_edge_overhangs=tuple(sorted(overhangs, key=lambda item: item.node_id)),
        enclosure=enclosures[0],
    )
