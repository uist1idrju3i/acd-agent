"""Silkscreen placement search tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import pytest

from acd_core.board_model import BoardModel, ComponentPlacement, FootprintShape, PadShape
from acd_core.electrical import GraphExtractionError
from acd_core.silkscreen import SilkscreenLane, SilkTextView
from silkscreen_search import resolve_silkscreen_placements


def _search_board(rotation_deg: float = 0.0) -> BoardModel:
    return BoardModel(
        20.0,
        20.0,
        2,
        0.15,
        0.15,
        0.3,
        0.6,
        0.0,
        (
            ComponentPlacement(
                "J1",
                FootprintShape(
                    "Test:J1",
                    (
                        PadShape(
                            "1",
                            0.0,
                            0.0,
                            0.0,
                            "rect",
                            1.0,
                            1.0,
                            False,
                            None,
                            True,
                            False,
                        ),
                    ),
                    courtyard_bbox_mm=(-1.0, -1.0, 1.0, 1.0),
                    body_bbox_mm=(-2.0, -2.0, 2.0, 2.0),
                ),
                10.0,
                10.0,
                rotation_deg,
            ),
        ),
        (),
    )


def _search_text(
    *,
    role: str = "connector_identifier",
    order: str = "top,bottom",
    step: float = 0.25,
    limit: float = 2.0,
) -> SilkTextView:
    return SilkTextView(
        "silk",
        role,
        "USB",
        1.0,
        1.0,
        "F.SilkS",
        1.0,
        0.15,
        0.0,
        "footprint_perimeter",
        order,
        "J1",
        step,
        limit,
    )


def test_silkscreen_resolves_connector_identifier_and_records_rejections() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(),), ())
    resolved = resolve_silkscreen_placements(lane, _search_board())
    text = resolved.texts[0]
    evidence = resolved.placement_evidence[0]
    assert text.x_mm != 1.0 or text.y_mm != 1.0
    assert evidence["role"] == "connector_identifier"
    assert evidence["accepted_position_mm"] == [text.x_mm, text.y_mm]
    assert evidence["rejected_candidates"]


@pytest.mark.parametrize(
    ("order", "step", "limit", "message"),
    (
        ("diagonal", 0.25, 1.0, "invalid placement search order"),
        ("top", 0.0, 1.0, "invalid placement search range"),
        ("top", 0.25, 0.1, "invalid placement search range"),
    ),
)
def test_silkscreen_search_declaration_is_validated(
    order: str, step: float, limit: float, message: str
) -> None:
    lane = SilkscreenLane(
        "board.gd1",
        (_search_text(order=order, step=step, limit=limit),),
        (),
    )
    with pytest.raises(GraphExtractionError, match=message):
        resolve_silkscreen_placements(lane, _search_board())


def test_silkscreen_backside_position_is_not_search_resolved() -> None:
    text = _search_text(role="board_type", order="top", step=0.25, limit=1.0)
    text = SilkTextView(
        text.node_id,
        text.role,
        "DEV BOARD",
        15.0,
        2.0,
        "B.SilkS",
        text.height_mm,
        text.stroke_width_mm,
        text.rotation_deg,
        text.placement_basis,
        text.placement_search_order,
        "board.gd1",
        text.placement_offset_step_mm,
        text.placement_search_limit_mm,
    )
    resolved = resolve_silkscreen_placements(
        SilkscreenLane("board.gd1", (text,), ()), _search_board(rotation_deg=90.0)
    )
    assert (resolved.texts[0].x_mm, resolved.texts[0].y_mm) == (15.0, 2.0)
    assert resolved.placement_evidence[0]["resolution"] == (
        "graph_declared_backside_position"
    )
