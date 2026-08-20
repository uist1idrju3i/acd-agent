"""Deterministic SVG writers for firmware state and sequence observations."""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    DIAGRAM_FONT_SIZE_RATIO,
    SvgVisualProjectionError,
    escape_xml,
    format_svg_number,
    input_records,
    render_svg_projection,
    slugify_identifier,
    view_box_font_size,
)
from acd.core.firmware_lane import FirmwareLane
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)

FirmwareProjectionType = Literal[
    "firmware_state_view",
    "firmware_sequence_view",
]

# Both firmware projections are laid out on a fixed 240-unit wide viewBox.
_DIAGRAM_VIEW_BOX_WIDTH = 240.0


def _state_svg(lane: FirmwareLane) -> bytes:
    states = tuple(sorted(lane.states, key=lambda state: state.node_id))
    transitions = tuple(
        sorted(
            lane.transitions,
            key=lambda transition: (
                transition.from_state,
                transition.to_state,
                transition.trigger,
            ),
        )
    )
    if not states or not transitions:
        raise SvgVisualProjectionError(
            "firmware state projection requires declared states and transitions"
        )
    positions = {
        state.node_id: (30.0, 25.0 + index * 28.0)
        for index, state in enumerate(states)
    }
    height = max(
        80.0,
        50.0 + math.ceil(max(len(states), len(transitions)) / 2) * 28.0,
    )
    font_size = view_box_font_size(_DIAGRAM_VIEW_BOX_WIDTH, ratio=DIAGRAM_FONT_SIZE_RATIO)
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="240mm" '
        f'height="{format_svg_number(height)}mm" '
        f'viewBox="0 0 240 {format_svg_number(height)}">',
        '<g id="firmware-state-view">',
    ]
    for transition in transitions:
        from_x, from_y = positions[transition.from_state]
        to_x, to_y = positions[transition.to_state]
        identifier = slugify_identifier(transition.node_id)
        chunks.extend(
            [
                f'<line id="fw-transition-{identifier}" '
                f'data-node-id="{escape_xml(transition.node_id)}" '
                f'data-from-state="{escape_xml(transition.from_state)}" '
                f'data-to-state="{escape_xml(transition.to_state)}" '
                f'data-trigger="{escape_xml(transition.trigger)}" '
                f'x1="{format_svg_number(from_x + 48)}" '
                f'y1="{format_svg_number(from_y + 8)}" '
                f'x2="{format_svg_number(to_x + 48)}" '
                f'y2="{format_svg_number(to_y + 8)}" stroke="#555"/>',
                f'<text id="fw-transition-trigger-{identifier}" '
                f'x="{format_svg_number(95.0)}" '
                f'y="{format_svg_number((from_y + to_y) / 2 + 6)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(transition.trigger)}</text>",
            ]
        )
    for state in states:
        identifier = slugify_identifier(state.node_id)
        x, y = positions[state.node_id]
        chunks.extend(
            [
                f'<g id="fw-state-{identifier}" '
                f'data-node-id="{escape_xml(state.node_id)}" '
                f'data-state-name="{escape_xml(state.state_name)}" '
                f'data-initial="{str(state.initial).lower()}">',
                f'<rect id="fw-state-box-{identifier}" '
                f'x="{format_svg_number(x)}" y="{format_svg_number(y)}" '
                'width="48" height="16" fill="none" stroke="#000"/>',
                f'<text id="fw-state-label-{identifier}" '
                f'x="{format_svg_number(x + 2)}" '
                f'y="{format_svg_number(y + 10)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(state.node_id)}</text>",
            ]
        )
        if state.initial:
            chunks.append(
                f'<circle id="fw-state-initial-{identifier}" '
                f'cx="{format_svg_number(x - 6)}" '
                f'cy="{format_svg_number(y + 8)}" r="3" fill="#000"/>'
            )
        chunks.append("</g>")
    chunks.append("</g></svg>")
    return "".join(chunks).encode("utf-8")


