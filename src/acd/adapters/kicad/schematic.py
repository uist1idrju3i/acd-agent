"""Deterministic KiCad schematic projection.

Places every component on a fixed grid and connects pins with global labels
(one label per connected pin, anchored at the pin connection point). Explicit
no-connect markers are emitted for unused pins. ``PWR_FLAG`` symbols are added
to nets that have no driving pin so that ERC power checks are meaningful
rather than suppressed. A fixed sheet note states the label-based connection
convention so that a reader does not read the absence of drawn wires as a
missing connection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from acd.adapters.kicad.emit import det_uuid, fmt, requote
from acd.adapters.kicad.library import ParsedSymbol, SymbolLibrary, SymbolPin
from acd.core.electrical import ComponentView, ElectricalLane, LibraryPin
from acd.core.sexpr import Quoted, SExpr, Sym, dumps

SCH_VERSION = "20250114"
SCH_FORMAT_NAME = "kicad_sch"

_GRID = 1.27  # KiCad schematic grid in mm
_COLS = 6
_CELL_W = 80.0
_CELL_H = 70.0
_ORIGIN_X = 40.64
_ORIGIN_Y = 40.64

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
class PlacedSymbol:
    component: ComponentView
    symbol: ParsedSymbol
    x_mm: float
    y_mm: float


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
        _property("Reference", comp.refdes, placed.x_mm, placed.y_mm - 5.08, hide=False),
        _property("Value", comp.value, placed.x_mm, placed.y_mm + 5.08, hide=False),
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
        path = Path(comp.library.symbol_file)
        if not path.is_absolute():
            path = fixture_dir / path
        parsed = symbol_library.load(comp.library.symbol, path, comp.library.symbol_sha256)
        symbols[comp.refdes] = parsed
        lib_symbols.setdefault(parsed.lib_id, parsed)

    root_uuid = det_uuid("sheet", "root")
    placements: list[PlacedSymbol] = []
    ordered = sorted(lane.components, key=_refdes_key)
    for index, comp in enumerate(ordered):
        col = index % _COLS
        row = index // _COLS
        x = _snap(_ORIGIN_X + col * _CELL_W)
        y = _snap(_ORIGIN_Y + row * _CELL_H)
        placements.append(PlacedSymbol(component=comp, symbol=symbols[comp.refdes], x_mm=x, y_mm=y))

    net_names = {net.node_id: net.name for net in lane.nets}
    pins_by_refdes: dict[str, dict[str, tuple[str | None, bool]]] = {}
    for pin_view in lane.pins:
        comp = lane.component_by_id(pin_view.component_id)
        pins_by_refdes.setdefault(comp.refdes, {})[pin_view.pad] = (
            pin_view.net_id,
            pin_view.no_connect,
        )

    body: list[list[SExpr]] = []
    labels: list[list[SExpr]] = []
    notes: list[list[SExpr]] = [
        _text_note(
            CONNECTION_CONVENTION_NOTE,
            _snap(_ORIGIN_X),
            _snap(_ORIGIN_Y - 20.0),
            "connection-convention",
        )
    ]
    no_connects: list[list[SExpr]] = []
    for placed in placements:
        comp = placed.component
        extra = {"MPN": comp.mpn, "LCSC": comp.lcsc} if comp.mpn else {}
        body.append(_symbol_instance(placed, root_uuid, extra, project_name))
        pad_map = pins_by_refdes.get(comp.refdes, {})
        for sym_pin in placed.symbol.pins:
            px, py = _pin_point(placed.x_mm, placed.y_mm, sym_pin)
            mapping = pad_map.get(sym_pin.number)
            if mapping is None:
                raise ValueError(
                    f"symbol pin {comp.refdes}.{sym_pin.number} has no graph pin node"
                )
            net_id, no_connect = mapping
            if net_id is not None:
                labels.append(
                    _global_label(
                        net_names[net_id],
                        px,
                        py,
                        _label_rotation(sym_pin),
                        f"{comp.refdes}.{sym_pin.number}",
                    )
                )
            elif no_connect:
                no_connects.append(_no_connect(px, py, f"{comp.refdes}.{sym_pin.number}"))

    flag_nets = nets_needing_pwr_flag(lane, symbols)
    lib_symbols.setdefault(pwr_flag_symbol.lib_id, pwr_flag_symbol)
    for flag_index, net_id in enumerate(sorted(flag_nets)):
        refdes = f"PWR{flag_index + 1:02d}"
        x = _snap(_ORIGIN_X + flag_index * 20.0)
        y = _snap(_ORIGIN_Y + math.ceil(len(ordered) / _COLS) * _CELL_H + 40.0)
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
        placed_flag = PlacedSymbol(component=flag_comp, symbol=pwr_flag_symbol, x_mm=x, y_mm=y)
        node = _symbol_instance(placed_flag, root_uuid, {}, project_name)
        # PWR_FLAG has no footprint
        body.append(node)
        flag_pin = pwr_flag_symbol.pins[0]
        px, py = _pin_point(x, y, flag_pin)
        labels.append(
            _global_label(net_names[net_id], px, py, _label_rotation(flag_pin), f"{refdes}.1")
        )

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
        [Sym("paper"), Quoted("A2")],
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
