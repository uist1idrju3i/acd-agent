"""Tests for the fixed graph-driven VibeBB design loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import acd.pipeline.design_loop as design_loop  # pyright: ignore[reportMissingTypeStubs]
from acd.core.naming import artifact_prefix, output_prefix
from acd.pipeline.design_loop import (  # pyright: ignore[reportMissingTypeStubs]
    DEFAULT_STAGE_RUNNERS,
    DESIGN_LOOP_LANE_IDS,
    DESIGN_LOOP_STAGE_IDS,
    DesignLoopConfig,
    run_design_loop,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _successful_runner(
    stage_id: str,
    seen: list[str],
) -> Callable[[DesignLoopConfig], dict[str, Any]]:
    def runner(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append(stage_id)
        return {
            "stage_id": stage_id,
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
        }

    return runner


def _patch_runners(
    monkeypatch: pytest.MonkeyPatch,
    runners: dict[str, Callable[[DesignLoopConfig], Any]],
) -> None:
    monkeypatch.setattr(design_loop, "DEFAULT_STAGE_RUNNERS", runners)


def test_design_loop_keeps_fixed_stage_order_and_graph_derived_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    graph_id_calls = 0
    original_graph_id = design_loop._graph_id  # pyright: ignore[reportPrivateUsage]

    def graph_id_once(fixture_dir: Path) -> str:
        nonlocal graph_id_calls
        graph_id_calls += 1
        return original_graph_id(fixture_dir)

    monkeypatch.setattr(design_loop, "_graph_id", graph_id_once)
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, seen)
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=1,
    )

    assert result["ok"] is True
    assert seen == list(DESIGN_LOOP_STAGE_IDS)
    assert graph_id_calls == 1
    assert result["graph_id"] == "golden-design-1"
    assert result["output_prefix"] == output_prefix("golden-design-1")
    assert result["artifact_prefix"] == artifact_prefix("golden-design-1") == "gd1"


def test_design_loop_stops_after_first_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    def failing_board(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append("board-pipeline")
        return {
            "stage_id": "board-pipeline",
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failure_reason": "intentional test failure",
        }

    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = failing_board
    _patch_runners(monkeypatch, runners)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=1,
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "board-pipeline"
    assert result["failure_reason"] == "intentional test failure"
    assert seen == ["silkscreen-resolve", "board-pipeline"]
    assert [item["stage_id"] for item in result["results"]] == [
        "silkscreen-resolve",
        "board-pipeline",
    ]
    assert all(item["pass_evidence"] is False for item in result["results"])


def test_missing_firmware_skill_fails_closed_without_running_order_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    firmware_runner = DEFAULT_STAGE_RUNNERS["firmware-pipeline"]
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["firmware-pipeline"] = firmware_runner
    _patch_runners(monkeypatch, runners)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        repository=tmp_path / "repository",
        jobs=1,
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "firmware-pipeline"
    assert "Skill script is missing" in result["failure_reason"]
    assert seen == ["silkscreen-resolve", "board-pipeline", "enclosure-pipeline"]


def test_design_loop_stage_set_and_order_are_fixed() -> None:
    assert DESIGN_LOOP_STAGE_IDS == (
        "silkscreen-resolve",
        "board-pipeline",
        "enclosure-pipeline",
        "firmware-pipeline",
        "order-readiness",
    )
    assert tuple(DEFAULT_STAGE_RUNNERS) == DESIGN_LOOP_STAGE_IDS


def test_design_loop_rejects_naive_evaluated_at(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        evaluated_at=datetime(2026, 8, 14),
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert result["failure_reason"] == "ValueError: evaluated-at must include a timezone"


def test_order_readiness_resolves_relative_paths_from_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    policy = json.loads(
        (Path(__file__).parents[2] / "fixtures/contracts/valid/order-policy.json").read_text(
            encoding="utf-8"
        )
    )
    policy["evidence_paths"] = "out/**/evidence-*.json"
    (repository / "policy.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )
    order_total = {
        "subtotals": [
            {
                "category": "assembly",
                "amount": {
                    "amount_minor": 100,
                    "currency": "USD",
                    "minor_unit_digits": 2,
                },
            }
        ],
        "total": {
            "amount_minor": 100,
            "currency": "USD",
            "minor_unit_digits": 2,
        },
        "target_revision": "r12",
        "quote_hashes": [
            {"quote_id": "quote-1", "canonical_hash": "sha256:" + "a" * 64}
        ],
        "breakdown_hash": "sha256:" + "b" * 64,
    }
    (repository / "order-total.json").write_text(
        json.dumps(order_total), encoding="utf-8"
    )
    evidence = repository / "out" / "lane" / "evidence-test.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_gate(**kwargs: Any) -> Any:
        captured.update(kwargs)

        def model_dump(mode: str) -> dict[str, str]:
            del mode
            return {"status": "valid"}

        return SimpleNamespace(model_dump=model_dump)

    monkeypatch.setattr(design_loop, "evaluate_pre_order_gate", fake_gate)

    def fake_order_total(document: Any) -> Any:
        return SimpleNamespace(document=document)

    monkeypatch.setattr(
        design_loop,
        "order_total_result_from_document",
        fake_order_total,
    )
    seen: list[str] = []
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["order-readiness"] = DEFAULT_STAGE_RUNNERS["order-readiness"]
    _patch_runners(monkeypatch, runners)

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=Path("order-total.json"),
        policy=Path("policy.json"),
        repository=repository,
    )

    assert result["ok"] is True
    assert captured["repository"] == repository.resolve()
    assert captured["evidence_paths"] == [evidence]


def test_invalid_graph_input_fails_closed(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "graph.json").write_text("{", encoding="utf-8")

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "input"
    assert result["results"] == []


def test_unsafe_graph_id_fails_closed(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    graph = (FIXTURE / "graph.json").read_text(encoding="utf-8")
    (fixture / "graph.json").write_text(
        graph.replace('"graph_id": "golden-design-1"', '"graph_id": "!!!"'),
        encoding="utf-8",
    )

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "input"
    assert "output prefix" in result["failure_reason"]


def test_design_loop_parallel_lanes_preserve_result_order_and_hashes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def runner(stage_id: str) -> Callable[[DesignLoopConfig], dict[str, Any]]:
        def run(config: DesignLoopConfig) -> dict[str, Any]:
            del config
            return {
                "stage_id": stage_id,
                "ok": True,
                "fail_closed": False,
                "pass_evidence": False,
                "normalized_hash": f"sha256:{stage_id}",
            }

        return run

    runners = {stage_id: runner(stage_id) for stage_id in DESIGN_LOOP_STAGE_IDS}
    _patch_runners(monkeypatch, runners)
    sequential = run_design_loop(
        FIXTURE,
        tmp_path / "sequential",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=1,
    )
    parallel = run_design_loop(
        FIXTURE,
        tmp_path / "parallel",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=3,
    )

    assert sequential["ok"] is True
    assert parallel["ok"] is True
    assert [item["stage_id"] for item in sequential["results"]] == list(
        DESIGN_LOOP_STAGE_IDS
    )
    assert [item["stage_id"] for item in parallel["results"]] == list(
        DESIGN_LOOP_STAGE_IDS
    )
    assert [
        item["normalized_hash"] for item in sequential["results"]
    ] == [item["normalized_hash"] for item in parallel["results"]]


def test_design_loop_resume_reexecutes_gate_stages_and_uses_default_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, Path | None]] = []

    def runner(stage_id: str) -> Callable[[DesignLoopConfig], dict[str, Any]]:
        def run(config: DesignLoopConfig) -> dict[str, Any]:
            seen.append((stage_id, config.cache_dir))
            return {
                "stage_id": stage_id,
                "ok": True,
                "fail_closed": False,
                "pass_evidence": False,
                "verdict": "valid",
                "evidence": {"restored": False},
            }

        return run

    _patch_runners(
        monkeypatch,
        {stage_id: runner(stage_id) for stage_id in DESIGN_LOOP_STAGE_IDS},
    )
    out_root = tmp_path / "artifacts"
    result = run_design_loop(
        FIXTURE,
        out_root,
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        resume=True,
        jobs=1,
    )

    assert result["ok"] is True
    assert result["cache_dir"] == str(out_root / ".stage-cache")
    assert [stage_id for stage_id, _cache in seen] == list(DESIGN_LOOP_STAGE_IDS)
    assert all(cache == out_root / ".stage-cache" for _stage, cache in seen)
    assert all(item["pass_evidence"] is False for item in result["results"])


def test_design_loop_parallel_failure_reports_all_started_lanes_without_order_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    def runner(stage_id: str) -> Callable[[DesignLoopConfig], dict[str, Any]]:
        def run(config: DesignLoopConfig) -> dict[str, Any]:
            del config
            seen.append(stage_id)
            if stage_id in {"board-pipeline", "firmware-pipeline"}:
                return {
                    "stage_id": stage_id,
                    "ok": False,
                    "fail_closed": True,
                    "pass_evidence": False,
                    "failure_reason": stage_id,
                }
            return {
                "stage_id": stage_id,
                "ok": True,
                "fail_closed": False,
                "pass_evidence": False,
            }

        return run

    _patch_runners(
        monkeypatch,
        {stage_id: runner(stage_id) for stage_id in DESIGN_LOOP_STAGE_IDS},
    )
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=3,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "board-pipeline"
    assert set(seen) == set(DESIGN_LOOP_LANE_IDS) | {"silkscreen-resolve"}
    assert [item["stage_id"] for item in result["results"]] == [
        "silkscreen-resolve",
        "board-pipeline",
        "enclosure-pipeline",
        "firmware-pipeline",
    ]


def test_design_loop_records_timing_write_failure_without_changing_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )

    def fail_write(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        raise OSError("timing destination is unavailable")

    monkeypatch.setattr(design_loop, "write_timing_record", fail_write)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=1,
    )

    assert result["ok"] is True
    assert "timing destination is unavailable" in result["timing_record_error"]


def test_design_loop_rejects_unusable_cache_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )
    cache_file = tmp_path / "cache-file"
    cache_file.write_text("not a directory", encoding="utf-8")
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        cache_dir=cache_file,
        jobs=1,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert "FileExistsError" in result["failure_reason"]


def test_design_loop_rejects_non_positive_jobs(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        jobs=0,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert result["failure_reason"] == "ValueError: jobs must be a positive integer"