def _sequence_svg(lane: FirmwareLane) -> bytes:
    steps = tuple(sorted(lane.sequence_steps, key=lambda step: step.step_index))
    if not steps:
        raise SvgVisualProjectionError(
            "firmware sequence projection requires declared sequence steps"
        )
    lifeline_ids = sorted(
        {lane.module.node_id}
        | {step.target for step in steps}
    )
    if any(step.actor not in lifeline_ids for step in steps):
        raise SvgVisualProjectionError(
            "firmware sequence actor must be the module or a declared target"
        )
    positions = {
        node_id: (25.0 + index * 65.0, 25.0)
        for index, node_id in enumerate(lifeline_ids)
    }
    height = max(80.0, 55.0 + len(steps) * 24.0)
    font_size = view_box_font_size(_DIAGRAM_VIEW_BOX_WIDTH, ratio=DIAGRAM_FONT_SIZE_RATIO)
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="240mm" '
        f'height="{format_svg_number(height)}mm" '
        f'viewBox="0 0 240 {format_svg_number(height)}">',
        '<g id="firmware-sequence-view">',
    ]
    for node_id in lifeline_ids:
        identifier = slugify_identifier(node_id)
        x, y = positions[node_id]
        chunks.extend(
            [
                f'<g id="fw-lifeline-{identifier}" '
                f'data-node-id="{escape_xml(node_id)}">',
                f'<text id="fw-lifeline-label-{identifier}" '
                f'x="{format_svg_number(x)}" y="{format_svg_number(y)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(node_id)}</text>",
                f'<line id="fw-lifeline-line-{identifier}" '
                f'x1="{format_svg_number(x + 12)}" '
                f'y1="{format_svg_number(y + 5)}" '
                f'x2="{format_svg_number(x + 12)}" '
                f'y2="{format_svg_number(height - 12)}" stroke="#888"/>',
                "</g>",
            ]
        )
    for step in steps:
        actor_x, _ = positions[step.actor]
        target_x, _ = positions[step.target]
        identifier = f"{step.step_index:03d}-{slugify_identifier(step.node_id)}"
        y = 45.0 + (step.step_index - 1) * 24.0
        chunks.extend(
            [
                f'<line id="fw-sequence-step-{identifier}" '
                f'data-node-id="{escape_xml(step.node_id)}" '
                f'data-step-index="{step.step_index}" '
                f'data-actor="{escape_xml(step.actor)}" '
                f'data-target="{escape_xml(step.target)}" '
                f'data-action="{escape_xml(step.action)}" '
                f'x1="{format_svg_number(actor_x + 12)}" '
                f'y1="{format_svg_number(y)}" '
                f'x2="{format_svg_number(target_x + 12)}" '
                f'y2="{format_svg_number(y)}" stroke="#555"/>',
                f'<text id="fw-sequence-action-{identifier}" '
                f'x="{format_svg_number(min(actor_x, target_x) + 16)}" '
                f'y="{format_svg_number(y - 3)}" '
                f'font-size="{format_svg_number(font_size)}">'
                f"{escape_xml(step.action)}</text>",
            ]
        )
    chunks.append("</g></svg>")
    return "".join(chunks).encode("utf-8")


class SvgFirmwareRenderer:
    """Render firmware SVGs without external tools."""

    renderer_type: ClassVar[Literal["acd-svg"]] = "acd-svg"
    tool_name: ClassVar[Literal["acd-svg"]] = "acd-svg"

    def __init__(self, *, tool_version: str = ACD_SVG_RENDERER_VERSION) -> None:
        if not tool_version or tool_version == "unknown":
            raise SvgVisualProjectionError("renderer version is unknown")
        self.tool_version = tool_version

    def _write_svg(
        self,
        *,
        projection_type: FirmwareProjectionType,
        lane: FirmwareLane,
        output_path: Path,
    ) -> None:
        content = (
            _state_svg(lane)
            if projection_type == "firmware_state_view"
            else _sequence_svg(lane)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(content)
        except OSError as exc:
            raise SvgVisualProjectionError(
                f"firmware SVG could not be written: {output_path}"
            ) from exc

    def render(
        self,
        *,
        projection_id: str,
        projection_type: FirmwareProjectionType,
        source_revision: str,
        lane: FirmwareLane,
        input_files: list[VisualProjectionInput],
        output_path: Path,
        base_dir: Path,
    ) -> VisualProjectionRecord:
        if projection_type not in {
            "firmware_state_view",
            "firmware_sequence_view",
        }:
            raise SvgVisualProjectionError("unsupported firmware projection type")
        return render_svg_projection(
            projection_id=projection_id,
            projection_type=projection_type,
            domain="firmware",
            source_revision=source_revision,
            input_files=input_files,
            output_path=output_path,
            base_dir=base_dir,
            tool_version=self.tool_version,
            write_svg=lambda path: self._write_svg(
                projection_type=projection_type,
                lane=lane,
                output_path=path,
            ),
        )


def generate_firmware_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    lane: FirmwareLane,
    authoritative_inputs: tuple[Path, ...],
    input_base_dir: Path,
    renderer: SvgFirmwareRenderer | None = None,
    projection_ids: tuple[str, str] | None = None,
) -> VisualProjectionSet:
    """Generate the firmware state and sequence projection collection."""
    inputs = input_records(authoritative_inputs, input_base_dir)
    renderer = renderer or SvgFirmwareRenderer()
    ids = projection_ids or (
        f"{slugify_identifier(project_name)}-firmware-state",
        f"{slugify_identifier(project_name)}-firmware-sequence",
    )
    if len(ids) != 2:
        raise SvgVisualProjectionError(
            "firmware projection identifiers are incomplete"
        )
    records = [
        renderer.render(
            projection_id=ids[0],
            projection_type="firmware_state_view",
            source_revision=source_revision,
            lane=lane,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[0]}.svg",
            base_dir=out_dir,
        ),
        renderer.render(
            projection_id=ids[1],
            projection_type="firmware_sequence_view",
            source_revision=source_revision,
            lane=lane,
            input_files=inputs,
            output_path=out_dir / "visual" / f"{ids[1]}.svg",
            base_dir=out_dir,
        ),
    ]
    if len({record.projection_id for record in records}) != len(records):
        raise SvgVisualProjectionError(
            "firmware projection identifiers must be unique"
        )
    records.sort(key=lambda record: record.projection_id)
    result = VisualProjectionSet(
        source_revision=source_revision,
        projections=records,
    ).with_computed_hashes()
    (out_dir / "visual-projections-firmware.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return result
