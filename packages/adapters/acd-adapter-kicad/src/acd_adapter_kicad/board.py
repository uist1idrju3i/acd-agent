"""Deterministic KiCad board projection.

Embeds pinned footprint files verbatim (with position, reference, and pad net
assignments injected), draws the board outline and antenna keepout, and leaves
routing to the external router adapter. Net numbering is deterministic: nets
sorted by name, numbered from 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd_adapter_kicad.emit import det_uuid, fmt, requote
from acd_adapter_kicad.library import FootprintLibrary
from acd_adapter_kicad.overlay import apply_overlay
from acd_adapter_kicad.placement import (
    ANTENNA_MODULE_Y_MM,
    Placement,
    Rect,
    compute_placements,
)
from acd_core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    FootprintShape,
    KeepoutRect,
)
from acd_core.electrical import ElectricalLane
from acd_core.fab import FabProfile
from acd_core.sexpr import Quoted, SExpr, Sym, dumps

PCB_VERSION = "20241229"

_ANTENNA_KEEPOUT_HALF_WIDTH_MM = 7.0
_ANTENNA_KEEPOUT_DEPTH_MM = 4.6
_ANTENNA_KEEPOUT_PAD_CLEARANCE_MM = 0.3


@dataclass(frozen=True)
class BoardProjection:
    content: str
    net_numbers: dict[str, int]
    placements: tuple[Placement, ...]
    keepouts: tuple[KeepoutRect, ...]
    model: BoardModel
    overlays: tuple[dict[str, str], ...] = ()


def _setup(lane: ElectricalLane) -> list[SExpr]:
    return [
        Sym("setup"),
        [Sym("pad_to_mask_clearance"), "0"],
        [Sym("allow_soldermask_bridges_in_footprints"), Sym("no")],
    ]


_LAYERS: list[tuple[str, str, str]] = [
    ("0", "F.Cu", "signal"),
    ("2", "B.Cu", "signal"),
    ("9", "F.Adhes", "user"),
    ("11", "B.Adhes", "user"),
    ("13", "F.Paste", "user"),
    ("15", "B.Paste", "user"),
    ("5", "F.SilkS", "user"),
    ("7", "B.SilkS", "user"),
    ("1", "F.Mask", "user"),
    ("3", "B.Mask", "user"),
    ("17", "Dwgs.User", "user"),
    ("19", "Cmts.User", "user"),
    ("21", "Eco1.User", "user"),
    ("23", "Eco2.User", "user"),
    ("25", "Edge.Cuts", "user"),
    ("27", "Margin", "user"),
    ("31", "F.CrtYd", "user"),
    ("29", "B.CrtYd", "user"),
    ("35", "F.Fab", "user"),
    ("33", "B.Fab", "user"),
]


def _layers_node() -> list[SExpr]:
    node: list[SExpr] = [Sym("layers")]
    for number, name, kind in _LAYERS:
        node.append([Sym(number), Quoted(name), Sym(kind)])
    return node


def _edge_lines(width: float, height: float) -> list[list[SExpr]]:
    corners = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    lines: list[list[SExpr]] = []
    for index, (sx, sy) in enumerate(corners):
        ex, ey = corners[(index + 1) % 4]
        lines.append(
            [
                Sym("gr_line"),
                [Sym("start"), fmt(sx), fmt(sy)],
                [Sym("end"), fmt(ex), fmt(ey)],
                [Sym("stroke"), [Sym("width"), "0.1"], [Sym("type"), Sym("solid")]],
                [Sym("layer"), Quoted("Edge.Cuts")],
                [Sym("uuid"), Quoted(det_uuid("edge", str(index)))],
            ]
        )
    return lines


def _keepout_zone(keepout: KeepoutRect, index: int) -> list[SExpr]:
    pts: list[SExpr] = [Sym("pts")]
    for x, y in (
        (keepout.x1_mm, keepout.y1_mm),
        (keepout.x2_mm, keepout.y1_mm),
        (keepout.x2_mm, keepout.y2_mm),
        (keepout.x1_mm, keepout.y2_mm),
    ):
        pts.append([Sym("xy"), fmt(x), fmt(y)])
    return [
        Sym("zone"),
        [Sym("net"), "0"],
        [Sym("net_name"), Quoted("")],
        [Sym("layers"), Quoted("F.Cu"), Quoted("B.Cu")],
        [Sym("uuid"), Quoted(det_uuid("keepout", str(index)))],
        [Sym("name"), Quoted(keepout.name)],
        [Sym("hatch"), Sym("edge"), "0.5"],
        [
            Sym("keepout"),
            [Sym("tracks"), Sym("not_allowed")],
            [Sym("vias"), Sym("not_allowed")],
            [Sym("pads"), Sym("not_allowed")],
            [Sym("copperpour"), Sym("not_allowed")],
            [Sym("footprints"), Sym("allowed")],
        ],
        [
            Sym("polygon"),
            pts,
        ],
    ]


def _to_fab_layer(item: list[SExpr]) -> list[SExpr]:
    """Move a reference text item onto F.Fab so dense placements keep a clean silk."""
    fixed: list[SExpr] = []
    for child in item:
        if isinstance(child, list) and child and child[0] == "layer":
            fixed.append([Sym("layer"), Quoted("F.Fab")])
        else:
            fixed.append(child)
    return fixed


def _rotate_pad(pad: list[SExpr], rotation_deg: float) -> list[SExpr]:
    """Board-format pad angles are absolute, so the footprint rotation must be
    folded into each pad's ``(at ...)`` angle when embedding a library pad."""
    if rotation_deg % 360.0 == 0.0:
        return pad
    result: list[SExpr] = []
    for child in pad:
        if isinstance(child, list) and child and child[0] == "at":
            at = list(child)
            angle = float(str(at[3])) if len(at) >= 4 else 0.0
            total = (angle + rotation_deg) % 360.0
            at = [*at[:3], fmt(total)]
            result.append(at)
        else:
            result.append(child)
    return result


