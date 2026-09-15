from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from acd.core.electrical import extract_electrical_lane
from acd.core.part_lifecycle import evaluate_part_lifecycle
from acd.schema import DesignGraph, PartLifecycleRegistry

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REGISTRY_PATH = ROOT / "fixtures/part-lifecycle/gd1-2026-09.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _registry_payload() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8")),
    )


def _registry(**updates: object) -> PartLifecycleRegistry:
    payload = _registry_payload()
    payload.update(updates)
    return PartLifecycleRegistry.model_validate(payload)


def _result(registry: PartLifecycleRegistry | None = None):
    graph = _graph()
    return evaluate_part_lifecycle(
        graph,
        extract_electrical_lane(graph),
        registry or _registry(),
    )


def test_gd1_fixture_covers_all_bom_mpns_and_lists_no_mpn() -> None:
    result = _result()
    assert result.status == "pass"
    assert all(check.status == "pass" for check in result.checks)
    assert {
        part.mpn for part in result.per_part if part.mpn != "no_mpn"
    } == {
        entry["mpn"] for entry in _registry_payload()["entries"]
    }
    no_mpn = next(part for part in result.per_part if part.mpn == "no_mpn")
    assert no_mpn.refdes == [
        "H1",
        "H2",
        "H3",
        "H4",
        "TP1",
        "TP2",
        "TP3",
        "TP4",
        "TP5",
        "TP6",
        "TP7",
    ]


def test_missing_entry_is_unknown() -> None:
    payload = _registry_payload()
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if entry["mpn"] != "SHT40-AD1B-R3"
    ]
    result = _result(PartLifecycleRegistry.model_validate(payload))
    assert result.status == "unknown"
    check = next(item for item in result.checks if item.check_id == "coverage")
    assert check.status == "unknown"
    assert check.details["missing_mpn"] == ["SHT40-AD1B-R3"]


def test_eol_status_fails() -> None:
    payload = _registry_payload()
    for entry in payload["entries"]:
        if entry["mpn"] == "SHT40-AD1B-R3":
            entry["lifecycle_status"] = "eol"
    result = _result(PartLifecycleRegistry.model_validate(payload))
    assert result.status == "fail"
    assert next(
        item for item in result.checks if item.check_id == "lifecycle_status"
    ).status == "fail"


def test_stale_status_is_unknown() -> None:
    payload = _registry_payload()
    for entry in payload["entries"]:
        entry["status_source"]["observed_at"] = "2020-01-01"
    result = _result(PartLifecycleRegistry.model_validate(payload))
    assert result.status == "unknown"
    assert next(
        item for item in result.checks if item.check_id == "status_freshness"
    ).status == "unknown"


def test_required_second_source_without_alternate_fails() -> None:
    registry = _registry(
        policy={
            "require_second_source_for": "all",
            "max_status_age_days": 60,
        }
    )
    result = _result(registry)
    assert result.status == "fail"
    check = next(item for item in result.checks if item.check_id == "second_source")
    assert check.status == "fail"
    assert "KT-0603R" in check.subject_ids


def test_drop_in_alternate_with_different_footprint_fails() -> None:
    payload = _registry_payload()
    for entry in payload["entries"]:
        if entry["mpn"] == "ESP32-C3-MINI-1-N4":
            entry["alternates"][0]["footprint"] = "Other:Different"
    result = _result(PartLifecycleRegistry.model_validate(payload))
    assert result.status == "fail"
    assert next(
        item
        for item in result.checks
        if item.check_id == "alternate_footprint_consistency"
    ).status == "fail"


def test_warning_status_is_recorded_without_gating() -> None:
    payload = _registry_payload()
    for entry in payload["entries"]:
        if entry["mpn"] == "KT-0603R":
            entry["lifecycle_status"] = "nrnd"
    result = _result(PartLifecycleRegistry.model_validate(payload))
    assert result.status == "pass"
    check = next(item for item in result.checks if item.check_id == "lifecycle_status")
    assert check.details["warnings"] == {"KT-0603R": "nrnd"}


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    payload = _registry_payload()
    payload["revision"] = "r2"
    registry_path = tmp_path / "registry.json"
    output_path = tmp_path / "result.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_part_lifecycle.py"),
            "--graph",
            str(GRAPH_PATH),
            "--registry",
            str(registry_path),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output_path.exists()


def test_cli_as_of_override_is_deterministic(tmp_path: Path) -> None:
    output_one = tmp_path / "one.json"
    output_two = tmp_path / "two.json"
    args = [
        sys.executable,
        str(ROOT / "scripts/check_part_lifecycle.py"),
        "--graph",
        str(GRAPH_PATH),
        "--registry",
        str(REGISTRY_PATH),
        "--as-of",
        "2026-09-01",
    ]
    for output in (output_one, output_two):
        completed = subprocess.run(
            [*args, "--out", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
    assert output_one.read_bytes() == output_two.read_bytes()
