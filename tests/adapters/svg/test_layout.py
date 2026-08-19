"""Tests for deterministic placement and stackup SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from acd.adapters.svg.layout import (
    ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
    LayoutVisualProjectionError,
    SvgLayoutRenderer,
    generate_layout_visual_projections,
)
from acd.core.board_model import (
    BoardModel,
    ComponentPlacement,
    FootprintShape,
)
from acd.core.electrical import BoardView
from acd.core.visual_projection import measure_svg_resolution
from acd.schema.visual_projection import VisualProjectionSet


def _board(*, side: str = "front", empty: bool = False, layers: int = 2) -> BoardModel:
    footprint = FootprintShape(
        library_ref="Test:FP",
        pads=(),
        courtyard_bbox_mm=(-1.0, -0.5, 1.0, 0.5),
    )
    placements = (
        ComponentPlacement("R1", footprint, 10.0, 10.0, 0.0, side=side),
    )
    return BoardModel(
        width_mm=30.0,
        height_mm=20.0,
        layers=layers,
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_clearance_mm=0.3,
        placements=() if empty else placements,
        nets=(),
    )


def _board_view(*, layers: int = 2) -> BoardView:
    return BoardView(
        node_id="board",
        width_mm=30.0,
        height_mm=20.0,
        layers=layers,
        thickness_mm=1.6,
        unit="mm",
        origin="board_upper_left",
        y_axis="down",
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
        outer_copper_thickness_um=35.0,
        copper_thickness_source="declared 1 oz outer copper",
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "graph.json"
    source.write_text('{"revision":"r8"}\n', encoding="utf-8")
    return source, tmp_path


def _generate(
    tmp_path: Path,
    *,
    board: BoardModel | None = None,
    board_view: BoardView | None = None,
    renderer: SvgLayoutRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
):
    source, input_root = _inputs(tmp_path)
    return generate_layout_visual_projections(
        project_name="gd1",
        out_dir=tmp_path / "out",
        source_revision="r8",
        board=board or _board(),
        board_view=board_view or _board_view(),
        authoritative_inputs=(source,),
        input_base_dir=input_root,
        renderer=renderer,
        projection_ids=projection_ids,
    )


def test_generates_placement_and_stackup_with_deterministic_provenance(
    tmp_path: Path,
) -> None:
    projection_set = _generate(tmp_path)

    assert projection_set.pass_evidence is False
    assert [item.projection_type for item in projection_set.projections] == [
        "placement_view",
        "stackup_view",
    ]
    assert all(item.renderer.renderer_type == "acd-svg" for item in projection_set.projections)
    assert all(
        item.renderer.tool_version == ACD_SVG_RENDERER_VERSION
        for item in projection_set.projections
    )
    assert all(
        item.normalization_rule_id == ACD_SVG_NORMALIZATION_RULE_ID
        for item in projection_set.projections
    )
    assert all(
        item.normalization_rule_description == ACD_SVG_NORMALIZATION_RULE_DESCRIPTION
        for item in projection_set.projections
    )
    assert all(
        item.regeneration_check.status == "reproduced"
        for item in projection_set.projections
    )
    assert all(item.input_files[0].path == "graph.json" for item in projection_set.projections)
    assert (tmp_path / "out/visual-projections-layout.json").is_file()

    placement = next(
        item
        for item in projection_set.projections
        if item.projection_type == "placement_view"
    )
    svg = (tmp_path / "out" / placement.image_path).read_bytes()
    assert b'id="front"' in svg
    assert b'id="back"' in svg
    assert b'id="board-outline"' in svg
    assert b"generated_at" not in svg
    assert b"/home/" not in svg
    assert measure_svg_resolution(svg).view_box == (0.0, 0.0, 30.0, 20.0)

    second = _generate(tmp_path / "second")
    assert projection_set.identity_hash == second.identity_hash
    assert [item.image_hash for item in projection_set.projections] == [
        item.image_hash for item in second.projections
    ]


def test_stackup_layers_and_root_geometry_are_measured_from_bytes(tmp_path: Path) -> None:
    projection_set = _generate(
        tmp_path,
        board=_board(layers=4),
        board_view=_board_view(layers=4),
    )
    stackup = next(
        item
        for item in projection_set.projections
        if item.projection_type == "stackup_view"
    )
    svg = (tmp_path / "out" / stackup.image_path).read_bytes()
    assert all(
        marker in svg
        for marker in (b'id="F.Cu"', b'id="In1.Cu"', b'id="In2.Cu"', b'id="B.Cu"')
    )
    resolution = measure_svg_resolution(svg)
    assert resolution.width == "80mm"
    assert resolution.view_box[2:] == (80.0, 21.6)


@pytest.mark.parametrize(
    ("name", "board", "board_view"),
    [
        ("empty placements", _board(empty=True), _board_view()),
        ("unsupported placement side", _board(side="left"), _board_view()),
        ("unsupported layer count", _board(layers=3), _board_view(layers=3)),
        ("missing thickness", _board(), replace(_board_view(), thickness_mm=None)),
        (
            "missing outer copper thickness",
            _board(),
            replace(_board_view(), outer_copper_thickness_um=None),
        ),
        (
            "missing copper thickness source",
            _board(),
            replace(_board_view(), copper_thickness_source=None),
        ),
    ],
)
def test_layout_projection_rejects_undeclared_or_unsupported_values(
    tmp_path: Path,
    name: str,
    board: BoardModel,
    board_view: BoardView,
) -> None:
    with pytest.raises(LayoutVisualProjectionError, match="|".join(name.split())):
        _generate(tmp_path / name.replace(" ", "-"), board=board, board_view=board_view)


def test_missing_authoritative_input_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LayoutVisualProjectionError, match="missing"):
        generate_layout_visual_projections(
            project_name="gd1",
            out_dir=tmp_path / "out",
            source_revision="r8",
            board=_board(),
            board_view=_board_view(),
            authoritative_inputs=(tmp_path / "missing.json",),
            input_base_dir=tmp_path,
        )


def test_placement_anchor_outside_board_fails_closed(tmp_path: Path) -> None:
    placement = _board().placements[0]
    outside = replace(placement, x_mm=31.0)
    board = replace(_board(), placements=(outside,))
    with pytest.raises(LayoutVisualProjectionError, match="outside"):
        _generate(tmp_path, board=board)


def test_unknown_renderer_version_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LayoutVisualProjectionError, match="unknown"):
        _generate(tmp_path, renderer=SvgLayoutRenderer(tool_version="unknown"))


def test_duplicate_projection_identifiers_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unique"):
        _generate(tmp_path, projection_ids=("same", "same"))


def test_second_generation_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    class NonDeterministicRenderer(SvgLayoutRenderer):
        writes = 0

        def _write_svg(
            self,
            *,
            projection_type: Literal["placement_view", "stackup_view"],
            board: BoardModel,
            board_view: BoardView,
            output_path: Path,
        ) -> None:
            super()._write_svg(
                projection_type=projection_type,
                board=board,
                board_view=board_view,
                output_path=output_path,
            )
            self.writes += 1
            if self.writes == 2:
                output_path.write_bytes(output_path.read_bytes() + b" ")

    with pytest.raises(LayoutVisualProjectionError, match="regeneration"):
        _generate(tmp_path, renderer=NonDeterministicRenderer())


def test_revision_mismatch_is_rejected_by_projection_set(tmp_path: Path) -> None:
    projection_set = _generate(tmp_path)
    mutated = projection_set.projections[0].model_copy(update={"source_revision": "r9"})
    with pytest.raises(ValidationError, match="revisions"):
        VisualProjectionSet.model_validate(
            {
                "source_revision": projection_set.source_revision,
                "projections": [
                    mutated.model_dump(mode="json"),
                    projection_set.projections[1].model_dump(mode="json"),
                ],
            }
        )
