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
    assert seen == [
        "requirement-entry-validation",
        "silkscreen-resolve",
        "board-pipeline",
    ]
    assert [item["stage_id"] for item in result["results"]] == [
        "requirement-entry-validation",
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
    assert seen == [
        "requirement-entry-validation",
        "silkscreen-resolve",
        "board-pipeline",
        "enclosure-pipeline",
    ]


def test_design_loop_stage_set_and_order_are_fixed() -> None:
    assert DESIGN_LOOP_STAGE_IDS == (
        "requirement-entry-validation",
        "silkscreen-resolve",
        "board-pipeline",
        "enclosure-pipeline",
        "firmware-pipeline",
        "order-readiness",
    )
    assert tuple(DEFAULT_STAGE_RUNNERS) == DESIGN_LOOP_STAGE_IDS


def test_order_total_aggregation_runs_before_order_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }

    def aggregate(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append("order-total-aggregation")
        return {
            "stage_id": "order-total-aggregation",
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
            "record_class": "L2",
        }

    monkeypatch.setattr(design_loop, "_run_order_total_aggregation", aggregate)
    _patch_runners(monkeypatch, runners)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        fab_profile=tmp_path / "fab-profile.json",
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
        jobs=1,
    )

    assert result["ok"] is True
    assert seen[-2:] == ["order-total-aggregation", "order-readiness"]
    assert [item["stage_id"] for item in result["results"]][-2:] == [
        "order-total-aggregation",
        "order-readiness",
    ]


def test_order_total_aggregation_generates_plan_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    seen: list[str] = []
    quote = tmp_path / "quote-order.json"
    scope = tmp_path / "order-scope.json"
    quote.write_text(
        (root / "fixtures/contracts/valid/quote-order.json")
        .read_text(encoding="utf-8")
        .replace('"r12"', '"r1"'),
        encoding="utf-8",
    )
    scope.write_text(
        (root / "fixtures/contracts/valid/order-scope.json")
        .read_text(encoding="utf-8")
        .replace('"r12"', '"r1"'),
        encoding="utf-8",
    )
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    _patch_runners(monkeypatch, runners)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        fab_profile=root / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json",
        quote_records=[quote],
        order_scope=scope,
        evaluated_at=datetime.fromisoformat("2025-01-11T00:00:00+00:00"),
        jobs=1,
    )

    assert result["ok"] is True
    output = tmp_path / "artifacts" / "order-total.json"
    assert output.is_file()
    aggregation = next(
        item for item in result["results"] if item["stage_id"] == "order-total-aggregation"
    )
    assert aggregation["output_path"] == str(output)
    assert aggregation["quote_count"] == 1