def _inject_footprint(
    raw: list[SExpr],
    library_ref: str,
    refdes: str,
    placement: Placement,
    pad_nets: dict[str, tuple[int, str]],
) -> list[SExpr]:
    node: list[SExpr] = [Sym("footprint"), Quoted(library_ref)]
    body: list[SExpr] = []
    for item in raw[2:]:
        if not isinstance(item, list) or not item:
            continue
        tag = item[0]
        if tag in ("at", "layer", "version", "generator", "generator_version"):
            continue
        body.append(item)
    node.append([Sym("layer"), Quoted("F.Cu")])
    node.append([Sym("uuid"), Quoted(det_uuid("footprint", refdes))])
    node.append(
        [Sym("at"), fmt(placement.x_mm), fmt(placement.y_mm), fmt(placement.rotation_deg)]
    )
    for item in body:
        assert isinstance(item, list)
        tag = item[0]
        is_ref = (tag == "fp_text" and len(item) >= 2 and item[1] == "reference") or (
            tag == "property" and len(item) >= 3 and item[1] == "Reference"
        )
        if is_ref:
            fixed = _to_fab_layer(list(item))
            fixed[2] = Quoted(refdes)
            node.append(requote(fixed))
        elif tag == "pad":
            pad = _rotate_pad(list(item), placement.rotation_deg)
            number = pad[1]
            assert isinstance(number, str)
            rebuilt = requote(pad)
            assert isinstance(rebuilt, list)
            rebuilt[1] = Quoted(number)
            mapping = pad_nets.get(number)
            if mapping is not None:
                net_number, net_name = mapping
                rebuilt.append([Sym("net"), str(net_number), Quoted(net_name)])
            node.append(rebuilt)
        else:
            node.append(requote(item))
    return node


def _antenna_keepout_depth(
    lane: ElectricalLane,
    footprints: dict[str, FootprintShape],
) -> float:
    """Keepout extends from the top board edge down to just above the RF
    module's topmost copper pad row, capped at the configured maximum depth."""
    for comp in lane.components:
        if not comp.library.footprint.startswith("Espressif:"):
            continue
        footprint = footprints[comp.refdes]
        top_pad_edge = min(
            pad.y_mm - max(pad.size_x_mm, pad.size_y_mm) / 2.0 for pad in footprint.pads
        )
        depth = ANTENNA_MODULE_Y_MM + top_pad_edge - _ANTENNA_KEEPOUT_PAD_CLEARANCE_MM
        return max(0.0, min(_ANTENNA_KEEPOUT_DEPTH_MM, depth))
    return _ANTENNA_KEEPOUT_DEPTH_MM


