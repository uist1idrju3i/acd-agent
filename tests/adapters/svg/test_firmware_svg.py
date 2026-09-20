"""Tests for deterministic firmware SVG projections."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.svg import generate_firmware_visual_projections
from acd.adapters.svg.common import SvgVisualProjectionError
from acd.adapters.svg.firmware import (
    FirmwareProjectionType,
    SvgFirmwareRenderer,
)
from acd.core.firmware.firmware_lane import FirmwareLane, extract_firmware_lane
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
        projection_ids=("gd1-firmware-state", "gd1-firmware-sequence"),
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
    state_svg = (tmp_path / "visual" / "gd1-firmware-state.svg").read_text(
        encoding="utf-8"
    )
    sequence_svg = (tmp_path / "visual" / "gd1-firmware-sequence.svg").read_text(
        encoding="utf-8"
    )
    assert "Firmware state machine" in state_svg
    assert 'id="title"' in state_svg and 'id="state-view-legend"' in state_svg
    # Human label: state name is primary, the node id is secondary.
    assert ">sensor_init</text>" in state_svg
    assert ">fw.state.sensor_init</text>" in state_svg
    # Exactly one initial marker, on the declared entry state.
    assert state_svg.count('id="fw-state-initial-') == 1
    assert "fw-state-initial-fw-state-boot" in state_svg
    assert "fw-transition-fw-transition-boot-sensor-init" in state_svg
    assert ">boot_complete</text>" in state_svg
    # BFS order puts the entry state leftmost.
    box_x = {
        frag: float(match.group(2))
        for frag, match in (
            (m.group(1), m)
            for m in re.finditer(
                r'id="fw-state-box-([a-z0-9-]+)" x="([0-9.]+)"', state_svg
            )
        )
    }
    assert min(box_x, key=lambda frag: box_x[frag]) == "fw-state-boot"
    # 240 unit wide viewBox * DIAGRAM_FONT_SIZE_RATIO
    assert 'font-size="3"' in state_svg
    assert 'viewBox="0 0 ' in state_svg
    assert "2026-" not in state_svg
    assert "/home/" not in state_svg
    assert "Firmware sequence" in sequence_svg
    assert 'id="sequence-view-legend"' in sequence_svg
    assert "fw-lifeline-fw-module-main" in sequence_svg
    assert "Main firmware" in sequence_svg
    assert "fw-sequence-step-001" in sequence_svg
    assert "fw-sequence-action-001-fw-sequence-001" in sequence_svg
    # Visible step-number badge at the left margin.
    assert '>1</text>' in sequence_svg
    assert 'id="fw-seqnum-001"' in sequence_svg
    assert 'font-size="3"' in sequence_svg
    assert "2026-" not in sequence_svg


def _generate(
    tmp_path: Path,
    *,
    renderer: SvgFirmwareRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
    source_revision: str | None = None,
    lane: FirmwareLane | None = None,
    authoritative_inputs: tuple[Path, ...] | None = None,
    target_captions: Mapping[str, str] | None = None,
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
        target_captions=target_captions,
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
            target_captions: Mapping[str, str],
            output_path: Path,
        ) -> None:
            super()._write_svg(
                projection_type=projection_type,
                lane=lane,
                target_captions=target_captions,
                output_path=output_path,
            )
            self.writes += 1
            if self.writes == 2:
                output_path.write_bytes(output_path.read_bytes() + b" ")

    with pytest.raises(SvgVisualProjectionError, match="regeneration"):
        _generate(tmp_path, renderer=NondeterministicRenderer())


def test_sequence_target_captions_render_primary_and_secondary_labels(
    tmp_path: Path,
) -> None:
    captions = {
        "comp.u1": "U1 MCU",
        "comp.u3": "U3 sensor",
        "comp.d1": "D1 status LED",
    }
    projection_set = _generate(tmp_path, target_captions=captions)
    sequence = next(
        record
        for record in projection_set.projections
        if record.projection_type == "firmware_sequence_view"
    )
    svg = (tmp_path / sequence.image_path).read_text(encoding="utf-8")
    assert ">U1 MCU</text>" in svg
    assert '>comp.u1</text>' in svg
    assert 'id="fw-lifeline-sub-comp-u1"' in svg
    assert 'data-node-id="comp.u1"' in svg

    second = _generate(tmp_path / "second", target_captions=captions)
    assert projection_set.identity_hash == second.identity_hash


def test_sequence_target_captions_default_and_invalid_keys_fail_closed(
    tmp_path: Path,
) -> None:
    projection_set = _generate(tmp_path)
    sequence = next(
        record
        for record in projection_set.projections
        if record.projection_type == "firmware_sequence_view"
    )
    svg = (tmp_path / sequence.image_path).read_text(encoding="utf-8")
    assert ">comp.u1</text>" in svg

    with pytest.raises(SvgVisualProjectionError, match="unknown target"):
        _generate(tmp_path / "unknown", target_captions={"comp.missing": "U9"})
    with pytest.raises(SvgVisualProjectionError, match="must not be empty"):
        _generate(tmp_path / "blank", target_captions={"comp.u1": " "})


def test_state_transition_labels_have_placement_metadata_without_overlap(
    tmp_path: Path,
) -> None:
    projection_set = _generate(tmp_path)
    state = next(
        record
        for record in projection_set.projections
        if record.projection_type == "firmware_state_view"
    )
    svg = (tmp_path / state.image_path).read_text(encoding="utf-8")
    paths = {
        match.group("id"): tuple(float(value) for value in match.groups()[1:])
        for match in re.finditer(
            r'id="(?P<id>fw-transition-[^"]+)"[^>]*'
            r'd="M (?P<x1>[0-9.]+) (?P<y1>[0-9.]+) V '
            r'(?P<lane>[0-9.]+) H (?P<x2>[0-9.]+) V '
            r'(?P<y2>[0-9.]+)"',
            svg,
        )
    }
    labels = list(
        re.finditer(
            r'<rect id="fw-label-(?P<label>[^"]+)" '
            r'data-transition-id="(?P<transition>[^"]+)" '
            r'data-label-placement="(?P<placement>[^"]+)" '
            r'x="(?P<x>[0-9.]+)" y="(?P<y>[0-9.]+)" '
            r'width="(?P<w>[0-9.]+)" height="(?P<h>[0-9.]+)"',
            svg,
        )
    )
    assert labels
    assert {match.group("placement") for match in labels} <= {"clear", "fallback"}
    assert all(
        f'fw-transition-{match.group("label")}' in paths for match in labels
    )

    for label in labels:
        if label.group("placement") != "clear":
            continue
        label_x1 = float(label.group("x"))
        label_x2 = label_x1 + float(label.group("w"))
        label_y1 = float(label.group("y"))
        label_y2 = label_y1 + float(label.group("h"))
        own = f'fw-transition-{label.group("label")}'
        for path_id, values in paths.items():
            if path_id == own:
                continue
            x1, y1, lane_y, x2, y2 = values
            for vertical_x, endpoint_y in ((x1, y1), (x2, y2)):
                if (
                    label_x1 < vertical_x < label_x2
                    and max(min(endpoint_y, lane_y), label_y1)
                    < min(max(endpoint_y, lane_y), label_y2)
                ):
                    raise AssertionError(
                        f"clear label {label.group('transition')} intersects {path_id}"
                    )

    for first_index, first in enumerate(labels):
        first_y1 = float(first.group("y"))
        first_y2 = first_y1 + float(first.group("h"))
        for second in labels[first_index + 1 :]:
            second_y1 = float(second.group("y"))
            second_y2 = second_y1 + float(second.group("h"))
            assert first_y2 <= second_y1 or second_y2 <= first_y1


def test_state_transition_label_fallback_still_renders(tmp_path: Path) -> None:
    graph_path, graph = _fixture()
    lane = extract_firmware_lane(graph)
    long_transitions = tuple(
        replace(transition, trigger="x" * 10_000)
        for transition in lane.transitions
    )
    projection_set = _generate(
        tmp_path,
        lane=replace(lane, transitions=long_transitions),
        authoritative_inputs=(graph_path,),
    )
    state = next(
        record
        for record in projection_set.projections
        if record.projection_type == "firmware_state_view"
    )
    svg = (tmp_path / state.image_path).read_text(encoding="utf-8")
    assert 'data-label-placement="fallback"' in svg


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
    assert first.canonical_hash != second.canonical_hash
    assert [record.image_hash for record in first.projections] == [
        record.image_hash for record in second.projections
    ]
