"""Canonical stage and lane declarations for graph-driven design execution.

The design loop owns order-readiness, while the command-line lane runner owns
the silkscreen barrier, design lanes, and pytest subset validation lane.
The pytest subset is declared only for the GD1 artifact prefix; a
design-specific validation lane for arbitrary graphs is not yet available.
Board exploration is a conditional stage that runs only after an eligible
board rejection when explicitly enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.core.naming import artifact_prefix, output_prefix


@dataclass(frozen=True)
class LaneStage:
    """Describe one stage shared by the design loop and lane runner."""

    stage_id: str
    barrier: bool
    output_path: Path | None
    cacheable: bool
    command_kind: str | None
    design_loop: bool
    lane_runner: bool


@dataclass(frozen=True)
class LanePlan:
    """Resolve canonical stage metadata and paths for one graph execution."""

    graph_id: str
    output_prefix: str
    artifact_prefix: str
    stages: tuple[LaneStage, ...]

    @property
    def design_loop_stages(self) -> tuple[LaneStage, ...]:
        return tuple(stage for stage in self.stages if stage.design_loop)

    @property
    def design_loop_stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.design_loop_stages)

    @property
    def design_loop_lanes(self) -> tuple[LaneStage, ...]:
        return tuple(
            stage
            for stage in self.design_loop_stages
            if not stage.barrier and stage.command_kind is not None
        )

    @property
    def design_loop_lane_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.design_loop_lanes)

    @property
    def lane_runner_stages(self) -> tuple[LaneStage, ...]:
        return tuple(stage for stage in self.stages if stage.lane_runner)

    @property
    def lane_runner_stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.lane_runner_stages)

    def stage(self, stage_id: str) -> LaneStage:
        """Return a declared stage by ID."""
        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage
        raise ValueError(f"unknown lane plan stage: {stage_id!r}")


@dataclass(frozen=True)
class _StageDefinition:
    stage_id: str
    output_suffix: str | None
    barrier: bool
    cacheable: bool
    command_kind: str | None
    design_loop: bool
    lane_runner: bool
    gd1_only: bool = False
    conditional: bool = False


_STAGE_DEFINITIONS: tuple[_StageDefinition, ...] = (
    _StageDefinition(
        "fixture-generation",
        None,
        barrier=True,
        cacheable=False,
        command_kind=None,
        design_loop=False,
        lane_runner=False,
        conditional=True,
    ),
    _StageDefinition(
        "requirement-compile",
        None,
        barrier=True,
        cacheable=False,
        command_kind=None,
        design_loop=False,
        lane_runner=False,
        conditional=True,
    ),
    _StageDefinition(
        "requirement-entry-validation",
        None,
        barrier=True,
        cacheable=False,
        command_kind=None,
        design_loop=False,
        lane_runner=False,
        conditional=True,
    ),
    _StageDefinition(
        "silkscreen-resolve",
        "-silkscreen-resolve",
        barrier=True,
        cacheable=False,
        command_kind="silkscreen",
        design_loop=True,
        lane_runner=True,
    ),
    _StageDefinition(
        "board-pipeline",
        "",
        barrier=False,
        cacheable=True,
        command_kind="board",
        design_loop=True,
        lane_runner=True,
    ),
    _StageDefinition(
        "enclosure-pipeline",
        "-enclosure",
        barrier=False,
        cacheable=False,
        command_kind="enclosure",
        design_loop=True,
        lane_runner=True,
    ),
    _StageDefinition(
        "firmware-pipeline",
        "-fw",
        barrier=False,
        cacheable=False,
        command_kind="firmware",
        design_loop=True,
        lane_runner=True,
    ),
    _StageDefinition(
        "order-readiness",
        None,
        barrier=False,
        cacheable=False,
        command_kind=None,
        design_loop=True,
        lane_runner=False,
    ),
    _StageDefinition(
        "pytest-subset",
        None,
        barrier=False,
        cacheable=False,
        command_kind="pytest",
        design_loop=False,
        lane_runner=True,
        gd1_only=True,
    ),
    _StageDefinition(
        "board-exploration",
        "-board-exploration",
        barrier=False,
        cacheable=False,
        command_kind=None,
        design_loop=False,
        lane_runner=False,
        conditional=True,
    ),
)

DESIGN_LOOP_STAGE_IDS: tuple[str, ...] = tuple(
    definition.stage_id
    for definition in _STAGE_DEFINITIONS
    if definition.design_loop
)
DESIGN_LOOP_LANE_IDS: tuple[str, ...] = tuple(
    definition.stage_id
    for definition in _STAGE_DEFINITIONS
    if definition.design_loop
    and not definition.barrier
    and definition.command_kind is not None
)
LANE_RUNNER_STAGE_IDS: tuple[str, ...] = tuple(
    definition.stage_id
    for definition in _STAGE_DEFINITIONS
    if definition.lane_runner
)


def build_lane_plan(graph_id: str, out_root: Path) -> LanePlan:
    """Build the canonical lane plan for a graph and output root."""
    resolved_output_prefix = output_prefix(graph_id)
    resolved_artifact_prefix = artifact_prefix(graph_id)
    stages = tuple(
        LaneStage(
            stage_id=definition.stage_id,
            barrier=definition.barrier,
            output_path=(
                out_root
                / (
                    resolved_artifact_prefix
                    if definition.output_suffix == ""
                    else f"{resolved_artifact_prefix}{definition.output_suffix}"
                )
                if definition.output_suffix is not None
                else None
            ),
            cacheable=definition.cacheable,
            command_kind=definition.command_kind,
            design_loop=definition.design_loop,
            lane_runner=(
                definition.lane_runner
                and (
                    not definition.gd1_only
                    or resolved_artifact_prefix == "gd1"
                )
            ),
        )
        for definition in _STAGE_DEFINITIONS
    )
    return LanePlan(
        graph_id=graph_id,
        output_prefix=resolved_output_prefix,
        artifact_prefix=resolved_artifact_prefix,
        stages=stages,
    )
