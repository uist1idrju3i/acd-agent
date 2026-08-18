"""Build the Golden Design #1 design-graph fixture.
Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""

from __future__ import annotations

from typing import cast

# ruff: noqa: E501,RUF100
from acd.schema.design_graph import GraphNode

from ..repository import repository_root
from .svg_artwork import encode_parts, place_svg


def _polygon_points(parts: tuple[dict[str, object], ...]) -> list[str]:
    contours = cast(list[object], parts[0]["contours"])
    points = cast(list[object], contours[0])
    return [
        f"{cast(list[float], point)[0]},{cast(list[float], point)[1]}"
        for point in points
    ]


def silkscreen_nodes(graph_id: str, revision: str) -> list[GraphNode]:
    board_label = f"{graph_id}-{revision}"
    common = {
        "layer": "F.SilkS",
        "height_mm": 1.0,
        "stroke_width_mm": 0.15,
        "rotation_deg": 0.0,
        "placement_search_order": (
            "top,bottom,right,left,top_right,bottom_right,bottom_left,top_left"
        ),
        "placement_offset_step_mm": 0.25,
        "placement_search_limit_mm": 8.0,
        "board_edge_margin_mm": 0.15,
        "board_edge_margin_source": (
            "fab_profile:jlcpcb-fr4-2l-1oz.min_silk_width=0.15 mm; "
            "declared edge keepout equals the profiled minimum silk stroke"
        ),
        "placement_rotation_degrees": ["0", "90", "180", "270"],
        "placement_safety_margin_mm": 0.15,
    }
    text_nodes = [
        (
            "mechanical.silk_text.reset",
            "functional_label_sw1",
            "RST",
            29.5,
            5.0,
            "SW1",
            "SW1 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.boot",
            "functional_label_sw2",
            "BOOT",
            4.55,
            5.4,
            "SW2",
            "SW2 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.led",
            "functional_label_d1",
            "D1",
            None,
            None,
            "D1",
            "D1 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.usb",
            "connector_identifier",
            "USB",
            None,
            None,
            "J1",
            "J1 center and connector keepout clearance",
        ),
        (
            "mechanical.silk_text.dev_board",
            "board_type",
            "DEV BOARD",
            25.0,
            1.0,
            "board.gd1",
            "open board area after reference and pad clearance search",
        ),
        (
            "mechanical.silk_text.board_id",
            "board_part_number",
            board_label,
            21.8,
            12.7,
            "board.gd1",
            "graph_id and revision derived part-number placement; branding and "
            "identification intentionally remain on B.SilkS after front-side "
            "functional-label clearance measurement",
        ),
    ]
    nodes = [
        GraphNode(
            id=node_id,
            kind="mechanical.silk_text",
            attrs={
                **common,
                "layer": "B.SilkS"
                if role in {"board_type", "board_part_number"}
                else common["layer"],
                "height_mm": 1.0
                if role in {"board_type", "board_part_number"}
                else common["height_mm"],
                "rotation_deg": 90.0 if role == "functional_label_sw1" else common["rotation_deg"],
                "role": role,
                "text": text,
                "placement_reference": reference,
                "placement_basis": basis,
                **(
                    {"x_mm": x_mm, "y_mm": y_mm}
                    if x_mm is not None and y_mm is not None
                    else {}
                ),
            },
            depends_on=["board.gd1"],
        )
        for node_id, role, text, x_mm, y_mm, reference, basis in text_nodes
    ]
    root = repository_root()
    logo_parts, logo_provenance = place_svg(
        root / "assets/vibebb-silkscreen.svg",
        board_width_mm=30.0,
        center_x_mm=21.0,
        center_y_mm=20.0,
        width_mm=16.0,
    )
    qr_parts, qr_provenance = place_svg(
        root / "assets/qr-repository-silkscreen.svg",
        board_width_mm=30.0,
        center_x_mm=7.0,
        center_y_mm=7.0,
        width_mm=13.5,
    )
    logo_provenance["source_path"] = "assets/vibebb-silkscreen.svg"
    qr_provenance["source_path"] = "assets/qr-repository-silkscreen.svg"
    nodes.append(
        GraphNode(
            id="mechanical.silk_graphic.vibebb",
            kind="mechanical.silk_graphic",
            attrs={
                "role": "vibebb_logo",
                "layer": "B.SilkS",
                "stroke_width_mm": 0.15,
                "polygon_points": _polygon_points(logo_parts),
                "graphic_parts": encode_parts(logo_parts),
                "source_path": logo_provenance["source_path"],
                "source_sha256": logo_provenance["source_sha256"],
                "source_viewbox_mm": logo_provenance["source_viewbox_mm"],
                "source_scale": logo_provenance["scale"],
                "placed_size_mm": logo_provenance["placed_size_mm"],
                "placement_basis": (
                    "provisional SVG-derived candidate; resolver must verify "
                    "backside pad/mask, silk, edge, and text clearance"
                ),
                "placement_search_order": common["placement_search_order"],
                "board_edge_margin_mm": 0.15,
                "board_edge_margin_source": common["board_edge_margin_source"],
            },
            depends_on=["board.gd1"],
        )
    )
    nodes.append(
        GraphNode(
            id="mechanical.silk_graphic.repository_qr",
            kind="mechanical.silk_graphic",
            attrs={
                "role": "repository_qr",
                "layer": "B.SilkS",
                "stroke_width_mm": 0.15,
                "polygon_points": _polygon_points(qr_parts),
                "graphic_parts": encode_parts(qr_parts),
                "source_path": qr_provenance["source_path"],
                "source_sha256": qr_provenance["source_sha256"],
                "source_viewbox_mm": qr_provenance["source_viewbox_mm"],
                "source_scale": qr_provenance["scale"],
                "placed_size_mm": qr_provenance["placed_size_mm"],
                "placement_basis": (
                    "provisional SVG-derived candidate; resolver must verify "
                    "backside pad/mask, silk, edge, and text clearance"
                ),
                "placement_search_order": common["placement_search_order"],
                "board_edge_margin_mm": 0.15,
                "board_edge_margin_source": common["board_edge_margin_source"],
            },
            depends_on=["board.gd1"],
        )
    )
    return nodes