def test_order_total_aggregation_failure_skips_order_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }

    def aggregate(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        seen.append("order-total-aggregation")
        return {
            "stage_id": "order-total-aggregation",
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failure_reason": "invalid quote",
        }

    monkeypatch.setattr(design_loop, "_run_order_total_aggregation", aggregate)
    _patch_runners(monkeypatch, runners)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        fab_profile=tmp_path / "fab-profile.json",
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
        jobs=1,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "order-total-aggregation"
    assert "order-readiness" not in seen


def test_order_total_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
        fab_profile=tmp_path / "fab-profile.json",
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert "mutually exclusive" in result["failure_reason"]


def test_order_total_aggregation_requires_fab_profile(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "input"
    assert "fab profile" in result["failure_reason"]


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
        item["normalized_hash"]
        for item in sequential["results"]
        if "normalized_hash" in item
    ] == [
        item["normalized_hash"]
        for item in parallel["results"]
        if "normalized_hash" in item
    ]


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
    assert set(seen) == set(DESIGN_LOOP_LANE_IDS) | {
        "requirement-entry-validation",
        "silkscreen-resolve",
    }
    assert [item["stage_id"] for item in result["results"]] == [
        "requirement-entry-validation",
        "silkscreen-resolve",
        "board-pipeline",
        "enclosure-pipeline",
        "firmware-pipeline",
    ]


def test_design_loop_records_timing_write_failure_without_changing_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["requirement-entry-validation"] = (
        design_loop._run_requirement_entry_validation  # pyright: ignore[reportPrivateUsage]
    )
    _patch_runners(monkeypatch, runners)

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


def _copied_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "graph.json").write_text(
        (FIXTURE / "graph.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ("requirements.json", "rationale.json"):
        (fixture / name).write_text(
            (FIXTURE / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return fixture


def test_board_exploration_is_disabled_by_default(
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

    def unexpected_exploration(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("exploration must be opt-in")

    monkeypatch.setattr(design_loop, "explore_board_candidates", unexpected_exploration)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    assert result["ok"] is True
    assert "exploration_rounds" not in result


def test_requirement_entry_validation_records_input_facts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["requirement-entry-validation"] = (
        design_loop._run_requirement_entry_validation  # pyright: ignore[reportPrivateUsage]
    )
    _patch_runners(monkeypatch, runners)

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    entry = result["results"][0]
    assert result["ok"] is True
    assert entry["stage_id"] == "requirement-entry-validation"
    assert "record_class" not in entry
    assert entry["requirements_sha256"].startswith("sha256:")
    assert entry["graph_id"] == "golden-design-1"
    assert entry["revision"] == "r1"
    assert entry["requirement_count"] == 11
    assert entry["pass_evidence"] is False


@pytest.mark.parametrize("mutation", ["missing", "malformed", "graph_id", "revision", "text"])
def test_requirement_entry_validation_fails_closed_before_silkscreen(
    mutation: str,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    requirements_path = fixture / "requirements.json"
    if mutation == "missing":
        requirements_path.unlink()
    elif mutation == "malformed":
        requirements_path.write_text("{", encoding="utf-8")
    else:
        document = json.loads(requirements_path.read_text(encoding="utf-8"))
        if mutation == "graph_id":
            document["graph_id"] = "other-design"
        elif mutation == "revision":
            document["revision"] = "r2"
        else:
            document["records"][0]["statement"] = "inconsistent"
        requirements_path.write_text(json.dumps(document), encoding="utf-8")

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "requirement-entry-validation"
    assert [item["stage_id"] for item in result["results"]] == [
        "requirement-entry-validation"
    ]
    assert result["results"][0]["pass_evidence"] is False


def test_requirement_compile_is_opt_in_and_records_l2_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    update = tmp_path / "requirement-update.json"
    update.write_text("{}", encoding="utf-8")
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )

    def fake_compile(
        fixture_dir: Path,
        requirement_path: Path,
        *,
        dry_run: bool,
    ) -> Any:
        assert fixture_dir == fixture
        assert requirement_path == update
        assert dry_run is False
        return SimpleNamespace(
            report={
                "changed_node_ids": ["req.gd1-req-001"],
                "before_graph_sha256": "sha256:" + "a" * 64,
                "after_graph_sha256": "sha256:" + "b" * 64,
            }
        )

    monkeypatch.setattr(design_loop, "compile_requirement_change", fake_compile)
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        requirement=update,
    )

    compile_record = result["results"][0]
    assert result["ok"] is True
    assert compile_record["stage_id"] == "requirement-compile"
    assert compile_record["record_class"] == "L2"
    assert compile_record["pass_evidence"] is False
    assert compile_record["changed_node_ids"] == ["req.gd1-req-001"]
    assert compile_record["before_graph_sha256"].startswith("sha256:")
    assert compile_record["after_graph_sha256"].startswith("sha256:")
    assert result["results"][1]["stage_id"] == "requirement-entry-validation"


def test_requirement_compile_rejects_graph_id_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    update = tmp_path / "requirement-update.json"
    update.write_text("{}", encoding="utf-8")

    def fake_compile(
        fixture_dir: Path,
        requirement_path: Path,
        *,
        dry_run: bool,
    ) -> Any:
        del requirement_path, dry_run
        document = json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
        document["graph_id"] = "other-design"
        (fixture_dir / "graph.json").write_text(json.dumps(document), encoding="utf-8")
        return SimpleNamespace(report={})

    monkeypatch.setattr(design_loop, "compile_requirement_change", fake_compile)
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        requirement=update,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "requirement-compile"
    assert "graph ID changed" in result["failure_reason"]
    assert [item["stage_id"] for item in result["results"]] == [
        "requirement-compile"
    ]


def test_fixture_generation_is_opt_in_and_refuses_existing_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    spec = tmp_path / "fixture-spec.json"
    spec.write_text('{"design_name":"generated"}', encoding="utf-8")

    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        fixture_spec=spec,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "fixture-generation"
    assert "already contains graph.json" in result["failure_reason"]
    assert [item["stage_id"] for item in result["results"]] == [
        "fixture-generation"
    ]


def test_declared_fixture_overwrite_regenerates_the_graph_with_a_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    spec = tmp_path / "fixture-spec.json"
    spec.write_text(
        json.dumps({"design_name": "regenerated", "graph_id": "regenerated"}),
        encoding="utf-8",
    )
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )

    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        fixture_spec=spec,
        fixture_overwrite=True,
    )

    assert result["ok"] is True
    assert result["fixture_overwrite"] is True
    assert result["graph_id"] == "regenerated"
    assert result["results"][0]["overwrite"] is True
    report = json.loads(
        (fixture / "graph-overwrite-report.json").read_text(encoding="utf-8")
    )
    backup = json.loads(Path(report["backup_path"]).read_text(encoding="utf-8"))
    assert backup["graph_id"] == "golden-design-1"


def test_fixture_generation_parse_failure_is_recorded_as_stage_failure(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "fixture-spec.json"
    spec.write_text("{", encoding="utf-8")

    result = run_design_loop(
        tmp_path / "fixture",
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        fixture_spec=spec,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "fixture-generation"
    assert result["results"][0]["stage_id"] == "fixture-generation"
    assert "ValidationError" in result["results"][0]["failure_reason"]


def test_fixture_generation_uses_declared_graph_id_for_initial_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = tmp_path / "misleading-file-name.json"
    spec.write_text(
        json.dumps({"design_name": "declared-design", "graph_id": "declared-id"}),
        encoding="utf-8",
    )
    _patch_runners(
        monkeypatch,
        {
            stage_id: _successful_runner(stage_id, [])
            for stage_id in DESIGN_LOOP_STAGE_IDS
        },
    )

    result = run_design_loop(
        tmp_path / "fixture",
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        fixture_spec=spec,
    )

    assert result["ok"] is True
    assert result["graph_id"] == "declared-id"
    assert result["output_prefix"] == output_prefix("declared-id")
    assert result["artifact_prefix"] == artifact_prefix("declared-id")
    assert result["results"][0]["graph_id"] == "declared-id"


def test_board_rejection_explores_with_loop_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    captured: dict[str, Any] = {}

    def failing_board(config: DesignLoopConfig) -> dict[str, Any]:
        seen.append(config.graph_id)
        return {
            "stage_id": "board-pipeline",
            "ok": False,
            "fail_closed": True,
            "pass_evidence": False,
            "failure_reason": "board rejected",
        }

    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = failing_board
    _patch_runners(monkeypatch, runners)
    fab_profile = tmp_path / "fab-profile.json"
    cache_dir = tmp_path / "cache"

    def fake_explore(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        max_passes: int,
        dry_run: bool,
        pipeline_runner: Callable[[Path, Path], object],
    ) -> Any:
        captured.update(
            {
                "graph_path": graph_path,
                "fixture_dir": fixture_dir,
                "out_dir": out_dir,
                "max_candidates": max_candidates,
                "max_passes": max_passes,
                "dry_run": dry_run,
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

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        fab_profile=fab_profile,
        fab_profile_id="profile-1",
        max_passes=7,
        cache_dir=cache_dir,
        explore_board=True,
        max_exploration_candidates=2,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "board-pipeline"
    assert "board rejected" in result["failure_reason"]
    assert "exhausted" in result["failure_reason"]
    assert captured["max_candidates"] == 2
    assert captured["max_passes"] == 7
    assert captured["dry_run"] is False
    assert captured["out_dir"].name == "round-1"
    assert result["exploration_rounds"][0]["status"] == "exhausted"
    assert result["exploration_termination"] == "exhausted"
    assert seen == ["golden-design-1"]


def test_candidate_found_updates_graph_and_reruns_all_l1_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    seen: list[str] = []
    aggregation_calls: list[int] = []
    runner_calls: list[tuple[Path, Path, int, Path | None, str | None, Path | None]] = []

    def board_runner(config: DesignLoopConfig) -> dict[str, Any]:
        seen.append(f"board:{config.graph_id}")
        if len([item for item in seen if item.startswith("board:")]) == 1:
            return {
                "stage_id": "board-pipeline",
                "ok": False,
                "fail_closed": True,
                "pass_evidence": False,
                "failure_reason": "initial board rejection",
            }
        return _successful_runner("board-pipeline", seen)(config)

    runners = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = board_runner
    _patch_runners(monkeypatch, runners)

    def aggregate_runner(config: DesignLoopConfig) -> dict[str, Any]:
        aggregation_calls.append(config.max_passes)
        return {
            "stage_id": "order-total-aggregation",
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
        }

    monkeypatch.setattr(
        design_loop,
        "_run_order_total_aggregation",
        aggregate_runner,
    )

    def fake_board_pipeline(
        working: Path,
        output: Path,
        max_passes: int,
        fab_profile: Path | None,
        *,
        fab_profile_id: str | None,
        cache_dir: Path | None,
        timing_recorder: Any,
    ) -> dict[str, str]:
        del timing_recorder
        runner_calls.append(
            (working, output, max_passes, fab_profile, fab_profile_id, cache_dir)
        )
        return {}

    monkeypatch.setattr(design_loop, "run_board_pipeline", fake_board_pipeline)

    def fake_explore(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        max_passes: int,
        dry_run: bool,
        pipeline_runner: Callable[[Path, Path], object],
    ) -> Any:
        del graph_path, max_candidates, max_passes, dry_run
        pipeline_runner(fixture_dir, out_dir)
        body = json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
        target_revision = body["revision"]
        candidate_node = next(
            node
            for node in body["nodes"]
            if node["id"] == "mechanical.silk_graphic.vibebb"
        )
        candidate_node["attrs"]["candidate_marker"] = "candidate"
        (fixture_dir / "graph.json").write_text(
            json.dumps(body), encoding="utf-8"
        )
        return SimpleNamespace(
            report={
                "status": "candidate_found",
                "winner_written": True,
                "target_revision": target_revision,
                "evaluated_candidates": 1,
                "candidates": [],
            },
            report_path=out_dir / "exploration-report.json",
        )

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore)
    fab_profile = tmp_path / "fab-profile.json"
    cache_dir = tmp_path / "cache"
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        fab_profile=fab_profile,
        fab_profile_id="profile-1",
        max_passes=7,
        cache_dir=cache_dir,
        explore_board=True,
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
    )

    assert result["ok"] is True
    assert result["graph_id"] == "golden-design-1"
    assert seen.count("silkscreen-resolve") == 2
    assert seen.count("board:golden-design-1") == 2
    assert len(runner_calls) == 1
    assert aggregation_calls == [7]
    assert runner_calls[0][2:] == (
        7,
        fab_profile,
        "profile-1",
        cache_dir,
    )
    assert result["exploration_rounds"][0]["status"] == "candidate_found"
    assert [
        item["stage_id"]
        for item in result["results"]
        if item["stage_id"] == "requirement-entry-validation"
    ] == ["requirement-entry-validation", "requirement-entry-validation"]
    assert any(
        item["stage_id"] == "board-exploration" for item in result["results"]
    )
    timing = json.loads(
        (tmp_path / "artifacts" / "timing-record.json").read_text(encoding="utf-8")
    )
    timing_names = [stage["name"] for stage in timing["stages"]]
    assert "design-loop/silkscreen-resolve" in timing_names
    assert "design-loop/board-pipeline" in timing_names
    assert "design-loop/round-1/board-exploration" in timing_names
    assert "design-loop/round-2/silkscreen-resolve" in timing_names
    assert "design-loop/round-2/board-pipeline" in timing_names
    assert "design-loop/round-2/requirement-entry-validation" in timing_names
    assert "design-loop/round-2/order-total-aggregation" in timing_names
    assert len(timing_names) == len(set(timing_names))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("graph_id", "updated graph ID"),
        ("revision_changed", "updated graph revision changed"),
        ("content_same", "updated graph content hash did not change"),
        ("target_revision", "target_revision does not match"),
    ],
)
def test_candidate_found_requires_graph_identity_and_content_change(
    mutation: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = lambda config: {
        "stage_id": "board-pipeline",
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": "board rejected",
    }
    _patch_runners(monkeypatch, runners)

    def fake_explore(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        max_passes: int,
        dry_run: bool,
        pipeline_runner: Callable[[Path, Path], object],
    ) -> Any:
        del graph_path, max_candidates, max_passes, dry_run, pipeline_runner
        body = json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
        target_revision = body["revision"]
        if mutation == "graph_id":
            body["graph_id"] = "custom-design"
        if mutation == "revision_changed":
            body["revision"] = "r2"
        if mutation == "target_revision":
            body["nodes"][0]["attrs"]["text"] += " candidate"
            target_revision = "r2"
        (fixture_dir / "graph.json").write_text(json.dumps(body), encoding="utf-8")
        return SimpleNamespace(
            report={
                "status": "candidate_found",
                "winner_written": True,
                "target_revision": target_revision,
                "evaluated_candidates": 1,
                "candidates": [],
            },
            report_path=out_dir / "exploration-report.json",
        )

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore)
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        explore_board=True,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "board-exploration"
    assert message in result["failure_reason"]
    assert result["results"][-2]["report_status"] == "candidate_found"
    assert result["results"][-2]["report_path"].endswith("exploration-report.json")
    assert result["results"][-1]["failure_reason"].endswith("(fail-closed)")
    assert result["results"][-1]["pass_evidence"] is False
    assert result["exploration_rounds"][0]["status"] == "candidate_found"


def test_exploration_round_limit_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _copied_fixture(tmp_path)
    exploration_calls = 0
    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = lambda config: {
        "stage_id": "board-pipeline",
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": "board rejected",
    }
    _patch_runners(monkeypatch, runners)

    def fake_explore(
        graph_path: Path,
        fixture_dir: Path,
        out_dir: Path,
        max_candidates: int,
        *,
        max_passes: int,
        dry_run: bool,
        pipeline_runner: Callable[[Path, Path], object],
    ) -> Any:
        del graph_path, max_candidates, max_passes, dry_run, pipeline_runner
        nonlocal exploration_calls
        exploration_calls += 1
        body = json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
        target_revision = body["revision"]
        candidate_node = next(
            node
            for node in body["nodes"]
            if node["id"] == "mechanical.silk_graphic.vibebb"
        )
        candidate_node["attrs"]["candidate_marker"] = f"candidate-{exploration_calls}"
        (fixture_dir / "graph.json").write_text(json.dumps(body), encoding="utf-8")
        return SimpleNamespace(
            report={
                "status": "candidate_found",
                "winner_written": True,
                "target_revision": target_revision,
                "evaluated_candidates": 1,
                "candidates": [],
            },
            report_path=out_dir / "exploration-report.json",
        )

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore)
    result = run_design_loop(
        fixture,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        explore_board=True,
        max_exploration_rounds=2,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "board-pipeline"
    assert result["exploration_termination"] == "max_rounds_reached"
    assert exploration_calls == 2
    assert [item["round"] for item in result["exploration_rounds"]] == [1, 2]


def test_parallel_lane_join_precedes_board_exploration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    completed: set[str] = set()
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {}
    for stage_id in DESIGN_LOOP_STAGE_IDS:
        if stage_id == "board-pipeline":
            def board(config: DesignLoopConfig) -> dict[str, Any]:
                del config
                completed.add("board-pipeline")
                return {
                    "stage_id": "board-pipeline",
                    "ok": False,
                    "fail_closed": True,
                    "pass_evidence": False,
                    "failure_reason": "board rejected",
                }

            runners[stage_id] = board
        elif stage_id in DESIGN_LOOP_LANE_IDS:
            def lane(config: DesignLoopConfig, lane_id: str = stage_id) -> dict[str, Any]:
                del config
                completed.add(lane_id)
                return {
                    "stage_id": lane_id,
                    "ok": True,
                    "fail_closed": False,
                    "pass_evidence": False,
                }

            runners[stage_id] = lane
        else:
            runners[stage_id] = _successful_runner(stage_id, [])
    _patch_runners(monkeypatch, runners)

    def fake_explore(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        assert completed == set(DESIGN_LOOP_LANE_IDS)
        return SimpleNamespace(
            report={
                "status": "stopped",
                "winner_written": False,
                "evaluated_candidates": 0,
                "candidates": [],
            },
            report_path=tmp_path / "exploration-report.json",
        )

    monkeypatch.setattr(design_loop, "explore_board_candidates", fake_explore)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        explore_board=True,
        jobs=3,
    )

    assert result["ok"] is False
    assert result["exploration_rounds"][0]["status"] == "stopped"
    assert result["exploration_termination"] == "stopped"


def test_exploration_exception_has_error_termination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runners = {
        stage_id: _successful_runner(stage_id, [])
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }
    runners["board-pipeline"] = lambda config: {
        "stage_id": "board-pipeline",
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": "board rejected",
    }
    _patch_runners(monkeypatch, runners)

    def failing_exploration(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("exploration unavailable")

    monkeypatch.setattr(
        design_loop,
        "explore_board_candidates",
        failing_exploration,
    )
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        explore_board=True,
    )

    assert result["ok"] is False
    assert result["exploration_termination"] == "error"
    assert result["exploration_rounds"][0]["status"] == "unknown"
    assert "exploration unavailable" in result["failure_reason"]


@pytest.mark.parametrize("failed_stage", ["enclosure-pipeline", "firmware-pipeline"])
def test_non_board_lane_failure_does_not_trigger_exploration(
    failed_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {}
    for stage_id in DESIGN_LOOP_STAGE_IDS:
        if stage_id == failed_stage:
            def fail(config: DesignLoopConfig, stage: str = stage_id) -> dict[str, Any]:
                del config
                seen.append(stage)
                return {
                    "stage_id": stage,
                    "ok": False,
                    "fail_closed": True,
                    "pass_evidence": False,
                    "failure_reason": f"{stage} rejected",
                }

            runners[stage_id] = fail
        else:
            runners[stage_id] = _successful_runner(stage_id, seen)
    _patch_runners(monkeypatch, runners)

    def unexpected_exploration(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("only board rejection may trigger exploration")

    monkeypatch.setattr(design_loop, "explore_board_candidates", unexpected_exploration)
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        order_total=tmp_path / "order-total.json",
        policy=tmp_path / "policy.json",
        explore_board=True,
    )

    assert result["ok"] is False
    assert result["failed_stage"] == failed_stage
    assert "exploration_rounds" in result
    assert result["exploration_rounds"] == []


def test_design_only_mode_iterates_design_stages_without_order_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    runners: dict[str, Callable[[DesignLoopConfig], Any]] = {
        stage_id: _successful_runner(stage_id, seen)
        for stage_id in DESIGN_LOOP_STAGE_IDS
    }

    def unexpected_order(config: DesignLoopConfig) -> dict[str, Any]:
        del config
        raise AssertionError("design-only mode must not execute the order gate")

    runners["order-readiness"] = unexpected_order
    _patch_runners(monkeypatch, runners)

    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        design_only=True,
        jobs=1,
    )

    assert result["design_only"] is True
    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["pass_evidence"] is False
    assert result["failed_stage"] == "order-readiness"
    assert "order-readiness" not in seen
    assert seen == [
        stage_id for stage_id in DESIGN_LOOP_STAGE_IDS if stage_id != "order-readiness"
    ]
    order_result = result["results"][-1]
    assert order_result["stage_id"] == "order-readiness"
    assert order_result["ok"] is False
    assert order_result["execution_status"] == "not_executed"
    assert order_result["order_readiness_status"] == "not_executed"
    assert order_result["design_only"] is True
    assert "order_total" not in order_result
    assert "quote_id" not in json.dumps(order_result)


def test_design_only_mode_rejects_order_aggregation_inputs(tmp_path: Path) -> None:
    result = run_design_loop(
        FIXTURE,
        tmp_path / "artifacts",
        policy=tmp_path / "policy.json",
        design_only=True,
        quote_records=[tmp_path / "quote.json"],
        order_scope=tmp_path / "scope.json",
    )

    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["failed_stage"] == "input"
    assert "order aggregation inputs" in result["failure_reason"]
