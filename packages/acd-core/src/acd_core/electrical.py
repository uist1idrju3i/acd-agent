"""Typed extraction of the electrical lane from a design graph.

Adapters consume these views instead of interpreting raw graph attributes, so
graph semantics stay in core. Missing or malformed attributes fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from acd_schema.design_graph import DesignGraph, GraphNode


class GraphExtractionError(ValueError):
    """Raised when the electrical lane cannot be extracted (fail-closed)."""


@dataclass(frozen=True)
class LibraryPin:
    symbol: str
    symbol_file: str
    symbol_source: str
    symbol_source_ref: str
    symbol_sha256: str
    footprint: str
    footprint_file: str
    footprint_source: str
    footprint_source_ref: str
    footprint_sha256: str


@dataclass(frozen=True)
class ComponentView:
    node_id: str
    refdes: str
    value: str
    mpn: str
    lcsc: str
    jlcpcb_class: str
    assembly: str
    library: LibraryPin
    overlay_file: str | None = None
    overlay_sha256: str | None = None
    decoupling_target: str | None = None
    cpl_position_basis: str | None = None
    cpl_position_source_url: str | None = None
    cpl_position_evidence_at: str | None = None
    cpl_position_evidence_method: str | None = None
    cpl_position_evidence_revision: str | None = None
    cpl_position_evidence_basis: str | None = None
    cpl_position_evidence_note: str | None = None
    cpl_rotation_basis: str | None = None
    cpl_rotation_source_url: str | None = None
    cpl_rotation_evidence_basis: str | None = None
    cpl_rotation_evidence_note: str | None = None
    cpl_rotation_evidence_at: str | None = None
    cpl_rotation_evidence_method: str | None = None
    cpl_rotation_evidence_revision: str | None = None
    cpl_rotation_offset_deg: float | None = None
    cpl_rotation_polarized: bool = True
    cpl_rotation_pin_functions: dict[str, str] = field(
        default_factory=lambda: dict[str, str]()
    )
    cpl_rotation_pin_aliases: dict[str, str] = field(
        default_factory=lambda: dict[str, str]()
    )


@dataclass(frozen=True)
class NetView:
    node_id: str
    name: str
    voltage_nominal_v: float | None


@dataclass(frozen=True)
class PinView:
    node_id: str
    component_id: str
    pad: str
    net_id: str | None
    no_connect: bool


@dataclass(frozen=True)
class BoardView:
    node_id: str
    width_mm: float
    height_mm: float
    layers: int
    thickness_mm: float
    unit: str
    origin: str
    y_axis: str
    min_track_mm: float
    min_clearance_mm: float
    via_drill_mm: float
    via_diameter_mm: float
    edge_copper_clearance_mm: float
    antenna_keepout: bool


@dataclass(frozen=True)
class ElectricalLane:
    components: tuple[ComponentView, ...]
    nets: tuple[NetView, ...]
    pins: tuple[PinView, ...]
    board: BoardView

    def component_by_id(self, node_id: str) -> ComponentView:
        for comp in self.components:
            if comp.node_id == node_id:
                return comp
        raise KeyError(node_id)

    def net_by_id(self, node_id: str) -> NetView:
        for net in self.nets:
            if net.node_id == node_id:
                return net
        raise KeyError(node_id)

    def pins_of_component(self, component_id: str) -> tuple[PinView, ...]:
        return tuple(pin for pin in self.pins if pin.component_id == component_id)

    def pads_of_net(self, net_id: str) -> tuple[tuple[str, str], ...]:
        """Return (refdes, pad) pairs connected to a net, in graph order."""
        pads: list[tuple[str, str]] = []
        for pin in self.pins:
            if pin.net_id == net_id:
                refdes = self.component_by_id(pin.component_id).refdes
                pads.append((refdes, pin.pad))
        return tuple(pads)


def _str_attr(node: GraphNode, key: str) -> str:
    value = node.attrs.get(key)
    if not isinstance(value, str) or (not value and key not in ("mpn", "lcsc")):
        if isinstance(value, str):
            return value
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not a string")
    return value


def _float_attr(node: GraphNode, key: str) -> float:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not a number")
    return float(value)


def _int_attr(node: GraphNode, key: str) -> int:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not an integer")
    return value


def _bool_attr(node: GraphNode, key: str) -> bool:
    value = node.attrs.get(key)
    if not isinstance(value, bool):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or not a boolean")
    return value


def _library_pin(node: GraphNode) -> LibraryPin:
    return LibraryPin(
        symbol=_str_attr(node, "symbol"),
        symbol_file=_str_attr(node, "symbol_file"),
        symbol_source=_str_attr(node, "symbol_source"),
        symbol_source_ref=_str_attr(node, "symbol_source_ref"),
        symbol_sha256=_str_attr(node, "symbol_sha256"),
        footprint=_str_attr(node, "footprint"),
        footprint_file=_str_attr(node, "footprint_file"),
        footprint_source=_str_attr(node, "footprint_source"),
        footprint_source_ref=_str_attr(node, "footprint_source_ref"),
        footprint_sha256=_str_attr(node, "footprint_sha256"),
    )


def _optional_str(node: GraphNode, key: str) -> str | None:
    value = node.attrs.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} must be a non-empty string")
    return value


def _optional_number(node: GraphNode, key: str) -> float | None:
    value = node.attrs.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} must be a number")
    return None if value is None else float(value)


def _optional_bool(node: GraphNode, key: str, default: bool) -> bool:
    value = node.attrs.get(key)
    if value is not None and not isinstance(value, bool):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} must be a boolean")
    return default if value is None else value


def _optional_string_map(node: GraphNode, key: str) -> dict[str, str]:
    value = node.attrs.get(key)
    if value is None:
        return {}
    if not isinstance(value, list):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} must be a string map list")
    result: dict[str, str] = {}
    for item in value:
        parts = item.split("=", 1)
        if len(parts) != 2 or not all(parts):
            raise GraphExtractionError(f"node {node.id!r}: attr {key!r} has invalid entry")
        result[parts[0]] = parts[1]
    return result


def extract_electrical_lane(graph: DesignGraph) -> ElectricalLane:
    components: list[ComponentView] = []
    nets: list[NetView] = []
    pins: list[PinView] = []
    boards: list[BoardView] = []
    for node in graph.nodes:
        if node.kind == "electrical.component":
            overlay_file = node.attrs.get("overlay_file")
            overlay_sha256 = node.attrs.get("overlay_sha256")
            decoupling_target = node.attrs.get("decoupling_target")
            if overlay_file is not None and not isinstance(overlay_file, str):
                raise GraphExtractionError(f"node {node.id!r}: overlay_file must be a string")
            if overlay_sha256 is not None and not isinstance(overlay_sha256, str):
                raise GraphExtractionError(f"node {node.id!r}: overlay_sha256 must be a string")
            if decoupling_target is not None and not isinstance(decoupling_target, str):
                raise GraphExtractionError(f"node {node.id!r}: decoupling_target must be a string")
            if (overlay_file is None) != (overlay_sha256 is None):
                raise GraphExtractionError(
                    f"node {node.id!r}: overlay_file and overlay_sha256 must be paired"
                )
            components.append(
                ComponentView(
                    node_id=node.id,
                    refdes=_str_attr(node, "refdes"),
                    value=_str_attr(node, "value"),
                    mpn=_str_attr(node, "mpn"),
                    lcsc=_str_attr(node, "lcsc"),
                    jlcpcb_class=_str_attr(node, "jlcpcb_class"),
                    assembly=_str_attr(node, "assembly"),
                    library=_library_pin(node),
                    overlay_file=overlay_file,
                    overlay_sha256=overlay_sha256,
                    decoupling_target=decoupling_target,
                    cpl_position_basis=_optional_str(node, "cpl_position_basis"),
                    cpl_position_source_url=_optional_str(node, "cpl_position_source_url"),
                    cpl_position_evidence_at=_optional_str(node, "cpl_position_evidence_at"),
                    cpl_position_evidence_method=_optional_str(
                        node, "cpl_position_evidence_method"
                    ),
                    cpl_position_evidence_revision=_optional_str(
                        node, "cpl_position_evidence_revision"
                    ),
                    cpl_position_evidence_basis=_optional_str(
                        node, "cpl_position_evidence_basis"
                    ),
                    cpl_position_evidence_note=_optional_str(
                        node, "cpl_position_evidence_note"
                    ),
                    cpl_rotation_basis=_optional_str(node, "cpl_rotation_basis"),
                    cpl_rotation_source_url=_optional_str(node, "cpl_rotation_source_url"),
                    cpl_rotation_evidence_basis=_optional_str(
                        node, "cpl_rotation_evidence_basis"
                    ),
                    cpl_rotation_evidence_note=_optional_str(
                        node, "cpl_rotation_evidence_note"
                    ),
                    cpl_rotation_evidence_at=_optional_str(node, "cpl_rotation_evidence_at"),
                    cpl_rotation_evidence_method=_optional_str(
                        node, "cpl_rotation_evidence_method"
                    ),
                    cpl_rotation_evidence_revision=_optional_str(
                        node, "cpl_rotation_evidence_revision"
                    ),
                    cpl_rotation_offset_deg=_optional_number(node, "cpl_rotation_offset_deg"),
                    cpl_rotation_polarized=_optional_bool(node, "cpl_rotation_polarized", True),
                    cpl_rotation_pin_functions=_optional_string_map(
                        node, "cpl_rotation_pin_functions"
                    ),
                    cpl_rotation_pin_aliases=_optional_string_map(
                        node, "cpl_rotation_pin_aliases"
                    ),
                )
            )
            if components[-1].assembly not in {"fitted", "not_fitted"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid assembly")
        elif node.kind == "electrical.net":
            voltage = node.attrs.get("voltage_nominal_v")
            nets.append(
                NetView(
                    node_id=node.id,
                    name=_str_attr(node, "name"),
                    voltage_nominal_v=(
                        float(voltage)
                        if isinstance(voltage, int | float) and not isinstance(voltage, bool)
                        else None
                    ),
                )
            )
        elif node.kind == "electrical.pin":
            net_value = node.attrs.get("net")
            if net_value is not None and not isinstance(net_value, str):
                raise GraphExtractionError(f"node {node.id!r}: attr 'net' must be a string or null")
            pins.append(
                PinView(
                    node_id=node.id,
                    component_id=_str_attr(node, "component"),
                    pad=_str_attr(node, "pad"),
                    net_id=net_value,
                    no_connect=_bool_attr(node, "no_connect"),
                )
            )
        elif node.kind == "electrical.board":
            unit = _str_attr(node, "unit")
            origin = _str_attr(node, "origin")
            y_axis = _str_attr(node, "y_axis")
            if unit != "mm" or origin != "board_upper_left" or y_axis != "down":
                raise GraphExtractionError(
                    f"node {node.id!r}: unsupported coordinate system "
                    f"(unit={unit!r}, origin={origin!r}, y_axis={y_axis!r})"
                )
            boards.append(
                BoardView(
                    node_id=node.id,
                    width_mm=_float_attr(node, "width_mm"),
                    height_mm=_float_attr(node, "height_mm"),
                    layers=_int_attr(node, "layers"),
                    thickness_mm=_float_attr(node, "thickness_mm"),
                    unit=unit,
                    origin=origin,
                    y_axis=y_axis,
                    min_track_mm=_float_attr(node, "min_track_mm"),
                    min_clearance_mm=_float_attr(node, "min_clearance_mm"),
                    via_drill_mm=_float_attr(node, "via_drill_mm"),
                    via_diameter_mm=_float_attr(node, "via_diameter_mm"),
                    edge_copper_clearance_mm=_float_attr(node, "edge_copper_clearance_mm"),
                    antenna_keepout=_bool_attr(node, "antenna_keepout"),
                )
            )
    if len(boards) != 1:
        raise GraphExtractionError(f"expected exactly one electrical.board node, got {len(boards)}")
    known_nets = {net.node_id for net in nets}
    known_components = {comp.node_id for comp in components}
    for pin in pins:
        if pin.component_id not in known_components:
            raise GraphExtractionError(f"pin {pin.node_id!r} references unknown component")
        if pin.net_id is not None and pin.net_id not in known_nets:
            raise GraphExtractionError(f"pin {pin.node_id!r} references unknown net")
        if pin.net_id is None and not pin.no_connect:
            raise GraphExtractionError(
                f"pin {pin.node_id!r} has no net and is not marked no_connect (unknown state)"
            )
    return ElectricalLane(
        components=tuple(components), nets=tuple(nets), pins=tuple(pins), board=boards[0]
    )
