"""Visual projection stages (electrical, layout, system, firmware, theme song)."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Literal, cast

from acd.adapters.kicad.cli import RuleCheckResult
from acd.adapters.svg import (
    generate_firmware_visual_projections,
    generate_layout_visual_projections,
    generate_system_visual_projections,
)
from acd.core.electrical.board_model import BoardModel
from acd.core.electrical.electrical import ElectricalLane
from acd.core.firmware.firmware_lane import extract_firmware_lane
from acd.core.knowledge.design_predicates import PredicateResult
from acd.core.mechanical.mechanical import placement_annotations
from acd.core.runtime.parallel import run_ordered_stages
from acd.pipeline.repository import repository_root
from acd.pipeline.theme_song import generate_theme_song_projection
from acd.pipeline.visual_projection import (
    crosscheck_electrical_visual_projections,
    crosscheck_firmware_visual_projections,
    generate_electrical_visual_projections,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.theme_song import ThemeSongProjection
from acd.schema.visual_crosscheck import VisualCrosscheckReport
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    ElectricalVisualProjectionPredicate,
    VisualProjectionSet,
)


def visual_silkscreen_status(
    value: object,
) -> Literal["measured_pass", "fail"]:
    if value == "measured_pass":
        return "measured_pass"
    if value == "fail":
        return "fail"
    raise ValueError("silkscreen status is invalid for visual projection")


def visual_dfm_status(value: object) -> Literal["pass", "fail"]:
    if value == "pass":
        return "pass"
    if value == "fail":
        return "fail"
    raise ValueError("DFM status is invalid for visual projection")


def stage_electrical_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    schematic: Path,
    routed_board: Path,
    lane: ElectricalLane,
    board: BoardModel,
    gates: ElectricalVisualProjectionGates,
) -> tuple[VisualProjectionSet, VisualCrosscheckReport]:
    visual_projection_set = generate_electrical_visual_projections(
        project_name=project_name,
        out_dir=out_dir,
        source_revision=source_revision,
        schematic=schematic,
        routed_board=routed_board,
        lane=lane,
        board=board,
        gates=gates,
    )
    visual_crosscheck = crosscheck_electrical_visual_projections(
        project_name=project_name,
        source_revision=source_revision,
        visual_projection_set=visual_projection_set,
        lane=lane,
        board=board,
        base_dir=out_dir,
        machine_inputs=(schematic, routed_board),
    )
    return visual_projection_set, visual_crosscheck


def stage_firmware_visual_projections(
    *,
    project_name: str,
    out_dir: Path,
    source_revision: str,
    graph: DesignGraph,
    lane: ElectricalLane,
    graph_input: Path,
    input_base_dir: Path,
) -> tuple[VisualProjectionSet, VisualCrosscheckReport]:
    firmware_lane = extract_firmware_lane(graph)
    target_captions: dict[str, str] = {}
    for step in firmware_lane.sequence_steps:
        try:
            component = lane.component_by_id(step.target)
        except KeyError:
            continue
        target_captions[step.target] = f"{component.refdes} {component.value}".strip()
    projection_ids = (f"{project_name}-firmware-state", f"{project_name}-firmware-sequence")
    firmware_projection_set = generate_firmware_visual_projections(
        project_name=project_name,
        out_dir=out_dir,
        source_revision=source_revision,
        lane=firmware_lane,
        authoritative_inputs=(graph_input,),
        input_base_dir=input_base_dir,
        projection_ids=projection_ids,
        target_captions=target_captions,
    )
    firmware_crosscheck = crosscheck_firmware_visual_projections(
        source_revision=source_revision,
        visual_projection_set=firmware_projection_set,
        lane=firmware_lane,
        graph_input=graph_input,
        base_dir=out_dir,
        input_base_dir=input_base_dir,
        projection_ids=projection_ids,
    )
    return firmware_projection_set, firmware_crosscheck


def build_electrical_visual_gates(
    *,
    erc: RuleCheckResult,
    drc: RuleCheckResult,
    route_convergence_state: str,
    silkscreen_status: object,
    dfm_status: object,
    design_predicates: tuple[PredicateResult, ...],
) -> ElectricalVisualProjectionGates:
    return ElectricalVisualProjectionGates(
        erc_errors=erc.error_count,
        erc_unconnected=len(erc.unconnected_items),
        routing_converged=route_convergence_state == "converged",
        drc_errors=drc.error_count,
        drc_unconnected=len(drc.unconnected_items),
        independent_reload=True,
        silkscreen_status=visual_silkscreen_status(silkscreen_status),
        dfm_status=visual_dfm_status(dfm_status),
        design_predicates=tuple(
            ElectricalVisualProjectionPredicate.model_validate(
                predicate.model_dump(
                    mode="json",
                    include={"name", "status", "detail"},
                )
            )
            for predicate in design_predicates
            if predicate.status != "not_applicable"
        ),
    )


def run_visual_projection_stages(
    *,
    project_name: str,
    out_dir: Path,
    fixture_dir: Path,
    source_revision: str,
    graph: DesignGraph,
    lane: ElectricalLane,
    schematic: Path,
    routed_path: Path,
    board: BoardModel,
    gates: ElectricalVisualProjectionGates,
    pipeline_workers: int,
) -> tuple[Path, ThemeSongProjection]:
    """Run the independent visual projection stages and fail closed on crosscheck mismatch."""
    visual_stage_results = run_ordered_stages(
        (
            (
                "electrical-visual-projections",
                partial(
                    stage_electrical_visual_projections,
                    project_name=project_name,
                    out_dir=out_dir,
                    source_revision=source_revision,
                    schematic=schematic,
                    routed_board=routed_path,
                    lane=lane,
                    board=board,
                    gates=gates,
                ),
            ),
            (
                "layout-visual-projections",
                partial(
                    generate_layout_visual_projections,
                    project_name=project_name,
                    out_dir=out_dir,
                    source_revision=source_revision,
                    board=board,
                    board_view=lane.board,
                    annotations=placement_annotations(graph),
                    authoritative_inputs=(fixture_dir / "graph.json",),
                    input_base_dir=repository_root(),
                ),
            ),
            (
                "system-visual-projections",
                partial(
                    generate_system_visual_projections,
                    project_name=project_name,
                    out_dir=out_dir,
                    source_revision=source_revision,
                    graph=graph,
                    lane=lane,
                    authoritative_inputs=(fixture_dir / "graph.json",),
                    input_base_dir=repository_root(),
                ),
            ),
            (
                "firmware-visual-projections",
                partial(
                    stage_firmware_visual_projections,
                    project_name=project_name,
                    out_dir=out_dir,
                    source_revision=source_revision,
                    graph=graph,
                    lane=lane,
                    graph_input=fixture_dir / "graph.json",
                    input_base_dir=repository_root(),
                ),
            ),
            (
                "theme-song-projection",
                partial(
                    generate_theme_song_projection,
                    project_name=project_name,
                    repository=repository_root(),
                    graph_path=fixture_dir / "graph.json",
                    out_dir=out_dir,
                    source_revision=source_revision,
                ),
            ),
        ),
        pipeline_workers,
    )
    _visual_projection_set, visual_crosscheck = cast(
        tuple[VisualProjectionSet, VisualCrosscheckReport],
        visual_stage_results[0],
    )
    layout_projection_set = cast(VisualProjectionSet, visual_stage_results[1])
    system_projection_set = cast(VisualProjectionSet, visual_stage_results[2])
    firmware_projection_set, firmware_crosscheck = cast(
        tuple[VisualProjectionSet, VisualCrosscheckReport],
        visual_stage_results[3],
    )
    theme_song_projection_path, theme_song_projection = cast(
        tuple[Path, ThemeSongProjection],
        visual_stage_results[4],
    )
    print(
        "[10/12] electrical visual projections recorded: "
        f"{out_dir / 'visual-projections-electrical.json'}"
    )
    if visual_crosscheck.status != "match":
        raise RuntimeError("electrical visual cross-check did not match (fail-closed)")
    print(
        "[10/12] electrical visual cross-check recorded: "
        f"{out_dir / 'visual-crosscheck-electrical.json'}"
    )
    print(
        "[10/12] layout visual projections recorded: "
        f"{out_dir / 'visual-projections-layout.json'} "
        f"(identity_hash={layout_projection_set.identity_hash}; "
        f"canonical_hash={layout_projection_set.canonical_hash})"
    )
    print(
        "[10/12] system visual projections recorded: "
        f"{out_dir / 'visual-projections-system.json'} "
        f"(identity_hash={system_projection_set.identity_hash}; "
        f"canonical_hash={system_projection_set.canonical_hash})"
    )
    print(
        "[11/12] firmware visual projections recorded: "
        f"{out_dir / 'visual-projections-firmware.json'} "
        f"(identity_hash={firmware_projection_set.identity_hash}; "
        f"canonical_hash={firmware_projection_set.canonical_hash})"
    )
    if firmware_crosscheck.status != "match":
        raise RuntimeError("firmware visual cross-check did not match (fail-closed)")
    print(
        "[11/12] firmware visual cross-check recorded: "
        f"{out_dir / 'visual-crosscheck-firmware.json'} "
        f"(identity_hash={firmware_crosscheck.identity_hash}; "
        f"canonical_hash={firmware_crosscheck.canonical_hash})"
    )
    print(
        f"[11/12] theme song projection recorded: {theme_song_projection_path} "
        f"({theme_song_projection.key}, {theme_song_projection.bpm} bpm; "
        f"canonical_hash={theme_song_projection.canonical_hash})"
    )
    return theme_song_projection_path, theme_song_projection
