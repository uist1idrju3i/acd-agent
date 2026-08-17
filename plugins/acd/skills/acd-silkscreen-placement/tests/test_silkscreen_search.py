"""Silkscreen placement search tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from acd_core.board_model import BoardModel, ComponentPlacement, FootprintShape, PadShape
from acd_core.electrical import GraphExtractionError
from acd_core.silkscreen import SilkscreenLane, SilkTextView
from silkscreen_search import resolve_from_context, resolve_silkscreen_placements


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


def _context(*, outline: list[float] | None = None) -> dict[str, object]:
    return {
        "board_outline_bbox_mm": outline or [0.0, 0.0, 20.0, 20.0],
        "requirements": {
            "min_silk_width_mm": 0.1,
            "min_silk_height_mm": 0.5,
            "silk_text_advance_ratio": 0.95,
            "silk_text_attribution_margin_stroke_widths": 1.0,
            "silk_text_descender_chars": "gjpqy",
            "silk_text_descender_height_ratio": 1.25,
        },
        "pad_bboxes_mm": [],
        "mask_objects": [],
        "body_bboxes_mm": [{"refdes": "J1", "bbox_mm": [9.0, 9.0, 11.0, 11.0]}],
        "courtyard_bboxes_mm": [],
        "existing_silk_objects": [],
        "fixed_silk_objects": [],
        "silk_objects": [],
        "declarations": [
            {
                "node_id": "silk",
                "measured_text_length_mm": 2.0,
                "measured_height_mm": 0.5,
            }
        ],
    }


def test_context_search_returns_candidates_without_gate_threshold_copies() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(),), ())
    result = resolve_from_context(lane, _context())
    assert result[0]["resolution"] == "context_candidate"
    assert result[0]["accepted_position_mm"]


def test_context_search_fails_closed_for_missing_context_geometry() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(),), ())
    with pytest.raises(GraphExtractionError, match="capability requirements are missing"):
        resolve_from_context(lane, {"board_outline_bbox_mm": [0.0, 0.0, 20.0, 20.0]})


def test_context_search_reports_no_candidate_fail_closed() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(limit=0.25),), ())
    result = resolve_from_context(lane, _context(outline=[0.0, 0.0, 0.1, 0.1]))
    assert result[0]["resolution"] == "no_candidate_fail_closed"
    assert result[0]["candidates"] == []


def test_context_search_excludes_previously_placed_declarations() -> None:
    lane = SilkscreenLane(
        "board.gd1",
        (
            SilkTextView(
                "first",
                "first",
                "A",
                10.0,
                10.0,
                "F.SilkS",
                1.0,
                0.15,
                0.0,
                "test",
                "top",
                "J1",
                0.25,
                1.0,
            ),
            SilkTextView(
                "second",
                "second",
                "B",
                10.0,
                10.0,
                "F.SilkS",
                1.0,
                0.15,
                0.0,
                "test",
                "top",
                "J1",
                0.25,
                1.0,
            ),
        ),
        (),
    )
    context = _context()
    context["declarations"] = [
        {
            "node_id": "first",
            "measured_text_length_mm": 2.0,
            "measured_height_mm": 0.5,
        },
        {
            "node_id": "second",
            "measured_text_length_mm": 2.0,
            "measured_height_mm": 0.5,
        },
    ]
    result = resolve_from_context(lane, context)
    first = next(item for item in result if item["node_id"] == "first")
    second = next(item for item in result if item["node_id"] == "second")
    assert first["resolution"] == "context_candidate"
    assert second["resolution"] == "context_candidate"
    assert second["accepted_position_mm"] != first["accepted_position_mm"]
    rejected = cast(list[dict[str, Any]], second["rejected_candidates"])
    assert any(
        item["reason"] == "placed_declaration"
        for item in rejected
    )


def test_context_search_keeps_fixed_graphic_as_layer_obstacle() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(),), ())
    context = _context()
    context["fixed_silk_objects"] = [
        {"kind": "Line", "layer": "F.SilkS", "bbox_mm": [0.0, 0.0, 5.0, 5.0]}
    ]
    result = resolve_from_context(lane, context)
    assert result[0]["resolution"] == "context_candidate"
    rejected = cast(list[dict[str, Any]], result[0]["rejected_candidates"])
    assert any(
        item["reason"] == "fixed_silk_objects"
        for item in rejected
    )
