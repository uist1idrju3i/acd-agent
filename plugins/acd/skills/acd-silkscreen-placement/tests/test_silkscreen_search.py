"""Silkscreen placement search tests (skill asset, separate from the ACD core)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import pytest

import silkscreen_search
from acd.core.board_model import BoardModel, ComponentPlacement, FootprintShape, PadShape
from acd.core.electrical import GraphExtractionError
from acd.core.silkscreen import SilkscreenLane, SilkTextView
from silkscreen_search import _text_size, resolve_from_context, resolve_silkscreen_placements


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


def test_non_search_text_without_coordinates_fails_closed() -> None:
    text = replace(_search_text(role="non_search_label"), x_mm=None, y_mm=None)
    with pytest.raises(GraphExtractionError, match="no declared position"):
        resolve_silkscreen_placements(
            SilkscreenLane("board.gd1", (text,), ()),
            _search_board(),
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


def test_silkscreen_backside_text_is_search_resolved() -> None:
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
    resolved_text = resolved.texts[0]
    evidence = resolved.placement_evidence[0]
    assert resolved_text.layer == "B.SilkS"
    assert (resolved_text.x_mm, resolved_text.y_mm) != (15.0, 2.0)
    assert evidence["accepted_position_mm"] == [
        resolved_text.x_mm,
        resolved_text.y_mm,
    ]


def _context(*, outline: list[float] | None = None) -> dict[str, object]:
    return {
        "board_outline_bbox_mm": outline or [0.0, 0.0, 20.0, 20.0],
        "requirements": {
            "min_silk_width_mm": 0.1,
            "min_silk_height_mm": 0.5,
            "silk_text_advance_ratio": 0.95,
            "silk_text_attribution_margin_stroke_widths": 1.0,
            "silk_text_descender_chars": "gjpqy",
            "silk_text_descender_height_ratio": 1.45,
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


def test_context_search_workers_preserve_subprocess_output_bytes(tmp_path: Path) -> None:
    first = _search_text()
    second = replace(first, node_id="silk-second")
    context = _context()
    context["declarations"] = [
        {
            "node_id": first.node_id,
            "measured_text_length_mm": 2.0,
            "measured_height_mm": 0.5,
        },
        {
            "node_id": second.node_id,
            "measured_text_length_mm": 2.0,
            "measured_height_mm": 0.5,
        },
    ]
    payload = {
        "lane": {
            "board_node_id": "board.gd1",
            "texts": [asdict(first), asdict(second)],
            "graphics": [],
        },
        "context": context,
    }
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "silkscreen_search.py"
    )
    input_path = tmp_path / "silkscreen-input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    outputs: list[bytes] = []
    for workers in (1, 4):
        output_path = tmp_path / f"silkscreen-output-{workers}.json"
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(script),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--workers",
                str(workers),
            ],
            cwd=Path(__file__).resolve().parents[5],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(output_path.read_bytes())
    assert outputs[0] == outputs[1]


def test_context_search_all_reject_result_is_worker_invariant() -> None:
    lane = SilkscreenLane("board.gd1", (_search_text(limit=0.5),), ())
    context = _context()
    context["existing_silk_objects"] = [
        {"layer": "F.SilkS", "bbox_mm": [0.0, 0.0, 20.0, 20.0]}
    ]
    sequential = resolve_from_context(lane, context, workers=1)
    parallel = resolve_from_context(lane, context, workers=4)
    assert sequential == parallel
    assert sequential[0]["resolution"] == "no_candidate_fail_closed"


def test_context_search_worker_exception_is_not_partial_success() -> None:
    context = _context()
    context["pad_bboxes_mm"] = [{"bbox_mm": [0.0, 0.0, 1.0, 1.0]}]
    with pytest.raises(GraphExtractionError, match="pad layers are missing"):
        resolve_from_context(
            SilkscreenLane("board.gd1", (_search_text(),), ()),
            context,
            workers=4,
        )


def test_context_search_workers_one_does_not_create_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_created(*args: object, **kwargs: object) -> None:
        raise AssertionError("worker=1 must not create a process pool")

    monkeypatch.setattr(silkscreen_search, "ProcessPoolExecutor", fail_if_created)
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(),), ()),
        _context(),
        workers=1,
    )
    assert result[0]["resolution"] == "context_candidate"


@pytest.mark.parametrize(
    ("workers", "message"),
    (("0", "workers must be at least 1"), ("invalid", "workers must be an integer")),
)
def test_context_search_cli_rejects_invalid_workers(
    tmp_path: Path,
    workers: str,
    message: str,
) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "silkscreen_search.py"
    )
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(script),
            "--input",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "output.json"),
            "--workers",
            workers,
        ],
        cwd=Path(__file__).resolve().parents[5],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert message in completed.stderr


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


def test_context_search_rejects_mask_opening_overlap() -> None:
    context = _context()
    context["mask_objects"] = [
        {"layer": "F.Mask", "bbox_mm": [8.0, 7.0, 12.0, 9.0]}
    ]
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(order="top", limit=0.25),), ()),
        context,
    )
    assert any(
        item["reason"] == "mask_opening_bboxes_mm"
        for item in cast(list[dict[str, object]], result[0]["rejected_candidates"])
    )


@pytest.mark.parametrize("key", ("existing_silk_objects", "fixed_silk_objects"))
def test_context_search_rejects_silk_obstacle_overlap(key: str) -> None:
    context = _context()
    context[key] = [{"layer": "F.SilkS", "bbox_mm": [8.0, 7.0, 12.0, 9.0]}]
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(order="top", limit=0.25),), ()),
        context,
    )
    assert any(
        item["reason"] == key
        for item in cast(list[dict[str, object]], result[0]["rejected_candidates"])
    )


def test_context_search_applies_same_side_body_and_courtyard_checks() -> None:
    context = _context()
    context["body_bboxes_mm"] = [
        {"refdes": "J1", "layer": "B.Cu", "bbox_mm": [8.0, 7.0, 12.0, 9.0]}
    ]
    context["courtyard_bboxes_mm"] = [
        {"refdes": "J1", "layer": "F.Cu", "bbox_mm": [8.0, 7.0, 12.0, 9.0]}
    ]
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(order="top", limit=0.25),), ()),
        context,
    )
    reasons = {
        item["reason"]
        for item in cast(list[dict[str, object]], result[0]["rejected_candidates"])
    }
    assert "courtyard_bboxes_mm" in reasons
    assert "body_bboxes_mm" not in reasons


def test_context_search_rejects_nearest_component_mismatch() -> None:
    context = _context()
    context["body_bboxes_mm"] = [
        {"refdes": "J1", "layer": "F.Cu", "bbox_mm": [9.0, 9.0, 11.0, 11.0]},
        {"refdes": "U1", "layer": "F.Cu", "bbox_mm": [8.0, 9.0, 8.5, 11.0]},
    ]
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(order="top", limit=0.25),), ()),
        context,
    )
    assert any(
        item["reason"] == "nearest_component_mismatch"
        for item in cast(list[dict[str, object]], result[0]["rejected_candidates"])
    )


def test_context_search_generates_all_orthogonal_rotations() -> None:
    result = resolve_from_context(
        SilkscreenLane("board.gd1", (_search_text(),), ()),
        _context(),
    )
    rotations = {
        float(cast(float | int, item["rotation_deg"]))
        for item in cast(list[dict[str, object]], result[0]["candidates"])
    }
    assert rotations == {0.0, 90.0, 180.0, 270.0}


@pytest.mark.parametrize(
    ("text", "measured_width", "measured_height"),
    (
        ("RST", 2.455952, 1.15),
        ("BOOT", 3.598809, 1.15),
        ("DEV BOARD", 8.15, 1.15),
        ("golden-design-1-r1", 15.789286, 1.461366),
    ),
)
def test_text_size_contains_projected_silkscreen_measurements(
    text: str, measured_width: float, measured_height: float
) -> None:
    view = _search_text()
    view = SilkTextView(
        view.node_id,
        view.role,
        text,
        view.x_mm,
        view.y_mm,
        view.layer,
        view.height_mm,
        view.stroke_width_mm,
        view.rotation_deg,
        view.placement_basis,
        view.placement_search_order,
        view.placement_reference,
        view.placement_offset_step_mm,
        view.placement_search_limit_mm,
    )
    width, height = _text_size(view)
    assert width >= measured_width + 2 * view.stroke_width_mm
    assert height >= measured_height
