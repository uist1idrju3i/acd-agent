"""Declaration-driven per-lane recovery tests for the design loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import acd.pipeline.design_loop as design_loop  # pyright: ignore[reportMissingTypeStubs]
from acd.pipeline.design_loop import (  # pyright: ignore[reportMissingTypeStubs]
    DESIGN_LOOP_STAGE_IDS,
    DesignLoopConfig,
    run_design_loop,
)
from acd.pipeline.lane_plan import build_lane_plan
from acd.schema.common import canonical_json_sha256

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _copied_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    for name in ("graph.json", "requirements.json", "rationale.json"):
        (fixture / name).write_text(
            (FIXTURE / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return fixture


def _runners(
    failing_stage: str,
    reason: str = "lane rejected",
) -> dict[str, Callable[[DesignLoopConfig], Any]]:
    def success(stage_id: str) -> Callable[[DesignLoopConfig], dict[str, Any]]:
        def runner(config: DesignLoopConfig) -> dict[str, Any]:
            del config
            return {
                "stage_id": stage_id,
                "ok": True,
                "fail_closed": False,
                "pass_evidence": False,
            }

        return runner

    def failure(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        return {
            "stage_id": failing_stage,
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failure_reason": reason,
        }

    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: success(stage_id) for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners[failing_stage] = failure
    return runners


def _write_remediation_evidence(lane_out: Path, revision: str) -> None:
    evidence_dir = lane_out / "gate-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "artifact_kind": "design_predicate_report",
        "gate": "design_predicates",
        "target_revision": revision,
        "observation": {
            "predicates": [
                {
                    "name": "power_decoupling",
                    "status": "fail",
                    "remediation": {
                        "change_dimensions": ["component_placement_xy"],
                        "subject": {"refdes": "C5", "target_refdes": "U1"},
                    },
                }
            ]
        },
    }
    (evidence_dir / "design-predicates.json").write_text(
        json.dumps({**payload, "content_sha256": canonical_json_sha256(payload)}),
        encoding="utf-8",
    )


def test_board_rejection_without_recovery_reports_bounded_rerun_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(design_loop, "DEFAULT_STAGE_RUNNERS", _runners("board-pipeline"))

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        max_exploration_candidates=4,
        max_exploration_rounds=2,
    )

    rerun = result["recovery_rerun"]
    assert result["ok"] is False
    assert rerun["record_class"] == "L3"
    assert rerun["pass_evidence"] is False
    assert rerun["recovery_supported"] is True
    assert rerun["recovery_explorer"] == "board"
    assert "component_placement_xy" in rerun["recovery_dimensions"]
    assert rerun["arguments"] == {
        "--recover-lanes": True,
        "--max-exploration-candidates": 4,
        "--max-exploration-rounds": 2,
    }


def test_unsupported_lane_rejection_reports_a_next_step_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        design_loop, "DEFAULT_STAGE_RUNNERS", _runners("silkscreen-resolve")
    )

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    rerun = result["recovery_rerun"]
    assert result["failed_stage"] == "silkscreen-resolve"
    assert rerun["recovery_supported"] is False
    assert rerun["next_step_action"]
    assert rerun["recovery_unsupported_reason"]
    assert "arguments" not in rerun


def test_recover_lanes_dispatches_the_declared_enclosure_explorer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        design_loop, "DEFAULT_STAGE_RUNNERS", _runners("enclosure-pipeline")
    )

    def fake_explore_enclosure(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        dimensions: tuple[str, ...],
        jobs: int,
        pipeline_runner: Callable[[Path, Path], object],
        commit: bool,
    ) -> Any:
        del graph_path, fixture_dir, jobs, pipeline_runner
        captured.update(
            {
                "max_candidates": max_candidates,
                "dimensions": tuple(dimensions),
                "commit": commit,
            }
        )
        return SimpleNamespace(
            report={
                "status": "exhausted",
                "winner_written": False,
                "evaluated_candidates": 2,
                "candidates": [],
            },
            report_path=out_dir / "exploration-report.json",
        )

    def refuse_board(*args: object, **kwargs: object) -> Any:
        raise AssertionError("board exploration must not run for an enclosure lane")

    monkeypatch.setattr(
        design_loop, "explore_enclosure_candidates", fake_explore_enclosure
    )
    monkeypatch.setattr(design_loop, "explore_board_candidates", refuse_board)

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        recover_lanes=True,
        max_exploration_candidates=2,
    )

    assert result["ok"] is False
    assert result["recover_lanes"] is True
    assert captured["max_candidates"] == 2
    assert captured["commit"] is True
    assert "enclosure_wall_thickness_mm" in captured["dimensions"]
    round_record = result["exploration_rounds"][0]
    assert round_record["lane_id"] == "enclosure-pipeline"
    assert round_record["recovery_explorer"] == "enclosure"
    assert result["exploration_termination"] == "exhausted"
    assert all(item["pass_evidence"] is False for item in result["results"])


def test_remediation_free_board_rejection_consumes_no_candidate_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(design_loop, "DEFAULT_STAGE_RUNNERS", _runners("board-pipeline"))

    def refuse_board(*args: object, **kwargs: object) -> Any:
        raise AssertionError("recovery must not explore without declared remediation")

    monkeypatch.setattr(design_loop, "explore_board_candidates", refuse_board)

    result = run_design_loop(
        _copied_fixture(tmp_path),
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        recover_lanes=True,
    )

    exploration = next(
        item for item in result["results"] if item["stage_id"] == "board-exploration"
    )
    assert result["ok"] is False
    assert result["exploration_termination"] == "error"
    assert exploration["evaluated_candidates"] == 0
    assert exploration["report_status"] == "unknown"
    assert "no declared remediation" in exploration["failure_reason"] or (
        "has no predicate evidence" in exploration["failure_reason"]
    )
    assert exploration["pass_evidence"] is False


def test_declared_remediation_targets_the_board_explorer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    out_root = tmp_path / "artifacts"
    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    _write_remediation_evidence(
        build_lane_plan(graph["graph_id"], out_root).stage("board-pipeline").output_path
        or out_root,
        graph["revision"],
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(design_loop, "DEFAULT_STAGE_RUNNERS", _runners("board-pipeline"))

    def fake_explore_board(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        max_passes: int,
        dry_run: bool,
        pipeline_runner: Callable[[Path, Path], object],
        remediation: tuple[Any, ...],
    ) -> Any:
        del graph_path, fixture_dir, max_candidates, max_passes, dry_run
        del pipeline_runner
        captured["remediation"] = remediation
        return SimpleNamespace(
            report={
                "status": "exhausted",
                "winner_written": False,
                "evaluated_candidates": 1,
                "candidates": [],
            },
            report_path=out_dir / "exploration-report.json",
        )

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore_board)

    result = run_design_loop(
        fixture,
        out_root,
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        recover_lanes=True,
    )

    assert result["ok"] is False
    assert [item.refdes for item in captured["remediation"]] == ["C5"]
    assert [item.predicate for item in captured["remediation"]] == ["power_decoupling"]
    assert result["exploration_rounds"][0]["lane_id"] == "board-pipeline"


def test_invalid_recovery_declaration_stops_before_any_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def raise_declaration_error(*args: object, **kwargs: object) -> Any:
        raise design_loop.LaneRecoveryDeclarationError("declaration is invalid")

    monkeypatch.setattr(design_loop, "DEFAULT_STAGE_RUNNERS", _runners("board-pipeline"))
    monkeypatch.setattr(
        design_loop, "load_lane_recovery_declarations", raise_declaration_error
    )

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        recover_lanes=True,
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "input"
    assert "declaration is invalid" in result["failure_reason"]
