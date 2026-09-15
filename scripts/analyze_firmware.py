#!/usr/bin/env python3
"""Aggregate opt-in firmware analyses without changing the firmware pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from acd.schema import CoverageFloor, DesignGraph, FirmwareAnalysisResult

_SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins/acd/skills/acd-firmware-esp32c3/scripts"
)
sys.path.insert(0, str(_SKILL_SCRIPTS))

from fw_coverage import evaluate_coverage, parse_gcovr_json  # noqa: E402
from fw_qemu import (  # noqa: E402
    VirtualRunCheckError,
    assert_sensor_log_matches_scenario,
)
from fw_stack_usage import (  # noqa: E402
    StackFunction,
    evaluate_stack_usage,
    parse_size_json,
    parse_su,
)
from fw_static_analysis import run_clang_tidy  # noqa: E402


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _status(values: list[str]) -> str:
    if "fail" in values:
        return "fail"
    if "unknown" in values:
        return "unknown"
    return "pass"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--static", action="store_true")
    parser.add_argument("--stack-budget", type=Path)
    parser.add_argument("--sim-scenario", type=Path)
    parser.add_argument("--virtual-log", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--coverage-floor", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(_read(args.fixture / "graph.json"))
        statuses: list[str] = []
        tool_versions: dict[str, str] = {}
        input_hashes = {"graph": _sha256(args.fixture / "graph.json")}
        static_result = None
        if args.static:
            checks = _SKILL_SCRIPTS.parent / "rules/clang_tidy_checks.json"
            static_result = run_clang_tidy(args.build_dir, checks, target_revision=graph.revision)
            statuses.append(str(static_result["status"]))
            tool_versions["clang-tidy"] = str(static_result["tool_version"])
            input_hashes["clang_tidy_checks"] = _sha256(checks)

        stack_result = None
        if args.stack_budget is not None:
            su_files = sorted(args.build_dir.rglob("*.su"))
            size_file = args.build_dir / "size.json"
            if not su_files or not size_file.is_file():
                stack_result = {
                    "status": "unknown",
                    "authority": "estimate",
                    "functions": [],
                    "tasks": [],
                    "size": {"status": "unknown"},
                    "findings": ["stack_usage_input_missing"],
                }
            else:
                functions: list[StackFunction] = []
                for path in su_files:
                    functions.extend(parse_su(path.read_text(encoding="utf-8"), args.build_dir))
                budget_data = _read(args.stack_budget)
                if not isinstance(budget_data, dict):
                    raise ValueError("stack budget must be an object")
                budget_data = cast(dict[str, object], budget_data)
                budgets: dict[str, tuple[int, float]] = {}
                for task, value in budget_data.items():
                    if isinstance(value, dict) and "stack_bytes" in value:
                        value = cast(dict[str, object], value)
                        stack_bytes = value["stack_bytes"]
                        margin_pct = value.get("margin_pct", 0)
                        if not isinstance(stack_bytes, (int, float)) or not isinstance(
                            margin_pct, (int, float)
                        ):
                            raise ValueError("stack budget values must be numeric")
                        budgets[str(task)] = (
                            int(stack_bytes),
                            float(margin_pct),
                        )
                stack_result = evaluate_stack_usage(
                    functions,
                    task_budgets=budgets,
                    size=parse_size_json(size_file.read_text(encoding="utf-8")),
                )
            statuses.append(str(stack_result["status"]))
            input_hashes["stack_budget"] = _sha256(args.stack_budget)

        peripheral_result = None
        if args.sim_scenario is not None or args.virtual_log is not None:
            if args.sim_scenario is None or args.virtual_log is None:
                raise ValueError("--sim-scenario and --virtual-log are a pair")
            scenario = _read(args.sim_scenario)
            if not isinstance(scenario, list) or not scenario:
                raise ValueError("simulation scenario is malformed")
            scenario_items = cast(list[object], scenario)
            samples: list[dict[str, float]] = []
            for raw_item in scenario_items:
                if not isinstance(raw_item, dict):
                    raise ValueError("simulation scenario is malformed")
                item = cast(dict[str, object], raw_item)
                t_c = item.get("t_c")
                rh_pct = item.get("rh_pct")
                if not isinstance(t_c, (int, float)) or not isinstance(
                    rh_pct, (int, float)
                ):
                    raise ValueError("simulation scenario is malformed")
                samples.append({"t_c": float(t_c), "rh_pct": float(rh_pct)})
            try:
                assert_sensor_log_matches_scenario(
                    args.virtual_log.read_text(encoding="utf-8"),
                    samples,
                )
                peripheral_status = "pass"
                details: list[str] = []
            except (KeyError, TypeError, ValueError, VirtualRunCheckError) as exc:
                peripheral_status = "fail"
                details = [str(exc)]
            peripheral_result = {
                "status": peripheral_status,
                "authority": "observation",
                "scenario_sha256": _sha256(args.sim_scenario),
                "samples": samples,
                "findings": details,
            }
            statuses.append(peripheral_status)
            input_hashes["sim_scenario"] = _sha256(args.sim_scenario)
            input_hashes["virtual_log"] = _sha256(args.virtual_log)

        coverage_result = None
        if args.coverage is not None or args.coverage_floor is not None:
            if args.coverage is None or args.coverage_floor is None:
                raise ValueError("--coverage and --coverage-floor are a pair")
            floor = CoverageFloor.model_validate(_read(args.coverage_floor))
            report = (
                None
                if not args.coverage.is_file()
                else parse_gcovr_json(args.coverage.read_text(encoding="utf-8"))
            )
            coverage_result = evaluate_coverage(report, floor)
            statuses.append(coverage_result.status)
            input_hashes["coverage_floor"] = _sha256(args.coverage_floor)
            if args.coverage.is_file():
                input_hashes["coverage"] = _sha256(args.coverage)

        if not statuses:
            raise ValueError("at least one analysis option is required")
        result = FirmwareAnalysisResult.model_validate(
            {
                "graph_id": graph.graph_id,
                "revision": graph.revision,
                "status": _status(statuses),
                "static_analysis": static_result,
                "stack_usage": stack_result,
                "peripheral_sim": peripheral_result,
                "coverage": coverage_result,
                "tool_versions": tool_versions,
                "input_hashes": input_hashes,
            }
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")
    if coverage_result is None:
        payload.pop("coverage", None)
    args.out.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
