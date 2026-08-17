"""Build the Golden Design #1 design-graph fixture.
Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""
# pyright: reportUnknownVariableType=false,reportUnknownArgumentType=false,reportUnknownMemberType=false,reportUnknownParameterType=false,reportInvalidTypeForm=false,reportUnusedVariable=false,reportUnusedImport=false,reportGeneralTypeIssues=false

from __future__ import annotations

# ruff: noqa: E501,RUF100
from acd.schema.design_graph import AttrValue, GraphNode

from .components import *  # noqa: F401,F403

MECHANICAL_OUTLINE_ATTRS: dict[str, AttrValue] = {
    "width_mm": 30.0,
    "depth_mm": 25.0,
    "thickness_mm": 1.6,
    "corner_radius_mm": 1.0,
    "unit": "mm",
    "origin": "board_upper_left",
    "y_axis": "down",
    "mount_hole_count": 4,
    "mount_hole_1_x_mm": 1.5,
    "mount_hole_1_y_mm": 1.5,
    "mount_hole_1_diameter_mm": 2.2,
    "mount_hole_2_x_mm": 28.5,
    "mount_hole_2_y_mm": 1.5,
    "mount_hole_2_diameter_mm": 2.2,
    "mount_hole_3_x_mm": 1.5,
    "mount_hole_3_y_mm": 23.5,
    "mount_hole_3_diameter_mm": 2.2,
    "mount_hole_4_x_mm": 28.5,
    "mount_hole_4_y_mm": 23.5,
    "mount_hole_4_diameter_mm": 2.2,
    "position_source": "golden-design-1 mechanical declaration",
    "position_source_ref": "docs/golden-design-1.md",
}


def _body(
    component_id: str,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
    source: str,
    source_ref: str,
    body_type: str = "solid",
) -> tuple[str, dict[str, AttrValue]]:
    return (
        component_id,
        {
            "x_mm": x_mm,
            "y_mm": y_mm,
            "width_mm": width_mm,
            "depth_mm": depth_mm,
            "height_mm": height_mm,
            "body_type": body_type,
            "mounting_side": "top",
            "rotation_deg": 0.0,
            "position_source": "golden-design-1 mechanical declaration",
            "position_source_ref": "docs/golden-design-1.md",
            "dimensions_source": source,
            "dimensions_source_ref": source_ref,
            "dimensions_checked_at": "2026-08-11T00:00:00Z",
        },
    )


MECHANICAL_COMPONENT_BODIES: tuple[tuple[str, dict[str, AttrValue]], ...] = (
    _body(
        "comp.u1",
        x_mm=15.0,
        y_mm=13.0,
        width_mm=13.2,
        depth_mm=16.6,
        height_mm=2.4,
        source="Espressif ESP32-C3-MINI-1 datasheet",
        source_ref="https://www.espressif.com/sites/default/files/documentation/esp32-c3-mini-1_datasheet_en.pdf",
    ),
    _body(
        "comp.j1",
        x_mm=15.0,
        y_mm=5.0,
        width_mm=9.0,
        depth_mm=7.0,
        height_mm=3.2,
        source="KiCad official footprint library, package version 10.0.5",
        source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/Connector_USB.pretty",
    ),
    _body(
        "comp.u2",
        x_mm=10.0,
        y_mm=18.0,
        width_mm=6.5,
        depth_mm=3.5,
        height_mm=1.8,
        source="Advanced Monolithic AMS1117 datasheet",
        source_ref="https://www.advanced-monolithic.com/pdf/ds1117.pdf",
    ),
    _body(
        "comp.u3",
        x_mm=24.0,
        y_mm=8.0,
        width_mm=1.5,
        depth_mm=1.5,
        height_mm=0.5,
        source="Sensirion SHT4x datasheet",
        source_ref="https://sensirion.com/resource/datasheet/sht4x",
    ),
    _body(
        "comp.d1",
        x_mm=5.0,
        y_mm=20.0,
        width_mm=1.6,
        depth_mm=0.8,
        height_mm=0.55,
        source="LCSC KT-0603R LED datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C2286.pdf",
    ),
    _body(
        "comp.sw1",
        x_mm=7.0,
        y_mm=5.0,
        width_mm=6.0,
        depth_mm=6.0,
        height_mm=4.3,
        source="TS-1088 tactile switch datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C720477.pdf",
    ),
    _body(
        "comp.sw2",
        x_mm=23.0,
        y_mm=5.0,
        width_mm=6.0,
        depth_mm=6.0,
        height_mm=4.3,
        source="TS-1088 tactile switch datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C720477.pdf",
    ),
    *(
        _body(
            f"comp.{prefix}{index}",
            x_mm=8.0 + (index % 2) * 4.0,
            y_mm=8.0 + (index // 2) * 3.0,
            width_mm=1.6,
            depth_mm=0.8,
            height_mm=0.8,
            source="LCSC 0603 chip component datasheet",
            source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C1591.pdf",
        )
        for prefix, count in (("r", 6), ("c", 6))
        for index in range(1, count + 1)
    ),
    *(
        _body(
            f"comp.tp{index}",
            x_mm=2.0 + (index % 4) * 8.0,
            y_mm=23.0,
            width_mm=1.5,
            depth_mm=1.5,
            height_mm=0.0,
            body_type="none",
            source="KiCad TestPoint_Pad_D1.5mm has no declared component body",
            source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/TestPoint.pretty",
        )
        for index in range(1, 8)
    ),
    *(
        _body(
            f"comp.h{index}",
            x_mm=1.5 if index % 2 else 28.5,
            y_mm=1.5 if index <= 2 else 23.5,
            width_mm=2.2,
            depth_mm=2.2,
            height_mm=0.0,
            body_type="none",
            source="KiCad MountingHole_2.2mm_M2 has no component body",
            source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/MountingHole.pretty",
        )
        for index in range(1, 5)
    ),
)


MECHANICAL_ENCLOSURE_ATTRS: dict[str, AttrValue] = {
    "wall_thickness_mm": 2.0,
    "min_wall_thickness_mm": 1.2,
    "internal_clearance_mm": 1.0,
    "lid_fit_gap_mm": 0.2,
    "standoff_height_mm": 4.0,
    "standoff_radius_mm": 2.0,
    "material": "PETG",
    "unit": "mm",
    "tolerance_mm": 0.05,
    "interference_tolerance_mm3": 0.01,
    "tolerance_source": "golden-design-1 mechanical gate declaration",
    "tolerance_source_ref": "docs/golden-design-1.md",
}


def mechanical_nodes() -> list[GraphNode]:
    nodes = [
        GraphNode(
            id="mechanical.outline.gd1",
            kind="mechanical.outline",
            attrs=dict(MECHANICAL_OUTLINE_ATTRS),
            depends_on=["board.gd1"],
        )
    ]
    for index, (component_id, attrs) in enumerate(MECHANICAL_COMPONENT_BODIES, start=1):
        nodes.append(
            GraphNode(
                id=f"mechanical.component_body.{index}",
                kind="mechanical.component_body",
                attrs=dict(attrs),
                depends_on=[component_id],
            )
        )
    nodes.append(
        GraphNode(
            id="mechanical.connector_opening.j1",
            kind="mechanical.connector_opening",
            attrs={
                "connector": "comp.j1",
                "face": "front",
                "center_x_mm": 15.0,
                "center_y_mm": 5.0,
                "width_mm": 8.0,
                "height_mm": 5.0,
                "margin_mm": 0.5,
                "dimensions_source": ("KiCad official footprint library, package version 10.0.5"),
                "dimensions_source_ref": (
                    "https://github.com/KiCad/kicad-footprints/tree/10.0.5/Connector_USB.pretty"
                ),
                "dimensions_checked_at": "2026-08-11T00:00:00Z",
            },
            depends_on=["comp.j1"],
        )
    )
    nodes.append(
        GraphNode(
            id="mechanical.enclosure.gd1",
            kind="mechanical.enclosure",
            attrs=dict(MECHANICAL_ENCLOSURE_ATTRS),
            depends_on=[node.id for node in nodes[1:]],
        )
    )
    nodes.extend(
        [
            GraphNode(
                id="mechanical.board_edge_overhang.u1",
                kind="mechanical.board_edge_overhang",
                attrs={
                    "component_refdes": "U1",
                    "overhang_mm": 5.4,
                    "requirement_id": "req.gd1-req-015",
                    "edge": "top",
                },
                depends_on=["comp.u1", "req.gd1-req-015"],
            ),
        ]
    )
    return nodes
