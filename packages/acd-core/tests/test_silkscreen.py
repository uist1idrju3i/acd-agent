"""Silkscreen graph extraction and fail-closed geometry tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_core.board_model import BoardModel, ComponentPlacement, FootprintShape, PadShape
from acd_core.electrical import GraphExtractionError
from acd_core.silkscreen import (
    SilkscreenLane,
    SilkTextView,
    extract_silkscreen_lane,
    resolve_silkscreen_placements,
)
from acd_schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_silkscreen_lane_extracts_declared_text_and_vector_logo() -> None:
    lane = extract_silkscreen_lane(_graph())
    assert {item.text for item in lane.texts} >= {"RESET", "BOOT", "DEV BOARD"}
    assert len(lane.graphics) == 1
    assert lane.graphics[0].role == "vibebb_logo"
    assert all(item.placement_reference for item in lane.texts)


def test_silkscreen_declaration_missing_fails_closed() -> None:
    graph = _graph()
    nodes = tuple(node for node in graph.nodes if not node.kind.startswith("mechanical.silk"))
    with pytest.raises(GraphExtractionError, match="silkscreen declarations"):
        extract_silkscreen_lane(graph.model_copy(update={"nodes": nodes}))


def test_silkscreen_text_requires_board_dependency() -> None:
    graph = _graph()
    nodes = tuple(
        node.model_copy(update={"depends_on": []})
        if node.kind == "mechanical.silk_text"
        else node
        for node in graph.nodes
    )
    with pytest.raises(GraphExtractionError, match="must depend on board"):
        extract_silkscreen_lane(graph.model_copy(update={"nodes": nodes}))


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
