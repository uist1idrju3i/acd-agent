"""Deterministic KiCad board projection.

Embeds pinned footprint files verbatim (with position, reference, and pad net
assignments injected), draws the board outline and antenna keepout, and leaves
routing to the external router adapter. Net numbering is deterministic: nets
sorted by name, numbered from 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import cast

from acd.adapters.kicad.emit import det_uuid, fmt, requote
from acd.adapters.kicad.library import FootprintLibrary
from acd.adapters.kicad.overlay import apply_overlay
from acd.adapters.kicad.placement import Placement, PlacementError, Rect
from acd.core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    CopperZone,
    FootprintShape,
    KeepoutRect,
    NetClass,
)
from acd.core.electrical import BoardView, ElectricalLane
from acd.core.fab import FabProfile
from acd.core.library_assets import resolve_fixture_library_path
from acd.core.routing_width import derive_net_widths, group_netclasses
from acd.core.sexpr import Quoted, SExpr, Sym, dumps
from acd.core.silkscreen import (
    SilkGraphicPartView,
    SilkGraphicView,
    SilkscreenLane,
    SilkTextView,
)

PCB_VERSION = "20241229"

EDGE_CUTS_STROKE_WIDTH_MM = 0.1

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
    stitch_via_pitch_mm: float | None = None
    overlays: tuple[dict[str, str], ...] = ()
    silkscreen: SilkscreenLane | None = None


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
                [
                    Sym("stroke"),
                    [Sym("width"), fmt(EDGE_CUTS_STROKE_WIDTH_MM)],
                    [Sym("type"), Sym("solid")],
                ],
                [Sym("layer"), Quoted("Edge.Cuts")],
                [Sym("uuid"), Quoted(det_uuid("edge", str(index)))],
            ]
        )
    return lines


def _silk_text(item: SilkTextView) -> list[SExpr]:
    if item.x_mm is None or item.y_mm is None:
        raise ValueError(
            f"silkscreen text {item.node_id!r} has no declared position (fail-closed)"
        )
    effects: list[SExpr] = [
        Sym("effects"),
        [
            Sym("font"),
            [Sym("size"), fmt(item.height_mm), fmt(item.height_mm)],
            [Sym("thickness"), fmt(item.stroke_width_mm)],
        ],
    ]
    if item.layer == "B.SilkS":
        effects.append([Sym("justify"), Sym("mirror")])
    return [
        Sym("gr_text"),
        Quoted(item.text),
        [Sym("at"), fmt(item.x_mm), fmt(item.y_mm), fmt(item.rotation_deg)],
        [Sym("layer"), Quoted(item.layer)],
        effects,
        [Sym("uuid"), Quoted(det_uuid("silk-text", item.node_id))],
    ]


def _graphic_parts(item: SilkGraphicView) -> tuple[SilkGraphicPartView, ...]:
    if item.parts:
        return item.parts
    contours = item.contours or (item.polygon_points,)
    return (SilkGraphicPartView(contours, item.stroke_width_mm, item.fill, item.fill_rule),)


def _filled_contours(part: SilkGraphicPartView) -> tuple[tuple[tuple[float, float], ...], ...]:
    outer = next(iter(part.contours), None)
    if outer is None:
        raise ValueError("silkscreen graphic part has no contours")
    if part.fill_rule != "evenodd" or len(part.contours) < 2:
        return (outer,)
    outer_bbox = (
        min(point[0] for point in outer),
        min(point[1] for point in outer),
        max(point[0] for point in outer),
        max(point[1] for point in outer),
    )
    x_values = sorted({point[0] for contour in part.contours for point in contour})
    y_values = sorted({point[1] for contour in part.contours for point in contour})
    hole_bboxes = [
        (
            min(point[0] for point in contour),
            min(point[1] for point in contour),
            max(point[0] for point in contour),
            max(point[1] for point in contour),
        )
        for contour in part.contours[1:]
    ]
    filled: list[tuple[tuple[float, float], ...]] = []
    for x1, x2 in pairwise(x_values):
        for y1, y2 in pairwise(y_values):
            midpoint = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            if not (
                outer_bbox[0] <= midpoint[0] <= outer_bbox[2]
                and outer_bbox[1] <= midpoint[1] <= outer_bbox[3]
            ):
                continue
            if any(
                bbox[0] <= midpoint[0] <= bbox[2]
                and bbox[1] <= midpoint[1] <= bbox[3]
                for bbox in hole_bboxes
            ):
                continue
            filled.append(((x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)))
    return tuple(filled)


def _silk_graphic(item: SilkGraphicView) -> list[SExpr]:
    result: list[SExpr] = []
    for index, part in enumerate(_graphic_parts(item)):
        if not part.contours:
            raise ValueError(f"silkscreen graphic {item.node_id!r} has no contours")
        if part.fill != "none" and any(
            len(contour) < 3 or contour[0] != contour[-1]
            for contour in part.contours
        ):
            raise ValueError(
                f"filled silkscreen graphic {item.node_id!r} has an open contour"
            )
        contours = (
            _filled_contours(part)
            if part.fill != "none"
            else part.contours
        )
        for contour_index, contour in enumerate(contours):
            stroke: SExpr | None = (
                None
                if part.fill != "none"
                else cast(
                    SExpr,
                    [
                        Sym("stroke"),
                        [Sym("width"), fmt(part.stroke_width_mm)],
                        [Sym("type"), Sym("solid")],
                    ],
                )
            )
            uuid = f"{item.node_id}-{index}-{contour_index}"
            if len(contour) >= 3 and contour[0] == contour[-1]:
                points: list[SExpr] = [Sym("pts")]
                for x_mm, y_mm in contour:
                    points.append([Sym("xy"), fmt(x_mm), fmt(y_mm)])
                polygon: list[SExpr] = [
                    Sym("gr_poly"),
                    points,
                    [Sym("fill"), Sym("solid" if part.fill != "none" else "none")],
                    [Sym("layer"), Quoted(item.layer)],
                    [Sym("uuid"), Quoted(det_uuid("silk-graphic", uuid))],
                ]
                if stroke is not None:
                    polygon.insert(2, stroke)
                result.append(cast(SExpr, polygon))
            else:
                for segment_index, ((x1, y1), (x2, y2)) in enumerate(pairwise(contour)):
                    result.append(
                        cast(
                            SExpr,
                            [
                            Sym("gr_line"),
                            [Sym("start"), fmt(x1), fmt(y1)],
                            [Sym("end"), fmt(x2), fmt(y2)],
                            cast(SExpr, stroke),
                            [Sym("layer"), Quoted(item.layer)],
                            [
                                Sym("uuid"),
                                Quoted(det_uuid("silk-graphic", f"{uuid}-{segment_index}")),
                            ],
                            ],
                        )
                    )
    return result


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


def _copper_zone(
    zone: CopperZone,
    board: BoardView,
    net_number: int,
    index: int,
) -> list[SExpr]:
    inset = zone.inset_mm
    pts: list[SExpr] = [Sym("pts")]
    for x, y in (
        (inset, inset),
        (board.width_mm - inset, inset),
        (board.width_mm - inset, board.height_mm - inset),
        (inset, board.height_mm - inset),
    ):
        pts.append([Sym("xy"), fmt(x), fmt(y)])
    return [
        Sym("zone"),
        [Sym("net"), str(net_number)],
        [Sym("net_name"), Quoted(zone.net)],
        [Sym("layers"), *[Quoted(layer) for layer in zone.layers]],
        [Sym("uuid"), Quoted(det_uuid("copper-zone", str(index), zone.net))],
        [Sym("name"), Quoted(f"{zone.net}_plane")],
        [Sym("hatch"), Sym("edge"), "0.5"],
        [Sym("connect_pads"), [Sym("clearance"), fmt(board.min_clearance_mm)]],
        [Sym("min_thickness"), fmt(board.min_track_mm)],
        [
            Sym("fill"),
            [Sym("thermal_gap"), fmt(board.min_clearance_mm)],
            [Sym("thermal_bridge_width"), fmt(board.min_track_mm)],
        ],
        [Sym("polygon"), pts],
    ]


def stitch_via_pitch(board: BoardView) -> float | None:
    frequency_hz = board.stitch_via_max_frequency_hz
    dielectric_constant = board.stitch_via_dielectric_constant
    wavelength_fraction = board.stitch_via_wavelength_fraction
    basis_source = board.stitch_via_basis_source
    if (
        frequency_hz is None
        or dielectric_constant is None
        or wavelength_fraction is None
        or basis_source is None
    ):
        if any(
            value is not None
            for value in (
                frequency_hz,
                dielectric_constant,
                wavelength_fraction,
                basis_source,
            )
        ):
            raise ValueError("incomplete stitch-via basis declaration (fail-closed)")
        return None
    if (
        frequency_hz <= 0
        or dielectric_constant <= 0
        or not 0 < wavelength_fraction <= 1
    ):
        raise ValueError("invalid stitch-via basis declaration (fail-closed)")
    speed_of_light_mm_s = 299_792_458_000.0
    return (
        speed_of_light_mm_s
        / (
            frequency_hz
            * dielectric_constant**0.5
        )
        * wavelength_fraction
    )


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


def _validated_placements(
    lane: ElectricalLane, placements: tuple[Placement, ...]
) -> dict[str, Placement]:
    by_refdes: dict[str, Placement] = {}
    for placement in placements:
        if placement.refdes in by_refdes:
            raise PlacementError(f"duplicate placement for {placement.refdes} (fail-closed)")
        if placement.rotation_deg % 90.0 != 0.0:
            raise PlacementError(
                f"{placement.refdes}: unsupported rotation {placement.rotation_deg} (fail-closed)"
            )
        by_refdes[placement.refdes] = placement
    declared = {comp.refdes for comp in lane.components}
    missing = sorted(declared - by_refdes.keys())
    if missing:
        raise PlacementError(f"placement missing for {', '.join(missing)} (fail-closed)")
    unknown = sorted(by_refdes.keys() - declared)
    if unknown:
        raise PlacementError(f"placement for undeclared component {', '.join(unknown)}")
    return by_refdes


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
        depth = top_pad_edge - _ANTENNA_KEEPOUT_PAD_CLEARANCE_MM
        return max(0.0, min(_ANTENNA_KEEPOUT_DEPTH_MM, depth))
    return _ANTENNA_KEEPOUT_DEPTH_MM


@dataclass(frozen=True)
class BoardFootprints:
    """Pinned footprint geometry of every component, plus the raw KiCad forms."""

    shapes: dict[str, FootprintShape]
    raw: dict[str, list[SExpr]]
    overlays: tuple[dict[str, str], ...]


def load_board_footprints(
    lane: ElectricalLane,
    footprint_library: FootprintLibrary,
    fixture_dir: Path,
    profile: FabProfile,
) -> BoardFootprints:
    """Load pinned footprints and apply declared overlays.

    Exposed separately from the projection so a placement search can read the
    same geometry the projection will use.
    """
    footprints: dict[str, FootprintShape] = {}
    raw_footprints: dict[str, list[SExpr]] = {}
    overlay_records: list[dict[str, str]] = []
    for comp in lane.components:
        path = resolve_fixture_library_path(comp.library.footprint_file, fixture_dir)
        if comp.overlay_file is None:
            footprints[comp.refdes] = footprint_library.load(
                comp.library.footprint, path, comp.library.footprint_sha256
            )
            raw_footprints[comp.refdes] = footprint_library.raw(path)
        else:
            from acd.adapters.kicad.library import verify_pinned_file

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

    return BoardFootprints(
        shapes=footprints, raw=raw_footprints, overlays=tuple(overlay_records)
    )


def board_keepouts(
    lane: ElectricalLane, footprints: dict[str, FootprintShape]
) -> tuple[KeepoutRect, ...]:
    """Keepout rectangles declared by the board node (antenna clearance)."""
    board = lane.board
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
    return keepouts


def keepout_rects(keepouts: tuple[KeepoutRect, ...]) -> tuple[Rect, ...]:
    return tuple(Rect(k.x1_mm, k.y1_mm, k.x2_mm, k.y2_mm) for k in keepouts)


def generate_board(
    lane: ElectricalLane,
    footprint_library: FootprintLibrary,
    fixture_dir: Path,
    profile: FabProfile,
    placements: tuple[Placement, ...],
    silkscreen: SilkscreenLane | None = None,
) -> BoardProjection:
    """Project the board from the lane and the given placements.

    Placements are design data: they are produced outside the ACD core (for
    example by the ``acd-placement-search`` skill) and judged by the ERC/DRC and
    reload gates. Unknown or missing placements stop the projection.
    """
    board = lane.board
    loaded = load_board_footprints(lane, footprint_library, fixture_dir, profile)
    footprints = loaded.shapes
    raw_footprints = loaded.raw
    overlay_records = list(loaded.overlays)
    keepouts = board_keepouts(lane, footprints)
    placements = tuple(sorted(placements, key=lambda p: p.refdes))
    placement_by_refdes = _validated_placements(lane, placements)

    net_numbers: dict[str, int] = {}
    for index, net in enumerate(sorted(lane.nets, key=lambda n: n.name)):
        net_numbers[net.node_id] = index + 1
    net_names = {net.node_id: net.name for net in lane.nets}
    stitch_pitch = stitch_via_pitch(board)
    copper_zones: tuple[CopperZone, ...] = ()
    if board.ground_plane_net is not None:
        if not board.ground_plane_layers or board.ground_plane_min_island_area_mm2 is None:
            raise ValueError("incomplete ground-plane declaration (fail-closed)")
        ground_net_id = next(
            (net_id for net_id, name in net_names.items() if name == board.ground_plane_net),
            None,
        )
        if ground_net_id is None:
            raise ValueError("ground-plane net is not declared (fail-closed)")
        copper_zones = (
            CopperZone(
                net=board.ground_plane_net,
                layers=board.ground_plane_layers,
                inset_mm=board.edge_copper_clearance_mm,
                min_island_area_mm2=board.ground_plane_min_island_area_mm2,
            ),
        )

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
    if silkscreen is not None:
        doc.extend(_silk_text(item) for item in silkscreen.texts)
        for item in silkscreen.graphics:
            doc.extend(_silk_graphic(item))
    for index, keepout in enumerate(keepouts):
        doc.append(_keepout_zone(keepout, index))
    for index, zone in enumerate(copper_zones):
        zone_net_id = next(net_id for net_id, name in net_names.items() if name == zone.net)
        doc.append(_copper_zone(zone, board, net_numbers[zone_net_id], index))

    profile_minimum = float(profile.data["capabilities"]["min_track_width"]["value"])
    width_requirements = derive_net_widths(lane, profile_minimum)
    netclasses = tuple(
        NetClass(name=name, width_mm=width, nets=nets)
        for name, nets, width in group_netclasses(width_requirements)
    )
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
        copper_zones=copper_zones,
        stitch_via_pitch_mm=stitch_pitch,
        stitch_via_net=board.ground_plane_net,
        stitch_via_refill_max_iterations=board.stitch_via_refill_max_iterations,
        netclasses=netclasses,
    )
    return BoardProjection(
        content=dumps(doc) + "\n",
        net_numbers={net_names[k]: v for k, v in net_numbers.items()},
        placements=placements,
        keepouts=keepouts,
        model=model,
        overlays=tuple(overlay_records),
        stitch_via_pitch_mm=stitch_pitch,
        silkscreen=silkscreen,
    )
