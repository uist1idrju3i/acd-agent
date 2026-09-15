"""L3 summaries derived from design loop results."""

from __future__ import annotations

from typing import Any, cast

from acd.core.router_diagnostics import (
    read_router_diagnostics,
    router_diagnostics_hint,
)
from acd.pipeline.lane_plan import (
    RECOVERY_EXPLORATION_STAGE_IDS,
)

from .config import DesignLoopConfig

CANDIDATE_DIAGNOSTICS_LIMIT = 12


def surface_router_diagnostics(result: dict[str, Any], config: DesignLoopConfig | None) -> None:
    """Attach board-output router diagnostics to the loop result (L3 only)."""
    router_diagnostics: dict[str, Any] | None = None
    candidate_diagnostics: list[dict[str, Any]] | None = None
    failed_stage = result.get("failed_stage")
    board_stage_ids = {
        "board-pipeline",
        RECOVERY_EXPLORATION_STAGE_IDS["board-pipeline"],
    }
    if config is not None and isinstance(failed_stage, str) and failed_stage in board_stage_ids:
        board_output = config.lane_plan.stage("board-pipeline").output_path
        if board_output is not None:
            diagnostics = read_router_diagnostics(board_output)
            router_diagnostics = diagnostics.to_dict()
            hint = router_diagnostics_hint(diagnostics)
            if hint is not None:
                existing = result.get("next_step_action")
                result["next_step_action"] = (
                    f"{existing}; {hint}" if isinstance(existing, str) else hint
                )
        exploration_output = config.lane_plan.stage(
            RECOVERY_EXPLORATION_STAGE_IDS["board-pipeline"]
        ).output_path
        if exploration_output is not None and exploration_output.is_dir():
            entries: list[dict[str, Any]] = []
            for round_dir in sorted(exploration_output.glob("round-*")):
                if not round_dir.is_dir():
                    continue
                try:
                    round_number = int(round_dir.name.removeprefix("round-"))
                except ValueError:
                    continue
                candidates_dir = round_dir / "candidates"
                if not candidates_dir.is_dir():
                    continue
                for candidate_dir in sorted(candidates_dir.iterdir()):
                    if not candidate_dir.is_dir():
                        continue
                    candidate_diag = read_router_diagnostics(candidate_dir)
                    entries.append(
                        {
                            "round": round_number,
                            "candidate_id": candidate_dir.name,
                            **candidate_diag.to_dict(),
                        }
                    )
            if entries:
                entries.sort(key=lambda entry: (entry["round"], entry["candidate_id"]))
                candidate_diagnostics = entries[:CANDIDATE_DIAGNOSTICS_LIMIT]
    result["router_diagnostics"] = router_diagnostics
    result["candidate_router_diagnostics"] = candidate_diagnostics


def visual_review_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    """Return the loop-summary ``visual_review`` field for the manifest stage."""
    results = result.get("results")
    if not isinstance(results, list):
        return None
    for entry in cast(list[object], results):
        if not isinstance(entry, dict):
            continue
        stage_result = cast(dict[str, Any], entry)
        if stage_result.get("stage_id") == "visual-review-manifest":
            return {
                "manifest_path": stage_result.get("manifest_path"),
                "required": stage_result.get("required"),
                "status": stage_result.get("status") if stage_result.get("ok") else "failed",
            }
    return None


def projection_docs_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    results = result.get("results")
    if not isinstance(results, list):
        return None
    for entry in cast(list[object], results):
        if not isinstance(entry, dict):
            continue
        stage_result = cast(dict[str, Any], entry)
        if stage_result.get("stage_id") == "projection-docs":
            documents = stage_result.get("documents")
            return {
                "output_path": stage_result.get("output_path"),
                "documents": (
                    len(cast(list[object], documents)) if isinstance(documents, list) else 0
                ),
                "hashes_path": stage_result.get("hashes_path"),
                "status": "failed" if not stage_result.get("ok") else "ok",
            }
    return None


def manufacturing_submission_summary(
    result: dict[str, Any],
) -> dict[str, Any] | None:
    results = result.get("results")
    if not isinstance(results, list):
        return None
    for entry in cast(list[object], results):
        if not isinstance(entry, dict):
            continue
        stage_result = cast(dict[str, Any], entry)
        if stage_result.get("stage_id") == "manufacturing-submission":
            return {
                "verdict_path": stage_result.get("verdict_path"),
                "status": (
                    stage_result.get("status")
                    if stage_result.get("status") is not None
                    else "failed"
                    if not stage_result.get("ok")
                    else "ok"
                ),
            }
    return None
