"""Tests for deterministic firmware SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path

from acd.adapters.svg import generate_firmware_visual_projections
from acd.core.firmware_lane import extract_firmware_lane
from acd.pipeline.repository import repository_root
from acd.pipeline.visual_projection import crosscheck_firmware_visual_projections
from acd.schema.design_graph import DesignGraph


def _fixture() -> tuple[Path, DesignGraph]:
    graph_path = Path("fixtures/golden-design-1/graph.json")
    graph = DesignGraph.model_validate(
        json.loads(graph_path.read_text(encoding="utf-8"))
    )
    return graph_path, graph


def test_firmware_projections_are_deterministic_and_crosschecked(
    tmp_path: Path,
) -> None:
    graph_path, graph = _fixture()
    lane = extract_firmware_lane(graph)
    projection_set = generate_firmware_visual_projections(
        project_name="gd1",
        out_dir=tmp_path,
        source_revision=graph.revision,
        lane=lane,
        authoritative_inputs=(graph_path,),
        input_base_dir=repository_root(),
        projection_ids=("gd1-firmware-state", "gd1-firmware-sequence"),
    )
    report = crosscheck_firmware_visual_projections(
        source_revision=graph.revision,
        visual_projection_set=projection_set,
        lane=lane,
        graph_input=graph_path,
        base_dir=tmp_path,
        input_base_dir=repository_root(),
    )

    assert report.status == "match"
    assert [item.projection_id for item in projection_set.projections] == [
        "gd1-firmware-sequence",
        "gd1-firmware-state",
    ]
    assert {
        item.projection_type for item in projection_set.projections
    } == {"firmware_state_view", "firmware_sequence_view"}
    assert all(
        item.status == "unknown" and item.verification == "observation_required"
        for item in report.review_items
    )
    state_svg = (tmp_path / "visual" / "gd1-firmware-state.svg").read_text()
    sequence_svg = (
        tmp_path / "visual" / "gd1-firmware-sequence.svg"
    ).read_text()
    assert 'width="240mm"' in state_svg
    assert 'viewBox="0 0 240 134"' in state_svg
    assert "fw-state-initial-fw-state-boot" in state_svg
    assert "fw-transition-fw-transition-boot-sensor-init" in state_svg
    assert 'width="240mm"' in sequence_svg
    assert "fw-sequence-step-001" in sequence_svg
    assert "fw-sequence-action-001-fw-sequence-001" in sequence_svg
