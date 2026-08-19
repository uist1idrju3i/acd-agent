"""Tests for deterministic electrical visual cross-checks."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.core.board_model import BoardModel, CopperZone
from acd.core.electrical import BoardView, ComponentView, ElectricalLane, LibraryPin
from acd.core.visual_projection import normalized_svg_sha256
from acd.pipeline.visual_projection import crosscheck_electrical_visual_projections
from acd.schema.visual_crosscheck import (
    VisualCrosscheckItem,
    VisualCrosscheckReport,
    VisualProjectionCrosscheck,
    VisualReviewChecklistItem,
    VisualReviewObservationReference,
)
from acd.schema.visual_projection import VisualProjectionSet


def _lane_and_board(layer_count: int = 2) -> tuple[ElectricalLane, BoardModel]:
    board_view = BoardView(
        node_id="electrical-board",
        width_mm=30.0,
        height_mm=25.0,
        layers=layer_count,
        thickness_mm=1.6,
        unit="mm",
        origin="upper-left",
        y_axis="down",
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
        ground_plane_layers=("F.Cu", "B.Cu"),
    )
    lane = ElectricalLane(components=(), nets=(), pins=(), board=board_view)
    board = BoardModel(
        width_mm=30.0,
        height_mm=25.0,
        layers=layer_count,
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_clearance_mm=0.3,
        placements=(),
        nets=(),
        copper_zones=(CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    return lane, board


def _svg(file_name: str, *, refs: tuple[str, ...] = (), width: str = "30mm",
         height: str = "25mm", view_box: str = "0 0 30 25") -> bytes:
    ref_text = "".join(f"<text>{ref}</text>" for ref in refs)
    return (
        f'<svg width="{width}" height="{height}" viewBox="{view_box}">'
        '<title>SVG Image created as gd1.svg date 2026-08-19T03:45:00 </title>'
        "<desc>KiCad E.D.A. 10.0.5</desc>"
        f"<text>File: {file_name}</text>{ref_text}</svg>"
    ).encode()


def _projection(
    *,
    projection_id: str,
    projection_type: str,
    source_file: str,
    image_path: str,
    image_hash: str,
) -> dict[str, object]:
    return {
        "projection_id": projection_id,
        "projection_type": projection_type,
        "domain": "electrical",
        "source_revision": "r8",
        "input_files": [{"path": source_file, "content_hash": "sha256:" + "1" * 64}],
        "renderer": {
            "renderer_type": "kicad-cli",
            "tool_name": "kicad-cli",
            "tool_version": "10.0.5",
        },
        "media_type": "image/svg+xml",
        "resolution": {
            "width": "30mm",
            "height": "25mm",
            "view_box": [0.0, 0.0, 30.0, 25.0],
        },
        "normalization_rule_id": "kicad-svg-title-v1",
        "normalization_rule_description": "Replace one volatile KiCad SVG title.",
        "image_hash": image_hash,
        "generated_at": datetime(2026, 8, 19, tzinfo=UTC).isoformat(),
        "regeneration_check": {
            "status": "reproduced",
            "first_image_hash": image_hash,
            "second_image_hash": image_hash,
        },
        "image_path": image_path,
    }


def _fixture(
    tmp_path: Path,
    *,
    schematic: bytes | None = None,
    board: bytes | None = None,
    records: list[dict[str, object]] | None = None,
) -> tuple[Path, VisualProjectionSet, ElectricalLane, BoardModel]:
    visual_dir = tmp_path / "visual"
    visual_dir.mkdir(parents=True)
    schematic = schematic or _svg("gd1.kicad_sch")
    board = board or _svg("gd1.kicad_pcb")
    (visual_dir / "gd1-schematic.svg").write_bytes(schematic)
    (visual_dir / "gd1-f-cu.svg").write_bytes(board)
    (visual_dir / "gd1-b-cu.svg").write_bytes(board)
    if records is None:
        records = [
            _projection(
                projection_id="gd1-schematic",
                projection_type="schematic_view",
                source_file="gd1.kicad_sch",
                image_path="visual/gd1-schematic.svg",
                image_hash=normalized_svg_sha256(schematic),
            ),
            _projection(
                projection_id="gd1-f-cu",
                projection_type="layered_layout_view",
                source_file="gd1.kicad_pcb",
                image_path="visual/gd1-f-cu.svg",
                image_hash=normalized_svg_sha256(board),
            ),
            _projection(
                projection_id="gd1-b-cu",
                projection_type="layered_layout_view",
                source_file="gd1.kicad_pcb",
                image_path="visual/gd1-b-cu.svg",
                image_hash=normalized_svg_sha256(board),
            ),
        ]
    projection_set = VisualProjectionSet.model_validate(
        {
            "source_revision": "r8",
            "projections": sorted(records, key=lambda record: str(record["projection_id"])),
        }
    ).with_computed_hashes()
    source_schematic = tmp_path / "gd1.kicad_sch"
    source_board = tmp_path / "routed" / "gd1.kicad_pcb"
    source_board.parent.mkdir()
    source_schematic.write_text("schematic")
    source_board.write_text("board")
    lane, board_model = _lane_and_board()
    return tmp_path, projection_set, lane, board_model


def _crosscheck(tmp_path: Path) -> VisualCrosscheckReport:
    base_dir, projection_set, lane, board = _fixture(tmp_path)
    return crosscheck_electrical_visual_projections(
        project_name="gd1",
        source_revision="r8",
        visual_projection_set=projection_set,
        lane=lane,
        board=board,
        base_dir=base_dir,
        machine_inputs=(base_dir / "gd1.kicad_sch", base_dir / "routed/gd1.kicad_pcb"),
    )


def test_crosscheck_is_reproducible_and_writes_report(tmp_path: Path) -> None:
    first = _crosscheck(tmp_path / "first")
    second = _crosscheck(tmp_path / "second")

    assert first.status == "match"
    assert first.crosschecks == second.crosschecks
    assert first.review_items == second.review_items
    assert first.identity_hash == second.identity_hash
    assert (tmp_path / "first/visual-crosscheck-electrical.json").is_file()
    assert not (tmp_path / "first/hashes.json").exists()
    assert all(
        item.status == "unknown"
        for item in first.review_items
        if item.verification == "observation_required"
    )


@pytest.mark.parametrize(
    ("mutation",),
    [
        ("missing_layer",),
        ("extra_layer",),
        ("missing_schematic",),
        ("multiple_schematic",),
        ("non_mm",),
        ("non_zero_origin",),
        ("view_box_mismatch",),
        ("file_mismatch",),
        ("renderer_mismatch",),
        ("image_hash_mismatch",),
        ("missing_refdes",),
    ],
)
def test_crosscheck_mismatches_fail_closed(tmp_path: Path, mutation: str) -> None:
    base_dir, projection_set, lane, board = _fixture(tmp_path)
    records = [record.model_dump(mode="json") for record in projection_set.projections]
    if mutation == "missing_layer":
        records = [record for record in records if record["projection_id"] != "gd1-b-cu"]
    elif mutation == "extra_layer":
        extra = deepcopy(records[1])
        extra["projection_id"] = "gd1-in1-cu"
        extra["image_path"] = "visual/gd1-f-cu.svg"
        records.append(extra)
    elif mutation == "missing_schematic":
        records = [record for record in records if record["projection_id"] != "gd1-schematic"]
    elif mutation == "multiple_schematic":
        extra = deepcopy(records[0])
        extra["projection_id"] = "gd1-schematic-2"
        records.append(extra)
    elif mutation == "renderer_mismatch":
        records[0]["renderer"]["tool_version"] = "9.0.0"  # type: ignore[index]
    elif mutation == "image_hash_mismatch":
        records[0]["image_hash"] = "sha256:" + "f" * 64
    elif mutation == "missing_refdes":
        lane = replace(
            lane,
            components=(
                ComponentView(
                    node_id="component-u1",
                    refdes="U1",
                    value="controller",
                    mpn="mpn",
                    lcsc="lcsc",
                    jlcpcb_class="class",
                    assembly="yes",
                    library=LibraryPin(
                        symbol="Device:R",
                        symbol_file="symbol.kicad_sym",
                        symbol_source="fixture",
                        symbol_source_ref="fixture",
                        symbol_sha256="sha256:" + "1" * 64,
                        footprint="Package:QFN",
                        footprint_file="footprints.pretty",
                        footprint_source="fixture",
                        footprint_source_ref="fixture",
                        footprint_sha256="sha256:" + "2" * 64,
                    ),
                ),
            ),
        )
    elif mutation in {"non_mm", "non_zero_origin", "view_box_mismatch", "file_mismatch"}:
        content = _svg(
            "wrong.kicad_sch" if mutation == "file_mismatch" else "gd1.kicad_sch",
            width="30cm" if mutation == "non_mm" else "30mm",
            view_box="1 0 30 25" if mutation == "non_zero_origin" else "0 0 31 25"
            if mutation == "view_box_mismatch"
            else "0 0 30 25",
        )
        (base_dir / "visual/gd1-schematic.svg").write_bytes(content)
    mutated_set = VisualProjectionSet.model_validate(
        {
            "source_revision": "r8",
            "projections": sorted(records, key=lambda record: str(record["projection_id"])),
        }
    ).with_computed_hashes()
    report = crosscheck_electrical_visual_projections(
        project_name="gd1",
        source_revision="r8",
        visual_projection_set=mutated_set,
        lane=lane,
        board=board,
        base_dir=base_dir,
        machine_inputs=(base_dir / "gd1.kicad_sch", base_dir / "routed/gd1.kicad_pcb"),
    )
    assert report.status == "mismatch"


def test_unknown_crosscheck_status_cannot_be_aggregated_as_match() -> None:
    item = VisualCrosscheckItem(
        check_id="check",
        description="description",
        status="unknown",
        expected="expected",
        actual="actual",
        machine_field="field",
    )
    with pytest.raises(ValidationError):
        VisualProjectionCrosscheck(
            projection_id="projection",
            source_revision="r8",
            image_hash="sha256:" + "1" * 64,
            items=[item],
            status="match",
        )


def test_review_observation_is_not_evidence() -> None:
    with pytest.raises(ValidationError):
        VisualReviewChecklistItem(
            item_id="readability",
            aspect="readability",
            verification="observation_required",
            status="match",
            basis="observation",
        )
    with pytest.raises(ValidationError):
        VisualReviewObservationReference.model_validate(
            {
                "pass_evidence": True,
                "profile_name": "vision",
                "model": "model",
                "projection_id": "projection",
                "image_hash": "sha256:" + "1" * 64,
            }
        )


def test_report_rejects_evidence_promotion_and_unsafe_machine_paths(tmp_path: Path) -> None:
    report = _crosscheck(tmp_path)
    evidence_payload = report.model_dump(mode="json")
    evidence_payload["pass_evidence"] = True
    with pytest.raises(ValidationError):
        VisualCrosscheckReport.model_validate(evidence_payload)

    unsafe_payload = report.model_dump(mode="json")
    unsafe_payload["identity_hash"] = "unknown"
    unsafe_payload["canonical_hash"] = "unknown"
    unsafe_payload["machine_input_files"][0]["path"] = "../gd1.kicad_sch"
    with pytest.raises(ValidationError):
        VisualCrosscheckReport.model_validate(unsafe_payload)