def generate_board(
    lane: ElectricalLane,
    footprint_library: FootprintLibrary,
    fixture_dir: Path,
    profile: FabProfile,
) -> BoardProjection:
    board = lane.board
    footprints: dict[str, FootprintShape] = {}
    raw_footprints: dict[str, list[SExpr]] = {}
    overlay_records: list[dict[str, str]] = []
    for comp in lane.components:
        path = Path(comp.library.footprint_file)
        if not path.is_absolute():
            path = fixture_dir / path
        if comp.overlay_file is None:
            footprints[comp.refdes] = footprint_library.load(
                comp.library.footprint, path, comp.library.footprint_sha256
            )
            raw_footprints[comp.refdes] = footprint_library.raw(path)
        else:
            from acd_adapter_kicad.library import verify_pinned_file

            verify_pinned_file(path, comp.library.footprint_sha256)
            raw, hashes = apply_overlay(
                footprint_library.raw(path),
                path,
                fixture_dir / comp.overlay_file,
                comp.overlay_sha256 or "",
                profile,
            )
            applied = footprint_library.shape_from_raw(comp.library.footprint, raw)
            footprints[comp.refdes] = applied
            raw_footprints[comp.refdes] = raw
            overlay_records.append(
                {
                    "refdes": comp.refdes,
                    "overlay_file": comp.overlay_file,
                    "overlay_sha256": comp.overlay_sha256 or "",
                    **hashes,
                }
            )

    keepouts: tuple[KeepoutRect, ...] = ()
    if board.antenna_keepout:
        center_x = board.width_mm / 2.0
        depth = _antenna_keepout_depth(lane, footprints)
        keepouts = (
            KeepoutRect(
                name="antenna_keepout",
                x1_mm=center_x - _ANTENNA_KEEPOUT_HALF_WIDTH_MM,
                y1_mm=0.0,
                x2_mm=center_x + _ANTENNA_KEEPOUT_HALF_WIDTH_MM,
                y2_mm=depth,
            ),
        )
    keepout_rects = tuple(Rect(k.x1_mm, k.y1_mm, k.x2_mm, k.y2_mm) for k in keepouts)
    net_refdes = tuple(
        tuple(ref for ref, _pad in lane.pads_of_net(net.node_id))
        for net in sorted(lane.nets, key=lambda n: n.name)
    )
    placements = compute_placements(
        board,
        lane.components,
        footprints,
        keepout_rects,
        net_refdes,
        lane.pins,
        lane.nets,
    )
    placement_by_refdes = {p.refdes: p for p in placements}

    net_numbers: dict[str, int] = {}
    for index, net in enumerate(sorted(lane.nets, key=lambda n: n.name)):
        net_numbers[net.node_id] = index + 1
    net_names = {net.node_id: net.name for net in lane.nets}

    doc: list[SExpr] = [
        Sym("kicad_pcb"),
        [Sym("version"), PCB_VERSION],
        [Sym("generator"), Quoted("acd")],
        [Sym("generator_version"), Quoted("0.0.1")],
        [
            Sym("general"),
            [Sym("thickness"), fmt(board.thickness_mm)],
            [Sym("legacy_teardrops"), Sym("no")],
        ],
        [Sym("paper"), Quoted("A4")],
        _layers_node(),
        _setup(lane),
        [Sym("net"), "0", Quoted("")],
    ]
    for net_id, number in sorted(net_numbers.items(), key=lambda kv: kv[1]):
        doc.append([Sym("net"), str(number), Quoted(net_names[net_id])])

    for comp in sorted(lane.components, key=lambda c: c.refdes):
        pad_nets: dict[str, tuple[int, str]] = {}
        for pin in lane.pins_of_component(comp.node_id):
            if pin.net_id is not None:
                pad_nets[pin.pad] = (net_numbers[pin.net_id], net_names[pin.net_id])
        doc.append(
            _inject_footprint(
                raw_footprints[comp.refdes],
                comp.library.footprint,
                comp.refdes,
                placement_by_refdes[comp.refdes],
                pad_nets,
            )
        )

    doc.extend(_edge_lines(board.width_mm, board.height_mm))
    for index, keepout in enumerate(keepouts):
        doc.append(_keepout_zone(keepout, index))

    model = BoardModel(
        width_mm=board.width_mm,
        height_mm=board.height_mm,
        layers=board.layers,
        min_track_mm=board.min_track_mm,
        min_clearance_mm=board.min_clearance_mm,
        via_drill_mm=board.via_drill_mm,
        via_diameter_mm=board.via_diameter_mm,
        edge_clearance_mm=board.edge_copper_clearance_mm,
        placements=tuple(
            ComponentPlacement(
                refdes=p.refdes,
                footprint=footprints[p.refdes],
                x_mm=p.x_mm,
                y_mm=p.y_mm,
                rotation_deg=p.rotation_deg,
            )
            for p in placements
        ),
        nets=tuple(
            BoardNet(name=net.name, pads=lane.pads_of_net(net.node_id))
            for net in sorted(lane.nets, key=lambda n: n.name)
        ),
        keepouts=keepouts,
    )
    return BoardProjection(
        content=dumps(doc) + "\n",
        net_numbers={net_names[k]: v for k, v in net_numbers.items()},
        placements=placements,
        keepouts=keepouts,
        model=model,
        overlays=tuple(overlay_records),
    )
