"""Graph-driven VibeBB design loop package.

`acd.pipeline.design_loop` keeps its historical import surface (`run_design_loop`,
`DesignLoopConfig`, `DEFAULT_STAGE_RUNNERS`, stage ID tuples) while the implementation
lives in sibling modules:

- `config`: `DesignLoopConfig`, stage-result helpers, graph loading.
- `stages`: per-stage runners and `DEFAULT_STAGE_RUNNERS`.
- `recovery`: lane recovery declarations, candidate exploration, exploration stage.
- `summary`: L3 summaries surfaced on the loop result.
- `loop`: `run_design_loop` orchestration, `EXECUTE_ONCE_PLAN`, checkpoints, timing.

Dependency injection in tests must target the owning module (for example
`design_loop.loop.DEFAULT_STAGE_RUNNERS`, `design_loop.stages.run_board_pipeline`),
because rebinding a name on this facade does not affect the module that calls it.
"""

from __future__ import annotations

from acd.core.runtime.lane_recovery import LaneRecoveryDeclarationError
from acd.core.runtime.runtime_records import TimingRecorder
from acd.pipeline.lane_plan import DESIGN_LOOP_LANE_IDS, build_lane_plan

from . import config, loop, recovery, stages, summary
from .config import (
    DEFAULT_DESIGN_LOOP_JOBS,
    DESIGN_LOOP_STAGE_IDS,
    DesignLoopConfig,
    StageRunner,
    stage_failure,
    stage_success,
)
from .loop import EXECUTE_ONCE_PLAN, ExecuteOnceStep, run_design_loop
from .stages import (
    DEFAULT_STAGE_RUNNERS,
    run_board_stage,
    run_lane_preflight_stage,
    run_requirement_entry_validation_stage,
)

__all__ = [
    "DEFAULT_DESIGN_LOOP_JOBS",
    "DEFAULT_STAGE_RUNNERS",
    "DESIGN_LOOP_LANE_IDS",
    "DESIGN_LOOP_STAGE_IDS",
    "EXECUTE_ONCE_PLAN",
    "DesignLoopConfig",
    "ExecuteOnceStep",
    "LaneRecoveryDeclarationError",
    "StageRunner",
    "TimingRecorder",
    "build_lane_plan",
    "config",
    "loop",
    "recovery",
    "run_board_stage",
    "run_design_loop",
    "run_lane_preflight_stage",
    "run_requirement_entry_validation_stage",
    "stage_failure",
    "stage_success",
    "stages",
    "summary",
]
