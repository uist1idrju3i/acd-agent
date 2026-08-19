"""Tests for deterministic firmware SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.svg import generate_firmware_visual_projections
from acd.adapters.svg.common import SvgVisualProjectionError
from acd.adapters.svg.firmware import (
    FirmwareProjectionType,
    SvgFirmwareRenderer,
)
from acd.core.firmware_lane import FirmwareLane, extract_firmware_lane
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


def _generate(
    tmp_path: Path,
    *,
    renderer: SvgFirmwareRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
    source_revision: str | None = None,
    lane: FirmwareLane | None = None,
    authoritative_inputs: tuple[Path, ...] | None = None,
):
    graph_path, graph = _fixture()
    return generate_firmware_visual_projections(
        project_name="gd1",
        out_dir=tmp_path,
        source_revision=source_revision or graph.revision,
        lane=lane or extract_firmware_lane(graph),
        authoritative_inputs=authoritative_inputs or (graph_path,),
        input_base_dir=repository_root(),
        renderer=renderer,
        projection_ids=projection_ids,
    )


def test_unknown_renderer_version_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SvgVisualProjectionError, match="unknown"):
        _generate(tmp_path, renderer=SvgFirmwareRenderer(tool_version="unknown"))


def test_missing_input_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SvgVisualProjectionError, match="missing"):
        _generate(
            tmp_path,
            authoritative_inputs=(tmp_path / "missing-graph.json",),
        )


def test_duplicate_projection_ids_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SvgVisualProjectionError, match="identifiers"):
        _generate(tmp_path, projection_ids=("same", "same"))


def test_nondeterministic_renderer_fails_closed(tmp_path: Path) -> None:
    class NondeterministicRenderer(SvgFirmwareRenderer):
        writes = 0

        def _write_svg(
            self,
            *,
            projection_type: FirmwareProjectionType,
            lane: FirmwareLane,
            output_path: Path,
        ) -> None:
            super()._write_svg(
                projection_type=projection_type,
                lane=lane,
                output_path=output_path,
            )
            self.writes += 1
            if self.writes == 2:
                output_path.write_bytes(output_path.read_bytes() + b" ")

    with pytest.raises(SvgVisualProjectionError, match="regeneration"):
        _generate(tmp_path, renderer=NondeterministicRenderer())


@pytest.mark.parametrize("field", ["states", "transitions", "sequence_steps"])
def test_missing_firmware_declaration_fails_closed(
    tmp_path: Path,
    field: str,
) -> None:
    graph_path, graph = _fixture()
    lane = extract_firmware_lane(graph)
    empty_lane = replace(lane, **{field: ()})
    with pytest.raises(SvgVisualProjectionError, match="requires declared"):
        _generate(
            tmp_path,
            lane=empty_lane,
            authoritative_inputs=(graph_path,),
        )


def test_projection_hashes_are_reproducible(tmp_path: Path) -> None:
    first = _generate(tmp_path / "first")
    second = _generate(tmp_path / "second")

    assert first.identity_hash == second.identity_hash
    assert [record.image_hash for record in first.projections] == [
        record.image_hash for record in second.projections
    ]
