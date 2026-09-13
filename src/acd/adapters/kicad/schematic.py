"""Deterministic KiCad schematic projection.

Places every component on symbol-fitted row and column pitches and connects
pins with global labels (one label per connected pin, anchored at the pin
connection point). Explicit no-connect markers are emitted for unused pins.
``PWR_FLAG`` symbols are added to nets that have no driving pin so that ERC
power checks are meaningful rather than suppressed. A deterministic collision
check rejects labels that remain over symbols or properties after one outward
Reference/Value adjustment. A fixed sheet note states the label-based
connection convention so that a reader does not read the absence of drawn
wires as a missing connection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from acd.adapters.kicad.emit import det_uuid, fmt, requote
from acd.adapters.kicad.library import ParsedSymbol, SymbolLibrary, SymbolPin
from acd.adapters.kicad.paper import select_paper
from acd.core.electrical import ComponentView, ElectricalLane, LibraryPin
from acd.core.library_assets import resolve_fixture_library_path
from acd.core.sexpr import Quoted, SExpr, Sym, dumps

SCH_VERSION = "20250114"
SCH_FORMAT_NAME = "kicad_sch"

_GRID = 1.27  # KiCad schematic grid in mm
_MAX_COLS = 6
_GAP = 10.16
LABEL_ALLOWANCE = 3.0
_LABEL_HEIGHT = 2.0
_ORIGIN_X = 40.64
_ORIGIN_Y = 40.64
_PAGE_MARGIN = 20.0
# Approximate sheet width of the connection-convention note for page sizing.
_NOTE_EXTENT_X = 170.0
_NOTE_EXTENT_Y = 5.0

PWR_FLAG_LIB_ID = "power:PWR_FLAG"

# Connectivity is expressed with global labels instead of drawn wires, so the
# sheet carries a note that makes the convention explicit to a human reader.
CONNECTION_CONVENTION_NOTE = (
    "Connectivity is expressed with global net labels at each pin "
    "(no drawn wires). Nets with the same label are connected."
)


def _snap(value: float) -> float:
    return round(round(value / _GRID) * _GRID, 4)


@dataclass(frozen=True)
class _Box:
    left: float
    right: float
    top: float
    bottom: float


@dataclass(frozen=True)
class _LabelPlacement:
    refdes: str
    pin: str
    net: str
    x_mm: float
    y_mm: float
    rotation: int
    allowance: float

    @property
    def box(self) -> _Box:
        if self.rotation == 0:
            return _Box(
                _snap(self.x_mm),
                _snap(self.x_mm + self.allowance),
                _snap(self.y_mm - _LABEL_HEIGHT / 2),
                _snap(self.y_mm + _LABEL_HEIGHT / 2),
            )
        if self.rotation == 180:
            return _Box(
                _snap(self.x_mm - self.allowance),
                _snap(self.x_mm),
                _snap(self.y_mm - _LABEL_HEIGHT / 2),
                _snap(self.y_mm + _LABEL_HEIGHT / 2),
            )
        if self.rotation == 90:
            return _Box(
                _snap(self.x_mm - _LABEL_HEIGHT / 2),
                _snap(self.x_mm + _LABEL_HEIGHT / 2),
                _snap(self.y_mm - self.allowance),
                _snap(self.y_mm),
            )
        return _Box(
            _snap(self.x_mm - _LABEL_HEIGHT / 2),
            _snap(self.x_mm + _LABEL_HEIGHT / 2),
            _snap(self.y_mm),
            _snap(self.y_mm + self.allowance),
        )


@dataclass
class PlacedSymbol:
    component: ComponentView
    symbol: ParsedSymbol
    x_mm: float
    y_mm: float
    extent: _Box
    base_box: _Box
    reference_box: _Box
    value_box: _Box
    reference_adjusted: bool = False
    value_adjusted: bool = False

    def property_box(self, property_name: str) -> _Box:
        if property_name == "Reference":
            box = self.reference_box
            shift = -2.54 if self.reference_adjusted else 0.0
        else:
            box = self.value_box
            shift = 2.54 if self.value_adjusted else 0.0
        return _Box(
            self.x_mm + box.left,
            self.x_mm + box.right,
            self.y_mm + box.top + shift,
            self.y_mm + box.bottom + shift,
        )


@dataclass(frozen=True)
class _LayoutItem:
    component: ComponentView
    symbol: ParsedSymbol
    labels: tuple[str, ...]
    col: int
    row: int
    extent: _Box
    base_box: _Box
    reference_box: _Box
    value_box: _Box


def _direction(rotation: int) -> tuple[float, float]:
    return {
        0: (1.0, 0.0),
        180: (-1.0, 0.0),
        90: (0.0, -1.0),
        270: (0.0, 1.0),
    }[rotation % 360]


def _base_box(symbol: ParsedSymbol) -> _Box:
    if not symbol.pins:
        return _Box(-5.08, 5.08, -5.08, 5.08)
    points = [(pin.x_mm, -pin.y_mm) for pin in symbol.pins]
    return _Box(
        _snap(min(point[0] for point in points)),
        _snap(max(point[0] for point in points)),
        _snap(min(point[1] for point in points)),
        _snap(max(point[1] for point in points)),
    )


def _symbol_geometry(
    symbol: ParsedSymbol,
    net_label_names: list[str],
    *,
    reference: str = "",
    value: str = "",
) -> tuple[_Box, _Box, _Box, _Box]:
    base = _base_box(symbol)
    left, right, top, bottom = base.left, base.right, base.top, base.bottom
    for index, pin in enumerate(symbol.pins):
        name = net_label_names[index] if index < len(net_label_names) else ""
        allowance = len(name) * 1.27 * 0.9 + LABEL_ALLOWANCE if name else 2.54
        rotation = _label_rotation(pin)
        dx, dy = _direction(rotation)
        px, py = pin.x_mm, -pin.y_mm
        left = min(left, px + dx * allowance)
        right = max(right, px + dx * allowance)
        top = min(top, py + dy * allowance)
        bottom = max(bottom, py + dy * allowance)

    reference_width = len(reference) * 1.27 * 0.9
    value_width = len(value) * 1.27 * 0.9
    reference_box = _Box(
        -reference_width / 2,
        reference_width / 2,
        _snap(base.top - 2.54) - 1.27,
        _snap(base.top - 2.54) + 1.27,
    )
    value_box = _Box(
        -value_width / 2,
        value_width / 2,
        _snap(base.bottom + 2.54) - 1.27,
        _snap(base.bottom + 2.54) + 1.27,
    )
    left = min(left, reference_box.left, value_box.left)
    right = max(right, reference_box.right, value_box.right)
    top = min(top, reference_box.top, value_box.top)
    bottom = max(bottom, reference_box.bottom, value_box.bottom)
    return (
        _Box(_snap(left), _snap(right), _snap(top), _snap(bottom)),
        base,
        reference_box,
        value_box,
    )


def _boxes_overlap(first: _Box, second: _Box) -> bool:
    return (
        first.left < second.right
        and second.left < first.right
        and first.top < second.bottom
        and second.top < first.bottom
    )


def _placed_base_box(placed: PlacedSymbol) -> _Box:
    return _Box(
        placed.x_mm + placed.base_box.left,
        placed.x_mm + placed.base_box.right,
        placed.y_mm + placed.base_box.top,
        placed.y_mm + placed.base_box.bottom,
    )


def _adjust_properties(
    placements: list[PlacedSymbol],
    labels: list[_LabelPlacement],
) -> None:
    for label in labels:
        for placed in placements:
            for property_name in ("Reference", "Value"):
                property_box = placed.property_box(property_name)
                if not _boxes_overlap(label.box, property_box):
                    continue
                if property_name == "Reference" and not placed.reference_adjusted:
                    placed.reference_adjusted = True
                    continue
                if property_name == "Value" and not placed.value_adjusted:
                    placed.value_adjusted = True


def _label_collisions(
    placements: list[PlacedSymbol],
    labels: list[_LabelPlacement],
) -> list[str]:
    """Return deterministic label collisions without changing placements."""
    collisions: list[str] = []
    for label in labels:
        for placed in placements:
            for property_name in ("Reference", "Value"):
                property_box = placed.property_box(property_name)
                if _boxes_overlap(label.box, property_box):
                    collisions.append(
                        f"schematic label collision: {label.refdes}.{label.pin} "
                        f"label '{label.net}' overlaps {placed.component.refdes}."
                        f"{property_name} (fail-closed)"
                    )
        for other in placements:
            if other.component.refdes == label.refdes:
                continue
            if _boxes_overlap(label.box, _placed_base_box(other)):
                collisions.append(
                    f"schematic label collision: {label.refdes}.{label.pin} "
                    f"label '{label.net}' overlaps "
                    f"{other.component.refdes} body (fail-closed)"
                )
    for index, label in enumerate(labels):
        for other in labels[index + 1 :]:
            if _boxes_overlap(label.box, other.box):
                collisions.append(
                    f"schematic label collision: {label.refdes}.{label.pin} "
                    f"label '{label.net}' overlaps {other.refdes}.{other.pin} "
                    f"label '{other.net}' (fail-closed)"
                )
    return collisions


def _pin_point(placed_x: float, placed_y: float, pin: SymbolPin) -> tuple[float, float]:
    """Schematic-sheet coordinates of a pin connection point (rotation 0)."""
    return round(placed_x + pin.x_mm, 4), round(placed_y - pin.y_mm, 4)


def _effects(hide: bool = False) -> list[SExpr]:
    node: list[SExpr] = [
        Sym("effects"),
        [Sym("font"), [Sym("size"), "1.27", "1.27"]],
    ]
    if hide:
        node.append([Sym("hide"), Sym("yes")])
    return node


def _property(name: str, value: str, x: float, y: float, *, hide: bool) -> list[SExpr]:
    return [
        Sym("property"),
        Quoted(name),
        Quoted(value),
        [Sym("at"), fmt(x), fmt(y), "0"],
        _effects(hide=hide),
    ]


def _symbol_instance(
    placed: PlacedSymbol,
    root_uuid: str,
    extra_properties: dict[str, str],
    project_name: str,
) -> list[SExpr]:
    comp = placed.component
    sym_uuid = det_uuid("symbol", comp.refdes)
    node: list[SExpr] = [
        Sym("symbol"),
        [Sym("lib_id"), Quoted(placed.symbol.lib_id)],
        [Sym("at"), fmt(placed.x_mm), fmt(placed.y_mm), "0"],
        [Sym("unit"), "1"],
        [Sym("exclude_from_sim"), Sym("no")],
        [Sym("in_bom"), Sym("yes" if comp.jlcpcb_class != "none" else "no")],
        [Sym("on_board"), Sym("yes")],
        [Sym("dnp"), Sym("no")],
        [Sym("uuid"), Quoted(sym_uuid)],
        _property(
            "Reference",
            comp.refdes,
            placed.x_mm,
            _snap(
                _snap(placed.y_mm + placed.reference_box.top + 1.27)
                + (-2.54 if placed.reference_adjusted else 0.0)
            ),
            hide=False,
        ),
        _property(
            "Value",
            comp.value,
            placed.x_mm,
            _snap(
                _snap(placed.y_mm + placed.value_box.top + 1.27)
                + (2.54 if placed.value_adjusted else 0.0)
            ),
            hide=False,
        ),
        _property("Footprint", comp.library.footprint, placed.x_mm, placed.y_mm, hide=True),
        _property("Datasheet", "", placed.x_mm, placed.y_mm, hide=True),
    ]
    for prop_name, prop_value in sorted(extra_properties.items()):
        node.append(_property(prop_name, prop_value, placed.x_mm, placed.y_mm, hide=True))
    for pin in placed.symbol.pins:
        pin_uuid = det_uuid("pin", comp.refdes, pin.number)
        node.append([Sym("pin"), Quoted(pin.number), [Sym("uuid"), Quoted(pin_uuid)]])
    node.append(
        [
            Sym("instances"),
            [
                Sym("project"),
                Quoted(project_name),
                [
                    Sym("path"),
                    Quoted(f"/{root_uuid}"),
                    [Sym("reference"), Quoted(comp.refdes)],
                    [Sym("unit"), "1"],
                ],
            ],
        ]
    )
    return node


def _global_label(net_name: str, x: float, y: float, rotation: int, key: str) -> list[SExpr]:
    return [
        Sym("global_label"),
        Quoted(net_name),
        [Sym("shape"), Sym("passive")],
        [Sym("at"), fmt(x), fmt(y), str(rotation)],
        _effects(),
        [Sym("uuid"), Quoted(det_uuid("label", key))],
    ]


def _text_note(content: str, x: float, y: float, key: str) -> list[SExpr]:
    return [
        Sym("text"),
        Quoted(content),
        [Sym("exclude_from_sim"), Sym("no")],
        [Sym("at"), fmt(x), fmt(y), "0"],
        [
            Sym("effects"),
            [Sym("font"), [Sym("size"), "3.81", "3.81"]],
            [Sym("justify"), Sym("left"), Sym("bottom")],
        ],
        [Sym("uuid"), Quoted(det_uuid("text", key))],
    ]


def _no_connect(x: float, y: float, key: str) -> list[SExpr]:
    return [
        Sym("no_connect"),
        [Sym("at"), fmt(x), fmt(y)],
        [Sym("uuid"), Quoted(det_uuid("nc", key))],
    ]


def _refdes_key(comp: ComponentView) -> tuple[str, int, str]:
    digits = comp.refdes[1:]
    return comp.refdes[0], int(digits) if digits.isdigit() else 0, comp.refdes


def _label_rotation(pin: SymbolPin) -> int:
    """Global label rotation so its text points away from the symbol body."""
    rot = int(pin.rotation_deg) % 360
    return {0: 180, 90: 270, 180: 0, 270: 90}[rot]


_PWR_FLAG_DRIVE_TYPES = frozenset({"power_out", "output"})

_EMPTY_LIBRARY = LibraryPin(
    symbol=PWR_FLAG_LIB_ID,
    symbol_file="",
    symbol_source="",
    symbol_source_ref="",
    symbol_sha256="",
    footprint="",
    footprint_file="",
    footprint_source="",
    footprint_source_ref="",
    footprint_sha256="",
)


def nets_needing_pwr_flag(lane: ElectricalLane, symbols: dict[str, ParsedSymbol]) -> list[str]:
    """Nets that contain a power_in pin but no driving pin."""
    needing: list[str] = []
    for net in lane.nets:
        has_power_in = False
        has_driver = False
        for pin_view in lane.pins:
            if pin_view.net_id != net.node_id:
                continue
            comp = lane.component_by_id(pin_view.component_id)
            parsed = symbols[comp.refdes]
            for sym_pin in parsed.pins:
                if sym_pin.number != pin_view.pad:
                    continue
                if sym_pin.electrical_type == "power_in":
                    has_power_in = True
                if sym_pin.electrical_type in _PWR_FLAG_DRIVE_TYPES:
                    has_driver = True
        if has_power_in and not has_driver:
            needing.append(net.node_id)
    return needing


def generate_schematic(
    lane: ElectricalLane,
    symbol_library: SymbolLibrary,
    fixture_dir: Path,
    pwr_flag_symbol: ParsedSymbol,
    project_name: str,
) -> str:
    """Render the schematic file content for the electrical lane."""
    if not project_name:
        raise ValueError("schematic project name is unknown (fail-closed)")
    symbols: dict[str, ParsedSymbol] = {}
    lib_symbols: dict[str, ParsedSymbol] = {}
    for comp in lane.components:
        path = resolve_fixture_library_path(comp.library.symbol_file, fixture_dir)
        parsed = symbol_library.load(
            comp.library.symbol, path, comp.library.symbol_sha256
        )
        symbols[comp.refdes] = parsed
        lib_symbols.setdefault(parsed.lib_id, parsed)

    net_names = {net.node_id: net.name for net in lane.nets}
    pins_by_refdes: dict[str, dict[str, tuple[str | None, bool]]] = {}
    for pin_view in lane.pins:
        comp = lane.component_by_id(pin_view.component_id)
        pins_by_refdes.setdefault(comp.refdes, {})[pin_view.pad] = (
            pin_view.net_id,
            pin_view.no_connect,
        )

    ordered = sorted(lane.components, key=_refdes_key)
    cols = (
        max(1, min(_MAX_COLS, math.ceil(math.sqrt(len(ordered)))))
        if ordered
        else 1
    )
    layout_items: list[_LayoutItem] = []
    for index, comp in enumerate(ordered):
        symbol = symbols[comp.refdes]
        label_names: list[str] = []
        for pin in symbol.pins:
            mapping = pins_by_refdes.get(comp.refdes, {}).get(pin.number)
            if mapping is None:
                raise ValueError(
                    f"symbol pin {comp.refdes}.{pin.number} has no graph pin node"
                )
            net_id, _is_no_connect = mapping
            label_names.append(net_names[net_id] if net_id is not None else "")
        extent, base_box, reference_box, value_box = _symbol_geometry(
            symbol,
            label_names,
            reference=comp.refdes,
            value=comp.value,
        )
        layout_items.append(
            _LayoutItem(
                component=comp,
                symbol=symbol,
                labels=tuple(label_names),
                col=index % cols,
                row=index // cols,
                extent=extent,
                base_box=base_box,
                reference_box=reference_box,
                value_box=value_box,
            )
        )

    flag_nets = nets_needing_pwr_flag(lane, symbols)
    lib_symbols.setdefault(pwr_flag_symbol.lib_id, pwr_flag_symbol)
    comp_count = len(ordered)
    if comp_count:
        last_row = (comp_count - 1) // cols
        spare_cells = cols - (comp_count - last_row * cols)
    else:
        last_row = 0
        spare_cells = 0
    first_new_row = math.ceil(comp_count / cols) if comp_count else 0
    for flag_index, net_id in enumerate(sorted(flag_nets)):
        refdes = f"PWR{flag_index + 1:02d}"
        if flag_index < spare_cells:
            flag_col = comp_count - last_row * cols + flag_index
            flag_row = last_row
        else:
            extra = flag_index - spare_cells
            flag_col = extra % cols
            flag_row = first_new_row + extra // cols
        flag_comp = ComponentView(
            node_id=f"pwrflag.{refdes.lower()}",
            refdes=refdes,
            value="PWR_FLAG",
            mpn="",
            lcsc="",
            jlcpcb_class="none",
            assembly="not_fitted",
            library=_EMPTY_LIBRARY,
        )
        extent, base_box, reference_box, value_box = _symbol_geometry(
            pwr_flag_symbol,
            [net_names[net_id]],
            reference=refdes,
            value=flag_comp.value,
        )
        layout_items.append(
            _LayoutItem(
                component=flag_comp,
                symbol=pwr_flag_symbol,
                labels=(net_names[net_id],),
                col=flag_col,
                row=flag_row,
                extent=extent,
                base_box=base_box,
                reference_box=reference_box,
                value_box=value_box,
            )
        )

    column_widths: dict[int, float] = {}
    column_lefts: dict[int, float] = {}
    row_heights: dict[int, float] = {}
    row_tops: dict[int, float] = {}
    for item in layout_items:
        width = item.extent.right - item.extent.left
        height = item.extent.bottom - item.extent.top
        if width > column_widths.get(item.col, -1.0):
            column_widths[item.col] = width
            column_lefts[item.col] = item.extent.left
        if height > row_heights.get(item.row, -1.0):
            row_heights[item.row] = height
            row_tops[item.row] = item.extent.top
    column_pitches = {
        col: column_widths[col] + _GAP for col in column_widths
    }
    row_pitches = {row: row_heights[row] + _GAP for row in row_heights}

    def _offset_before(values: dict[int, float], index: int) -> float:
        return sum(values.get(previous, 0.0) for previous in range(index))

    placements: list[PlacedSymbol] = []
    item_labels: list[tuple[PlacedSymbol, tuple[str, ...]]] = []
    for item in layout_items:
        x = _snap(
            _ORIGIN_X
            + _offset_before(column_pitches, item.col)
            - column_lefts[item.col]
        )
        y = _snap(
            _ORIGIN_Y
            + _offset_before(row_pitches, item.row)
            - row_tops[item.row]
        )
        placed = PlacedSymbol(
            component=item.component,
            symbol=item.symbol,
            x_mm=x,
            y_mm=y,
            extent=item.extent,
            base_box=item.base_box,
            reference_box=item.reference_box,
            value_box=item.value_box,
        )
        placements.append(placed)
        item_labels.append((placed, item.labels))

    root_uuid = det_uuid("sheet", "root")
    label_placements: list[_LabelPlacement] = []
    no_connects: list[list[SExpr]] = []
    for placed, item_label_names in item_labels:
        for sym_pin, label_name in zip(
            placed.symbol.pins, item_label_names, strict=True
        ):
            px, py = _pin_point(placed.x_mm, placed.y_mm, sym_pin)
            if label_name:
                label_placements.append(
                    _LabelPlacement(
                        refdes=placed.component.refdes,
                        pin=sym_pin.number,
                        net=label_name,
                        x_mm=px,
                        y_mm=py,
                        rotation=_label_rotation(sym_pin),
                        allowance=len(label_name) * 1.27 * 0.9 + LABEL_ALLOWANCE,
                    )
                )
            else:
                mapping = pins_by_refdes.get(placed.component.refdes, {}).get(
                    sym_pin.number
                )
                if mapping is not None and mapping[1]:
                    no_connects.append(
                        _no_connect(
                            px,
                            py,
                            f"{placed.component.refdes}.{sym_pin.number}",
                        )
                    )

    _adjust_properties(placements, label_placements)
    collisions = _label_collisions(placements, label_placements)
    if collisions:
        raise ValueError(collisions[0])

    body: list[list[SExpr]] = []
    labels: list[list[SExpr]] = []
    for placed in placements:
        comp = placed.component
        extra = {"MPN": comp.mpn, "LCSC": comp.lcsc} if comp.mpn else {}
        body.append(_symbol_instance(placed, root_uuid, extra, project_name))
    for label in label_placements:
        labels.append(
            _global_label(
                label.net,
                label.x_mm,
                label.y_mm,
                label.rotation,
                f"{label.refdes}.{label.pin}",
            )
        )

    note_x = _snap(_ORIGIN_X)
    note_y = _snap(_ORIGIN_Y - 20.0)
    notes: list[list[SExpr]] = [
        _text_note(
            CONNECTION_CONVENTION_NOTE,
            note_x,
            note_y,
            "connection-convention",
        )
    ]
    extents_x = [note_x, note_x + _NOTE_EXTENT_X]
    extents_y = [note_y - _NOTE_EXTENT_Y, note_y + _NOTE_EXTENT_Y]
    for placed in placements:
        extents_x.extend(
            (placed.x_mm + placed.extent.left, placed.x_mm + placed.extent.right)
        )
        extents_y.extend(
            (placed.y_mm + placed.extent.top, placed.y_mm + placed.extent.bottom)
        )
        for property_name in ("Reference", "Value"):
            property_box = placed.property_box(property_name)
            extents_x.extend((property_box.left, property_box.right))
            extents_y.extend((property_box.top, property_box.bottom))
    for label in label_placements:
        extents_x.extend((label.box.left, label.box.right))
        extents_y.extend((label.box.top, label.box.bottom))

    min_x = min(extents_x)
    min_y = min(extents_y)
    max_x = max(extents_x)
    max_y = max(extents_y)
    if min_x < 0.0 or min_y < 0.0:
        raise ValueError(
            "schematic content extends outside the sheet origin (fail-closed)"
        )
    paper = select_paper(max_x + _PAGE_MARGIN, max_y + _PAGE_MARGIN)

    lib_symbols_node: list[SExpr] = [Sym("lib_symbols")]
    for lib_id in sorted(lib_symbols):
        entry = list(lib_symbols[lib_id].embedded)
        entry[0] = Sym("symbol")
        entry[1] = Quoted(lib_id)
        lib_symbols_node.append(requote(entry))

    doc: list[SExpr] = [
        Sym(SCH_FORMAT_NAME),
        [Sym("version"), SCH_VERSION],
        [Sym("generator"), Quoted("acd")],
        [Sym("generator_version"), Quoted("0.0.1")],
        [Sym("uuid"), Quoted(root_uuid)],
        [Sym("paper"), Quoted(paper)],
        lib_symbols_node,
    ]
    doc.extend(notes)
    doc.extend(no_connects)
    doc.extend(labels)
    doc.extend(body)
    doc.append(
        [
            Sym("sheet_instances"),
            [Sym("path"), Quoted("/"), [Sym("page"), Quoted("1")]],
        ]
    )
    return dumps(doc) + "\n"
