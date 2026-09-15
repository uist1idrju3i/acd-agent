"""Firmware visual projection crosscheck."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from acd.adapters.svg.common import (
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
)
from acd.core.fileio import read_json
from acd.core.firmware_lane import FirmwareLane
from acd.core.process import sha256_bytes
from acd.pipeline.visual_projection._common import (
    crosscheck_item,
    decimal_value,
    machine_input,
    node_id_fragment,
    status_for_items,
    svg_dimension,
    svg_root_geometry,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.visual_crosscheck import (
    VisualCrosscheckReport,
    VisualProjectionCrosscheck,
    VisualReviewChecklistItem,
)
from acd.schema.visual_projection import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
)


def _firmware_svg_elements(svg: bytes) -> tuple[ElementTree.Element, str, str, tuple[str, ...]]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck firmware SVG could not be parsed") from exc
    width, height, view_box = svg_root_geometry(svg)
    return root, width, height, view_box


def _firmware_projection_crosscheck(
    *,
    projection: VisualProjectionRecord,
    lane: FirmwareLane,
    base_dir: Path,
    expected_input: VisualProjectionInput,
) -> VisualProjectionCrosscheck:
    path = (base_dir / projection.image_path).resolve()
    try:
        path.relative_to(base_dir.resolve())
        svg = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("visual crosscheck firmware SVG could not be read") from exc
    root, width, height, view_box = _firmware_svg_elements(svg)
    width_value, width_unit = svg_dimension(width, "width")
    height_value, height_unit = svg_dimension(height, "height")
    view_box_numbers = tuple(decimal_value(value, "viewBox") for value in view_box)
    items = [
        crosscheck_item(
            check_id="svg-units",
            description="Firmware SVG root dimensions use millimeter units",
            expected="width=mm; height=mm",
            actual=f"width={width_unit}; height={height_unit}",
            machine_field="SVG.root.width/height",
            status="match" if width_unit == "mm" and height_unit == "mm" else "mismatch",
        ),
        crosscheck_item(
            check_id="svg-viewbox",
            description="Firmware SVG viewBox dimensions match the root dimensions",
            expected=f"{width_value} {height_value}",
            actual=f"{view_box[2]} {view_box[3]}",
            machine_field="SVG.root.width/height; SVG.root.viewBox",
            status=(
                "match"
                if view_box_numbers[2:] == (
                    decimal_value(width_value, "width"),
                    decimal_value(height_value, "height"),
                )
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-image-hash",
            description="Firmware SVG raw-byte hash matches the projection record",
            expected=projection.image_hash,
            actual=sha256_bytes(svg),
            machine_field="VisualProjectionRecord.image_hash",
            status=(
                "match"
                if sha256_bytes(svg) == projection.image_hash
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="svg-renderer",
            description="Firmware SVG uses the pinned acd-svg renderer contract",
            expected=(
                f"acd-svg/{ACD_SVG_RENDERER_VERSION}; "
                f"normalization={ACD_SVG_NORMALIZATION_RULE_ID}"
            ),
            actual=(
                f"{projection.renderer.renderer_type}/{projection.renderer.tool_version}; "
                f"normalization={projection.normalization_rule_id}"
            ),
            machine_field=(
                "VisualProjectionRecord.renderer; "
                "VisualProjectionRecord.normalization_rule_id"
            ),
            status=(
                "match"
                if projection.renderer.renderer_type == "acd-svg"
                and projection.renderer.tool_name == "acd-svg"
                and projection.renderer.tool_version == ACD_SVG_RENDERER_VERSION
                and projection.normalization_rule_id == ACD_SVG_NORMALIZATION_RULE_ID
                else "mismatch"
            ),
        ),
        crosscheck_item(
            check_id="input-file",
            description="Firmware projection input path and content hash match the graph input",
            expected=f"{expected_input.path}:{expected_input.content_hash}",
            actual=(
                ",".join(
                    f"{item.path}:{item.content_hash}" for item in projection.input_files
                )
                or "missing"
            ),
            machine_field="VisualProjectionRecord.input_files",
            status=(
                "match"
                if projection.input_files == [expected_input]
                else "mismatch"
            ),
        ),
    ]
    ids = {
        element.attrib["id"]
        for element in root.iter()
        if "id" in element.attrib
    }
    if projection.projection_type == "firmware_state_view":
        expected_state_ids = {
            f"fw-state-{node_id_fragment(state.node_id)}" for state in lane.states
        }
        expected_transition_ids = {
            f"fw-transition-{node_id_fragment(transition.node_id)}"
            for transition in lane.transitions
        }
        actual_state_ids = {
            identifier for identifier in ids if identifier.startswith("fw-state-")
            and not identifier.startswith("fw-state-box-")
            and not identifier.startswith("fw-state-label-")
            and not identifier.startswith("fw-state-initial-")
        }
        actual_transition_ids = {
            identifier for identifier in ids if identifier.startswith("fw-transition-")
            and not identifier.startswith("fw-transition-trigger-")
        }
        initial_ids = {
            identifier for identifier in ids if identifier.startswith("fw-state-initial-")
        }
        transition_elements = {
            element.attrib.get("data-node-id"): element
            for element in root.iter()
            if element.attrib.get("id", "").startswith("fw-transition-")
            and element.attrib.get("data-node-id") is not None
        }
        transition_texts = {
            element.attrib.get("id", ""): "".join(element.itertext())
            for element in root.iter()
            if element.attrib.get("id", "").startswith("fw-transition-trigger-")
        }
        expected_transitions = {
            transition.node_id: transition for transition in lane.transitions
        }
        missing_states = sorted(set(expected_state_ids) - actual_state_ids)
        extra_states = sorted(actual_state_ids - expected_state_ids)
        missing_transitions = sorted(
            set(expected_transition_ids) - actual_transition_ids
        )
        extra_transitions = sorted(
            actual_transition_ids - expected_transition_ids
        )
        transition_mismatches: list[str] = []
        for node_id in sorted(expected_transitions):
            transition = expected_transitions[node_id]
            element = transition_elements.get(node_id)
            if element is None:
                transition_mismatches.append(f"{node_id}:element")
                continue
            observed = {
                "from_state": element.attrib.get("data-from-state"),
                "to_state": element.attrib.get("data-to-state"),
                "trigger": element.attrib.get("data-trigger"),
                "text": transition_texts.get(
                    f"fw-transition-trigger-{node_id_fragment(node_id)}",
                    "",
                ),
            }
            expected = {
                "from_state": transition.from_state,
                "to_state": transition.to_state,
                "trigger": transition.trigger,
                "text": transition.trigger,
            }
            transition_mismatches.extend(
                f"{node_id}:{field}"
                for field in ("from_state", "to_state", "trigger", "text")
                if (
                    observed[field] != expected[field]
                    if field != "text"
                    else expected[field] not in str(observed[field])
                )
            )
        transition_payload_match = not transition_mismatches
        items.extend(
            [
                crosscheck_item(
                    check_id="state-coverage",
                    description="Every declared firmware state has one deterministic SVG element",
                    expected=",".join(sorted(expected_state_ids)),
                    actual=",".join(sorted(actual_state_ids)) or "none",
                    machine_field="FirmwareLane.states[*].node_id",
                    status=(
                        "match"
                        if not missing_states and not extra_states
                        else "mismatch"
                    ),
                ),
                crosscheck_item(
                    check_id="transition-coverage",
                    description=(
                        "Every declared firmware transition has one "
                        "deterministic SVG element"
                    ),
                    expected=",".join(sorted(expected_transition_ids)),
                    actual=",".join(sorted(actual_transition_ids)) or "none",
                    machine_field="FirmwareLane.transitions[*].node_id",
                    status=(
                        "match"
                        if not missing_transitions and not extra_transitions
                        else "mismatch"
                    ),
                ),
                crosscheck_item(
                    check_id="transition-declarations",
                    description="Transition endpoints and trigger text match declarations",
                    expected="all declared transition payloads",
                    actual=(
                        "match"
                        if transition_payload_match
                        else ",".join(transition_mismatches)
                    ),
                    machine_field="FirmwareLane.transitions[*]",
                    status="match" if transition_payload_match else "mismatch",
                ),
                crosscheck_item(
                    check_id="initial-state",
                    description="Exactly one declared initial state is visibly distinguished",
                    expected=f"fw-state-initial-{node_id_fragment(lane.module.entry_state)}",
                    actual=",".join(sorted(initial_ids)) or "none",
                    machine_field="FirmwareLane.states[*].initial; FirmwareLane.module.entry_state",
                    status=(
                        "match"
                        if initial_ids
                        == {
                            f"fw-state-initial-{node_id_fragment(lane.module.entry_state)}"
                        }
                        else "mismatch"
                    ),
                ),
            ]
        )
    else:
        expected_lifelines = {
            lane.module.node_id,
            *(step.target for step in lane.sequence_steps),
        }
        actual_lifelines = {
            element.attrib["data-node-id"]
            for element in root.iter()
            if element.attrib.get("id", "").startswith("fw-lifeline-")
            and element.attrib.get("data-node-id") is not None
        }
        expected_steps = {
            step.step_index: step for step in lane.sequence_steps
        }
        actual_steps = {
            int(element.attrib["data-step-index"]): element
            for element in root.iter()
            if element.attrib.get("id", "").startswith("fw-sequence-step-")
            and element.attrib.get("data-step-index", "").isdigit()
        }
        sequence_texts = {
            element.attrib.get("id", ""): "".join(element.itertext())
            for element in root.iter()
            if element.attrib.get("id", "").startswith("fw-sequence-action-")
        }
        sequence_mismatches: list[str] = []
        for index in sorted(expected_steps):
            step = expected_steps[index]
            element = actual_steps.get(index)
            if element is None:
                sequence_mismatches.append(
                    f"{step.node_id}[{index}]:element"
                )
                continue
            observed = {
                "node_id": element.attrib.get("data-node-id"),
                "step_index": element.attrib.get("data-step-index"),
                "actor": element.attrib.get("data-actor"),
                "target": element.attrib.get("data-target"),
                "action": element.attrib.get("data-action"),
                "text": sequence_texts.get(
                    f"fw-sequence-action-{index:03d}-"
                    f"{node_id_fragment(step.node_id)}",
                    "",
                ),
            }
            expected = {
                "node_id": step.node_id,
                "step_index": str(step.step_index),
                "actor": step.actor,
                "target": step.target,
                "action": step.action,
                "text": step.action,
            }
            sequence_mismatches.extend(
                f"{step.node_id}[{index}]:{field}"
                for field in (
                    "node_id",
                    "step_index",
                    "actor",
                    "target",
                    "action",
                    "text",
                )
                if (
                    observed[field] != expected[field]
                    if field != "text"
                    else expected[field] not in str(observed[field])
                )
            )
        sequence_match = not sequence_mismatches
        items.extend(
            [
                crosscheck_item(
                    check_id="lifeline-coverage",
                    description="Firmware module and declared sequence targets have lifelines",
                    expected=",".join(sorted(expected_lifelines)),
                    actual=",".join(sorted(actual_lifelines)) or "none",
                    machine_field=(
                        "FirmwareLane.module.node_id; "
                        "FirmwareLane.sequence_steps[*].target"
                    ),
                    status="match" if actual_lifelines == expected_lifelines else "mismatch",
                ),
                crosscheck_item(
                    check_id="sequence-coverage",
                    description="Every declared sequence step has one deterministic SVG message",
                    expected=",".join(str(index) for index in sorted(expected_steps)),
                    actual=",".join(str(index) for index in sorted(actual_steps)) or "none",
                    machine_field="FirmwareLane.sequence_steps[*].step_index",
                    status=(
                        "match"
                        if set(actual_steps) == set(expected_steps)
                        else "mismatch"
                    ),
                ),
                crosscheck_item(
                    check_id="sequence-declarations",
                    description="Sequence actor, target, index, and action match declarations",
                    expected="all declared sequence payloads",
                    actual=(
                        "match"
                        if sequence_match
                        else ",".join(sequence_mismatches)
                    ),
                    machine_field="FirmwareLane.sequence_steps[*]",
                    status="match" if sequence_match else "mismatch",
                ),
            ]
        )
    return VisualProjectionCrosscheck(
        projection_id=projection.projection_id,
        source_revision=projection.source_revision,
        image_hash=projection.image_hash,
        items=items,
        status=status_for_items(items),
    )


def crosscheck_firmware_visual_projections(
    *,
    source_revision: str,
    visual_projection_set: VisualProjectionSet,
    lane: FirmwareLane,
    graph_input: Path,
    base_dir: Path,
    input_base_dir: Path,
    projection_ids: tuple[str, str],
    output_path: Path | None = None,
) -> VisualCrosscheckReport:
    """Cross-check firmware SVG projections against graph declarations."""
    expected_ids = {identifier for identifier in projection_ids if identifier}
    if len(expected_ids) != 2:
        raise ValueError(
            "firmware crosscheck requires two distinct projection identifiers"
        )
    graph = DesignGraph.model_validate(
        read_json(graph_input)
    )
    graph_pin_assignments: list[tuple[str, int, str]] = []
    for node in graph.nodes:
        if node.kind != "firmware.pin_assignment":
            continue
        gpio = node.attrs.get("gpio")
        net = node.attrs.get("net")
        if isinstance(gpio, bool) or not isinstance(gpio, int):
            raise ValueError(
                f"firmware pin assignment {node.id!r} has invalid gpio"
            )
        if not isinstance(net, str) or not net:
            raise ValueError(
                f"firmware pin assignment {node.id!r} has invalid net"
            )
        graph_pin_assignments.append((node.id, gpio, net))
    expected_graph_pin_assignments = tuple(sorted(graph_pin_assignments))
    lane_pin_assignments = tuple(
        sorted(
            (assignment.node_id, assignment.gpio, assignment.net)
            for assignment in lane.pin_assignments
        )
    )
    if graph.revision != source_revision:
        raise ValueError("firmware crosscheck graph and source revisions do not match")
    if visual_projection_set.source_revision != source_revision:
        raise ValueError("visual crosscheck source revisions do not match")
    if any(
        projection.source_revision != source_revision
        for projection in visual_projection_set.projections
    ):
        raise ValueError("visual crosscheck projection revisions do not match")
    expected_input = machine_input(graph_input, base_dir=input_base_dir)
    expected_types = {"firmware_state_view", "firmware_sequence_view"}
    actual_types = [projection.projection_type for projection in visual_projection_set.projections]
    actual_ids = {projection.projection_id for projection in visual_projection_set.projections}
    coverage_item = crosscheck_item(
        check_id="projection-coverage",
        description="Projection set contains exactly one state and one sequence firmware view",
        expected=(
            "firmware_state_view=1; firmware_sequence_view=1; "
            f"projection_ids={','.join(sorted(expected_ids))}"
        ),
        actual=(
            f"types={','.join(sorted(actual_types)) or 'none'}; "
            f"projection_ids={','.join(sorted(actual_ids)) or 'none'}"
        ),
        machine_field="VisualProjectionSet.projections[*].projection_type/projection_id",
        status=(
            "match"
            if len(visual_projection_set.projections) == 2
            and set(actual_types) == expected_types
            and actual_ids == expected_ids
            else "mismatch"
        ),
    )
    records = [
        _firmware_projection_crosscheck(
            projection=projection,
            lane=lane,
            base_dir=base_dir,
            expected_input=expected_input,
        )
        for projection in visual_projection_set.projections
        if projection.projection_type in expected_types
    ]
    review_items = [
        VisualReviewChecklistItem(
            item_id="review-firmware-readability",
            aspect="readability",
            verification="observation_required",
            status="unknown",
            basis="Firmware SVG readability requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-firmware-annotations",
            aspect="annotations",
            verification="observation_required",
            status="unknown",
            basis="Firmware SVG annotation appropriateness requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-firmware-occlusion",
            aspect="occlusion",
            verification="observation_required",
            status="unknown",
            basis="Firmware SVG overlap or hidden meaning loss requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-firmware-state-intent",
            aspect="design_intent",
            verification="observation_required",
            status="unknown",
            basis="State-transition design-intent fidelity requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-firmware-sequence-intent",
            aspect="design_intent",
            verification="observation_required",
            status="unknown",
            basis="Sequence design-intent fidelity requires visual observation.",
        ),
        VisualReviewChecklistItem(
            item_id="review-firmware-functional-run",
            aspect="functional_run",
            verification="observation_required",
            status="unknown",
            basis="GD1 measured functional-run Evidence is on hold.",
        ),
    ]
    pin_match = lane_pin_assignments == expected_graph_pin_assignments
    pin_item = crosscheck_item(
        check_id="pin-assignments",
        description="Firmware pin assignment GPIO and net declarations remain consistent",
        expected="graph firmware.pin_assignment declarations",
        actual=(
            "match"
            if pin_match
            else (
                f"lane={lane_pin_assignments}; "
                f"graph={expected_graph_pin_assignments}"
            )
        ),
        machine_field=(
            "FirmwareLane.pin_assignments[*].gpio/net; "
            "DesignGraph.firmware.pin_assignment[*].attrs"
        ),
        status="match" if pin_match else "mismatch",
    )
    report = VisualCrosscheckReport(
        source_revision=source_revision,
        visual_projection_set_identity_hash=visual_projection_set.identity_hash,
        machine_input_files=[expected_input],
        set_items=[coverage_item, pin_item],
        crosschecks=sorted(records, key=lambda record: record.projection_id),
        review_items=review_items,
        status=status_for_items(
            [coverage_item, pin_item]
            + [item for record in records for item in record.items]
        ),
        generated_at=datetime.now(UTC),
    ).with_computed_hashes()
    if output_path is None:
        output_path = base_dir / "visual-crosscheck-firmware.json"
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report
