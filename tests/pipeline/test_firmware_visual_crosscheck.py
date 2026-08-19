"""Negative and reproducibility tests for firmware visual cross-checks."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd.adapters.svg import generate_firmware_visual_projections
from acd.core.firmware_lane import (
    FirmwareLane,
    FirmwareSequenceStepView,
    FirmwareStateView,
    extract_firmware_lane,
)
from acd.core.process import sha256_bytes
from acd.pipeline.repository import repository_root
from acd.pipeline.visual_projection import crosscheck_firmware_visual_projections
from acd.schema.design_graph import DesignGraph
from acd.schema.visual_crosscheck import VisualCrosscheckReport
from acd.schema.visual_projection import VisualProjectionInput, VisualProjectionSet

GRAPH_PATH = Path("fixtures/golden-design-1/graph.json")


def _context(
    tmp_path: Path,
) -> tuple[DesignGraph, FirmwareLane, VisualProjectionSet]:
    graph = DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )
    lane = extract_firmware_lane(graph)
    projections = generate_firmware_visual_projections(
        project_name="gd1",
        out_dir=tmp_path,
        source_revision=graph.revision,
        lane=lane,
        authoritative_inputs=(GRAPH_PATH,),
        input_base_dir=repository_root(),
        projection_ids=("gd1-firmware-state", "gd1-firmware-sequence"),
    )
    return graph, lane, projections


def _report(
    tmp_path: Path,
    *,
    lane: FirmwareLane | None = None,
    projections: VisualProjectionSet | None = None,
    source_revision: str | None = None,
) -> VisualCrosscheckReport:
    graph = DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )
    original_lane = lane or extract_firmware_lane(graph)
    original_projections = projections
    if original_projections is None:
        original_projections = _context(tmp_path)[2]
    return crosscheck_firmware_visual_projections(
        source_revision=source_revision or graph.revision,
        visual_projection_set=projections or original_projections,
        lane=lane or original_lane,
        graph_input=GRAPH_PATH,
        base_dir=tmp_path,
        input_base_dir=repository_root(),
    )


def _replace_projection(
    projection_set: VisualProjectionSet,
    projection_id: str,
    **changes: object,
) -> VisualProjectionSet:
    records = [
        record.model_copy(update=changes)
        if record.projection_id == projection_id
        else record
        for record in projection_set.projections
    ]
    return projection_set.model_copy(update={"projections": records})


def test_malformed_svg_fails_closed(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    state = tmp_path / "visual/gd1-firmware-state.svg"
    state.write_text("<svg>", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be parsed"):
        _report(tmp_path, projections=projections)


def test_svg_image_hash_mismatch_is_reported(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    state = tmp_path / "visual/gd1-firmware-state.svg"
    state.write_bytes(state.read_bytes() + b" ")
    report = _report(tmp_path, projections=projections)
    assert report.status == "mismatch"
    assert any(
        item.check_id == "svg-image-hash" and item.status == "mismatch"
        for record in report.crosschecks
        for item in record.items
    )


def test_declaration_coverage_mismatch_is_fail_closed(tmp_path: Path) -> None:
    _, lane, projections = _context(tmp_path)
    extra_state = FirmwareStateView(
        node_id="fw-state-extra",
        state_name="extra",
        initial=False,
    )
    report = _report(
        tmp_path,
        lane=replace(lane, states=(*lane.states, extra_state)),
        projections=projections,
    )
    assert report.status == "mismatch"
    assert any(
        item.check_id == "state-coverage" and item.status == "mismatch"
        for record in report.crosschecks
        for item in record.items
    )


def test_initial_marker_mismatch_is_fail_closed(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    state = tmp_path / "visual/gd1-firmware-state.svg"
    svg = state.read_text(encoding="utf-8")
    state.write_text(
        svg.replace('id="fw-state-initial-fw-state-boot"', 'id="removed"'),
        encoding="utf-8",
    )
    report = _report(tmp_path, projections=projections)
    assert report.status == "mismatch"
    assert any(
        item.check_id == "initial-state" and item.status == "mismatch"
        for record in report.crosschecks
        for item in record.items
    )


@pytest.mark.parametrize("kind", ["graph", "set", "record"])
def test_revision_mismatch_fails_closed(tmp_path: Path, kind: str) -> None:
    _, _, projections = _context(tmp_path)
    if kind == "graph":
        with pytest.raises(ValueError, match="graph and source"):
            _report(tmp_path, projections=projections, source_revision="r999")
    elif kind == "set":
        altered = projections.model_copy(update={"source_revision": "r999"})
        with pytest.raises(ValueError, match="source revisions"):
            _report(tmp_path, projections=altered)
    else:
        altered = _replace_projection(
            projections,
            "gd1-firmware-state",
            source_revision="r999",
        )
        with pytest.raises(ValueError, match="projection revisions"):
            _report(tmp_path, projections=altered)


def test_input_path_and_hash_mismatch_are_fail_closed(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    altered_input = [VisualProjectionInput(path="other.json", content_hash="sha256:" + "0" * 64)]
    altered = _replace_projection(
        projections,
        "gd1-firmware-state",
        input_files=altered_input,
    )
    report = _report(tmp_path, projections=altered)
    assert report.status == "mismatch"
    assert any(
        item.check_id == "input-file" and item.status == "mismatch"
        for record in report.crosschecks
        for item in record.items
    )


@pytest.mark.parametrize("change", ["renderer_type", "version", "normalization"])
def test_renderer_provenance_mismatch_is_fail_closed(
    tmp_path: Path,
    change: str,
) -> None:
    _, _, projections = _context(tmp_path)
    record = next(
        item for item in projections.projections
        if item.projection_id == "gd1-firmware-state"
    )
    renderer = record.renderer
    if change == "renderer_type":
        renderer = renderer.model_copy(
            update={"renderer_type": "kicad-cli", "tool_name": "kicad-cli"}
        )
    elif change == "version":
        renderer = renderer.model_copy(update={"tool_version": "other"})
    altered = _replace_projection(
        projections,
        "gd1-firmware-state",
        renderer=renderer,
        normalization_rule_id=(
            "other" if change == "normalization" else record.normalization_rule_id
        ),
    )
    report = _report(tmp_path, projections=altered)
    assert report.status == "mismatch"
    assert any(
        item.check_id == "svg-renderer" and item.status == "mismatch"
        for record in report.crosschecks
        for item in record.items
    )


def test_transition_mismatch_actual_lists_node_and_fields(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    state = tmp_path / "visual/gd1-firmware-state.svg"
    svg = state.read_text(encoding="utf-8")
    svg = svg.replace(
        'data-trigger="sensor_init_complete"',
        'data-trigger="wrong_trigger"',
    ).replace(">sensor_init_complete</text>", ">wrong_trigger</text>")
    state.write_text(svg, encoding="utf-8")
    altered = _replace_projection(
        projections,
        "gd1-firmware-state",
        image_hash=sha256_bytes(state.read_bytes()),
    )
    report = _report(tmp_path, projections=altered)
    item = next(
        item
        for record in report.crosschecks
        for item in record.items
        if item.check_id == "transition-declarations"
    )
    assert item.status == "mismatch"
    assert item.actual == (
        "fw.transition.sensor_init_measure:trigger,"
        "fw.transition.sensor_init_measure:text"
    )


def test_sequence_mismatch_actual_lists_step_and_fields(tmp_path: Path) -> None:
    _, _, projections = _context(tmp_path)
    sequence = tmp_path / "visual/gd1-firmware-sequence.svg"
    svg = sequence.read_text(encoding="utf-8")
    svg = svg.replace(
        'data-action="read_temperature_humidity"',
        'data-action="wrong_action"',
    )
    sequence.write_text(svg, encoding="utf-8")
    altered = _replace_projection(
        projections,
        "gd1-firmware-sequence",
        image_hash=sha256_bytes(sequence.read_bytes()),
    )
    report = _report(tmp_path, projections=altered)
    item = next(
        item
        for record in report.crosschecks
        for item in record.items
        if item.check_id == "sequence-declarations"
    )
    assert item.status == "mismatch"
    assert item.actual == "fw.sequence.004[4]:action"


def test_pin_assignment_is_one_set_item_and_reviews_do_not_match(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    assert report.status == "match"
    assert [item.check_id for item in report.set_items] == [
        "projection-coverage",
        "pin-assignments",
    ]
    assert all(item.status == "unknown" for item in report.review_items)


def test_crosscheck_hashes_are_reproducible(tmp_path: Path) -> None:
    first = _report(tmp_path)
    second = _report(tmp_path)
    assert first.identity_hash == second.identity_hash
    assert first.canonical_hash != second.canonical_hash


def test_sequence_declaration_mismatch_is_fail_closed(tmp_path: Path) -> None:
    _, lane, projections = _context(tmp_path)
    extra_step = FirmwareSequenceStepView(
        node_id="fw-sequence-extra",
        step_index=6,
        actor=lane.module.node_id,
        target=lane.module.node_id,
        action="extra",
    )
    report = _report(
        tmp_path,
        lane=replace(lane, sequence_steps=(*lane.sequence_steps, extra_step)),
        projections=projections,
    )
    assert report.status == "mismatch"
