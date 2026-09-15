"""Design loop configuration and shared stage-result helpers."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acd.core.runtime_records import (
    TimingRecorder,
)
from acd.pipeline import lane_plan
from acd.pipeline.lane_plan import (
    LanePlan,
)
from acd.schema import (
    DesignGraph,
)

DEFAULT_DESIGN_LOOP_JOBS = min(os.cpu_count() or 1, 3)
DESIGN_LOOP_STAGE_IDS = lane_plan.DESIGN_LOOP_STAGE_IDS

StageRunner = Callable[["DesignLoopConfig"], Any]


@dataclass(frozen=True)
class DesignLoopConfig:
    """Inputs for one graph-driven design loop."""

    fixture_dir: Path
    out_root: Path
    order_total: Path | None
    policy: Path
    repository: Path
    graph_id: str
    output_prefix: str
    artifact_prefix: str
    lane_plan: LanePlan
    fab_profile: Path | None
    fab_profile_id: str | None
    max_passes: int
    max_silkscreen_iterations: int
    run_seconds: int
    evaluated_at: datetime
    cache_dir: Path | None = None
    resume: bool = False
    jobs: int = DEFAULT_DESIGN_LOOP_JOBS
    timing_recorder: TimingRecorder | None = None
    max_exploration_candidates: int = 3
    max_exploration_rounds: int = 1
    requirement: Path | None = None
    fixture_spec: Path | None = None
    cpl_evidence_dir: Path | None = None
    quote_records: tuple[Path, ...] = ()
    order_scope: Path | None = None
    design_only: bool = False
    fixture_overwrite: bool = False
    wall_clock_budget_seconds: float | None = None
    token_budget: int | None = None
    previous_graph_path: Path | None = None
    document_languages: tuple[str, ...] = ("ja",)


def stage_success(stage_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": True,
        "fail_closed": False,
        "pass_evidence": False,
        **fields,
    }


def stage_failure(stage_id: str, reason: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": reason,
        **fields,
    }


def graph_id_of(fixture_dir: Path) -> str:
    graph_path = fixture_dir / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    return graph.graph_id


def load_graph(fixture_dir: Path) -> DesignGraph:
    return DesignGraph.model_validate_json((fixture_dir / "graph.json").read_text(encoding="utf-8"))


def resolve_evaluated_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("evaluated-at must include a timezone")
    return value
