"""Deterministic SVG writers for firmware state and sequence observations."""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, Literal

from acd.adapters.svg.common import (
    ACD_SVG_RENDERER_VERSION,
    COLOR_EDGE,
    COLOR_EDGE_MUTED,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    DIAGRAM_REFERENCE_WIDTH,
    KIND_FILL,
    KIND_STROKE,
    SMALL_FONT_SCALE,
    SvgVisualProjectionError,
    arrow_marker_defs,
    diagram_font_size,
    escape_xml,
    footer_height,
    format_svg_number,
    header_height,
    input_records,
    legend,
    render_svg_projection,
    slugify_identifier,
    svg_document,
    svg_text,
    text_advance,
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

# Firmware projections use the shared 240-unit reference width and grow when
# labels need more room.
_DIAGRAM_VIEW_BOX_WIDTH = DIAGRAM_REFERENCE_WIDTH

# Grouped fill/stroke for state boxes (firmware.module lane colour).
_STATE_FILL = KIND_FILL["firmware.module"]
_STATE_STROKE = KIND_STROKE["firmware.module"]
_LIFELINE_FILL = KIND_FILL["electrical.component"]
_LIFELINE_STROKE = KIND_STROKE["electrical.component"]


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
    initial_states = [state for state in states if state.initial]
    if len(initial_states) != 1 or initial_states[0].node_id != lane.module.entry_state:
        raise SvgVisualProjectionError(
            "firmware state projection requires exactly one declared initial state "
            "matching the module entry state"
        )
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    box_height = font_size * 4.2
    longest = max(
        max(
            text_advance(state.state_name, font_size, bold=True),
            text_advance(state.node_id, small),
        )
        for state in states
    )
    box_width = longest + font_size * 1.6
    columns = len(states) if len(states) <= 4 else 3
    gap_x = font_size * 4
    gap_y = font_size * 4
    row_pitch = box_height + gap_y
    # Vertical channels above each row keep transition runs out of the boxes.
    channels_per_gap = max(1, int((gap_y - font_size * 1.2) // (font_size * 0.9)))
    origin_x = margin + font_size * 2
    origin_y = header_height(font_size) + font_size * 7.5
    positions: dict[str, tuple[float, float, int]] = {}
    for index, state in enumerate(states):
        column = index % columns
        row = index // columns
        positions[state.node_id] = (
            origin_x + column * (box_width + gap_x),
            origin_y + row * row_pitch,
            row,
        )
    rows = math.ceil(len(states) / columns)
    # One channel slot per transition, assigned in declaration order.
    channel_slot = {transition.node_id: index for index, transition in enumerate(transitions)}

    body = [arrow_marker_defs(font_size), '<g id="firmware-state-view">']
    body += legend(
        [
            ("initial state", COLOR_TEXT, COLOR_TEXT),
            ("state", _STATE_FILL, _STATE_STROKE),
            ("transition", "none", COLOR_EDGE),
        ],
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="state-view-legend",
    )
    # Transitions route orthogonally through the staggered channel above the
    # source row so that horizontal runs never cross a state box.
    body.append('<g id="state-transitions">')
    for transition in transitions:
        identifier = slugify_identifier(transition.node_id)
        from_x, from_y, _row = positions[transition.from_state]
        to_x, to_y, _ = positions[transition.to_state]
        from_cx = from_x + box_width / 2
        to_cx = to_x + box_width / 2
        slot = channel_slot[transition.node_id] % channels_per_gap
        if transition.from_state == transition.to_state:
            loop_height = font_size * (2.0 + slot * 0.9)
            top_y = from_y - loop_height
            path_d = (
                f"M {format_svg_number(from_cx)} {format_svg_number(from_y)} "
                f"V {format_svg_number(top_y)} "
                f"H {format_svg_number(from_x + box_width * 0.9)} "
                f"V {format_svg_number(from_y)}"
            )
            label_x = (from_cx + from_x + box_width * 0.9) / 2
            label_y = top_y - small * 0.4
        else:
            channel_y = from_y - font_size * (1.2 + slot * 0.9)
            end_y = to_y if channel_y <= to_y else to_y + box_height
            path_d = (
                f"M {format_svg_number(from_cx)} {format_svg_number(from_y)} "
                f"V {format_svg_number(channel_y)} "
                f"H {format_svg_number(to_cx)} "
                f"V {format_svg_number(end_y)}"
            )
            label_x = (from_cx + to_cx) / 2
            label_y = channel_y - small * 0.4
        label_width = text_advance(transition.trigger, small) + small
        body.extend(
            [
                f'<path id="fw-transition-{identifier}" '
                f'data-node-id="{escape_xml(transition.node_id)}" '
                f'data-from-state="{escape_xml(transition.from_state)}" '
                f'data-to-state="{escape_xml(transition.to_state)}" '
                f'data-trigger="{escape_xml(transition.trigger)}" '
                f'd="{path_d}" fill="none" stroke="{COLOR_EDGE}" '
                f'stroke-width="{format_svg_number(font_size * 0.15)}" '
                'marker-end="url(#arrow)"/>',
                f'<rect x="{format_svg_number(label_x - label_width / 2)}" '
                f'y="{format_svg_number(label_y - small)}" '
                f'width="{format_svg_number(label_width)}" '
                f'height="{format_svg_number(small * 1.3)}" '
                'fill="#ffffff" stroke="none"/>',
                svg_text(
                    transition.trigger,
                    x=label_x,
                    y=label_y,
                    font_size=small,
                    element_id=f"fw-transition-trigger-{identifier}",
                    anchor="middle",
                    fill=COLOR_TEXT_MUTED,
                ),
            ]
        )
    body.append("</g>")
    for state in states:
        identifier = slugify_identifier(state.node_id)
        x, y, _ = positions[state.node_id]
        body.extend(
            [
                f'<g id="fw-state-{identifier}" '
                f'data-node-id="{escape_xml(state.node_id)}" '
                f'data-state-name="{escape_xml(state.state_name)}" '
                f'data-initial="{str(state.initial).lower()}">',
                f'<rect id="fw-state-box-{identifier}" '
                f'x="{format_svg_number(x)}" y="{format_svg_number(y)}" '
                f'width="{format_svg_number(box_width)}" '
                f'height="{format_svg_number(box_height)}" '
                f'rx="{format_svg_number(font_size * 0.4)}" '
                f'fill="{_STATE_FILL}" stroke="{_STATE_STROKE}" '
                f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                svg_text(
                    state.state_name,
                    x=x + font_size * 0.7,
                    y=y + font_size * 1.7,
                    font_size=font_size,
                    element_id=f"fw-state-label-{identifier}",
                    weight="bold",
                ),
                svg_text(
                    state.node_id,
                    x=x + font_size * 0.7,
                    y=y + font_size * 3.4,
                    font_size=small,
                    fill=COLOR_TEXT_MUTED,
                ),
            ]
        )
        if state.initial:
            marker_x = x - font_size * 1.1
            marker_y = y + box_height / 2
            body.append(
                f'<g id="fw-state-initial-{identifier}">'
                f'<circle cx="{format_svg_number(marker_x)}" '
                f'cy="{format_svg_number(marker_y)}" '
                f'r="{format_svg_number(font_size * 0.45)}" fill="{COLOR_TEXT}"/>'
                f'<line x1="{format_svg_number(marker_x + font_size * 0.45)}" '
                f'y1="{format_svg_number(marker_y)}" '
                f'x2="{format_svg_number(x)}" '
                f'y2="{format_svg_number(marker_y)}" '
                f'stroke="{COLOR_TEXT}" '
                f'stroke-width="{format_svg_number(font_size * 0.15)}" '
                'marker-end="url(#arrow)"/>'
                + svg_text(
                    "initial",
                    x=marker_x,
                    y=marker_y + small * 1.4,
                    font_size=small,
                    anchor="middle",
                    fill=COLOR_TEXT_MUTED,
                )
                + "</g>"
            )
        body.append("</g>")
    body.append("</g>")
    width = max(
        _DIAGRAM_VIEW_BOX_WIDTH,
        origin_x + columns * box_width + (columns - 1) * gap_x + margin + font_size * 4,
    )
    height = origin_y + rows * row_pitch + font_size * 2 + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=f"Firmware state machine — {lane.module.module_name}",
        subtitle=(
            f"module {lane.module.node_id} - entry state "
            f"{lane.module.entry_state}"
        ),
        body=body,
        font_size=font_size,
    )


def _sequence_svg(lane: FirmwareLane) -> bytes:
    steps = tuple(sorted(lane.sequence_steps, key=lambda step: step.step_index))
    if not steps:
        raise SvgVisualProjectionError(
            "firmware sequence projection requires declared sequence steps"
        )
    targets: list[str] = []
    for step in steps:
        if step.target not in targets:
            targets.append(step.target)
    lifeline_ids = [lane.module.node_id, *targets]
    if any(step.actor not in lifeline_ids for step in steps):
        raise SvgVisualProjectionError(
            "firmware sequence actor must be the module or a declared target"
        )
    font_size = diagram_font_size()
    small = font_size * SMALL_FONT_SCALE
    margin = font_size * 2
    badge_width = font_size * 4
    longest_label = max(
        [text_advance(lane.module.module_name, font_size, bold=True)]
        + [
            text_advance(node_id, font_size, bold=True)
            for node_id in lifeline_ids
        ]
        + [text_advance(step.action, font_size) for step in steps]
    )
    column_width = longest_label + font_size * 3
    origin_x = margin + badge_width + font_size * 2
    lifeline_y = header_height(font_size) + font_size * 4.5
    lifeline_box_height = font_size * 4.2
    positions = {
        node_id: origin_x + index * column_width + column_width / 2
        for index, node_id in enumerate(lifeline_ids)
    }
    step_pitch = font_size * 4.6
    steps_top = lifeline_y + lifeline_box_height + font_size * 3
    lifeline_bottom = steps_top + len(steps) * step_pitch

    body = [arrow_marker_defs(font_size), '<g id="firmware-sequence-view">']
    body += legend(
        [
            ("lifeline", _LIFELINE_FILL, _LIFELINE_STROKE),
            ("message", "none", COLOR_EDGE),
            ("step number", "#ffffff", COLOR_EDGE),
        ],
        x=margin,
        y=header_height(font_size) + font_size * 1.2,
        font_size=small,
        element_id="sequence-view-legend",
    )
    for index, node_id in enumerate(lifeline_ids):
        identifier = slugify_identifier(node_id)
        cx = positions[node_id]
        is_module = index == 0
        primary = lane.module.module_name if is_module else node_id
        body.extend(
            [
                f'<g id="fw-lifeline-{identifier}" '
                f'data-node-id="{escape_xml(node_id)}">',
                f'<rect x="{format_svg_number(cx - column_width / 2 + font_size)}" '
                f'y="{format_svg_number(lifeline_y)}" '
                f'width="{format_svg_number(column_width - font_size * 2)}" '
                f'height="{format_svg_number(lifeline_box_height)}" '
                f'rx="{format_svg_number(font_size * 0.4)}" '
                f'fill="{_LIFELINE_FILL}" stroke="{_LIFELINE_STROKE}" '
                f'stroke-width="{format_svg_number(font_size * 0.18)}"/>',
                svg_text(
                    primary,
                    x=cx,
                    y=lifeline_y + font_size * 1.7,
                    font_size=font_size,
                    element_id=f"fw-lifeline-label-{identifier}",
                    anchor="middle",
                    weight="bold",
                ),
            ]
        )
        if is_module:
            body.append(
                svg_text(
                    node_id,
                    x=cx,
                    y=lifeline_y + font_size * 3.4,
                    font_size=small,
                    element_id=f"fw-lifeline-sub-{identifier}",
                    anchor="middle",
                    fill=COLOR_TEXT_MUTED,
                )
            )
        body.extend(
            [
                f'<line id="fw-lifeline-line-{identifier}" '
                f'x1="{format_svg_number(cx)}" '
                f'y1="{format_svg_number(lifeline_y + lifeline_box_height)}" '
                f'x2="{format_svg_number(cx)}" '
                f'y2="{format_svg_number(lifeline_bottom)}" '
                f'stroke="{COLOR_EDGE_MUTED}" '
                f'stroke-width="{format_svg_number(font_size * 0.12)}" '
                f'stroke-dasharray="{format_svg_number(font_size * 0.8)} '
                f'{format_svg_number(font_size * 0.5)}"/>',
                "</g>",
            ]
        )
    badge_x = margin + badge_width / 2
    for step in steps:
        actor_x = positions[step.actor]
        target_x = positions[step.target]
        identifier = f"{step.step_index:03d}-{slugify_identifier(step.node_id)}"
        y = steps_top + (step.step_index - 1) * step_pitch + font_size * 2
        loop_width = font_size * 4
        body.append(
            f'<g id="fw-sequence-step-{identifier}" '
            f'data-node-id="{escape_xml(step.node_id)}" '
            f'data-step-index="{step.step_index}" '
            f'data-actor="{escape_xml(step.actor)}" '
            f'data-target="{escape_xml(step.target)}" '
            f'data-action="{escape_xml(step.action)}">'
        )
        if step.actor == step.target:
            path_d = (
                f"M {format_svg_number(actor_x)} {format_svg_number(y)} "
                f"h {format_svg_number(loop_width)} "
                f"v {format_svg_number(font_size * 1.4)} "
                f"h {format_svg_number(-loop_width + font_size * 1.2)}"
            )
            label_x = actor_x + loop_width / 2
            label_y = y - font_size * 0.7
        else:
            path_d = (
                f"M {format_svg_number(actor_x)} {format_svg_number(y)} "
                f"H {format_svg_number(target_x)}"
            )
            label_x = (actor_x + target_x) / 2
            label_y = y - font_size * 0.7
        body.extend(
            [
                f'<path d="{path_d}" fill="none" stroke="{COLOR_EDGE}" '
                f'stroke-width="{format_svg_number(font_size * 0.16)}" '
                'marker-end="url(#arrow)"/>',
                svg_text(
                    step.action,
                    x=label_x,
                    y=label_y,
                    font_size=font_size,
                    element_id=f"fw-sequence-action-{identifier}",
                    anchor="middle",
                ),
                "</g>",
                f'<g id="fw-seqnum-{step.step_index:03d}">'
                f'<circle cx="{format_svg_number(badge_x)}" '
                f'cy="{format_svg_number(y)}" '
                f'r="{format_svg_number(font_size * 0.9)}" '
                f'fill="#ffffff" stroke="{COLOR_EDGE}" '
                f'stroke-width="{format_svg_number(font_size * 0.14)}"/>'
                + svg_text(
                    str(step.step_index),
                    x=badge_x,
                    y=y + font_size * 0.35,
                    font_size=font_size,
                    anchor="middle",
                )
                + "</g>",
            ]
        )
    body.append("</g>")
    width = max(
        _DIAGRAM_VIEW_BOX_WIDTH,
        origin_x + len(lifeline_ids) * column_width + margin,
    )
    height = lifeline_bottom + font_size * 2 + footer_height(font_size)
    return svg_document(
        width=width,
        height=height,
        title=f"Firmware sequence — {lane.module.module_name}",
        subtitle=(
            f"module {lane.module.node_id} - {len(steps)} steps, "
            f"{len(lifeline_ids)} lifelines"
        ),
        body=body,
        font_size=font_size,
    )


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
