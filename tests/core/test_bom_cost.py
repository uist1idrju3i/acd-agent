from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.manufacturing.bom_cost import bom_cost_markdown, estimate_bom_cost
from acd.schema import DesignGraph, PartLifecycleRegistry, PartPriceBook

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
PRICE_BOOK_PATH = ROOT / "fixtures/bom-cost/gd1-2026-09.json"
LIFECYCLE_PATH = ROOT / "fixtures/part-lifecycle/gd1-2026-09.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _price_payload() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(PRICE_BOOK_PATH.read_text(encoding="utf-8")),
    )


def _lifecycle() -> PartLifecycleRegistry:
    return PartLifecycleRegistry.model_validate_json(
        LIFECYCLE_PATH.read_text(encoding="utf-8")
    )


def _estimate(
    payload: dict[str, Any] | None = None,
    lifecycle: PartLifecycleRegistry | None = None,
):
    graph = _graph()
    book = PartPriceBook.model_validate(payload or _price_payload())
    return estimate_bom_cost(
        graph,
        extract_electrical_lane(graph),
        book,
        lifecycle,
    )


def test_gd1_fixture_passes_and_lists_substitution_candidates() -> None:
    result = _estimate(lifecycle=_lifecycle())
    assert result.status == "pass"
    assert result.total_minor is not None
    assert result.coverage_pct == 100.0
    esp32 = next(
        candidate
        for candidate in result.substitution_candidates
        if candidate.mpn == "ESP32-C3-MINI-1-N4"
    )
    assert esp32.alternate_unit_price_minor == 610
    assert esp32.delta_minor == -40


def test_missing_mpn_is_unknown_and_total_is_null() -> None:
    payload = _price_payload()
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if entry["mpn"] != "SHT40-AD1B-R3"
    ]
    result = _estimate(payload)
    assert result.status == "unknown"
    assert result.total_minor is None
    assert result.partial_total_minor is not None
    coverage = next(check for check in result.checks if check.check_id == "price_coverage")
    assert coverage.details["missing_mpn"] == ["SHT40-AD1B-R3"]


def test_expired_price_is_unknown() -> None:
    payload = _price_payload()
    for entry in payload["entries"]:
        if entry["mpn"] == "SHT40-AD1B-R3":
            entry["source"]["valid_until"] = "2026-08-20T00:00:00Z"
    result = _estimate(payload)
    assert result.status == "unknown"
    assert "SHT40-AD1B-R3" in result.checks[0].subject_ids


def test_inference_basis_is_unknown_when_primary_is_required() -> None:
    payload = _price_payload()
    for entry in payload["entries"]:
        if entry["mpn"] == "KT-0603R":
            entry["basis"] = "inference"
    result = _estimate(payload)
    assert result.status == "unknown"
    assert "KT-0603R" in result.checks[0].subject_ids


def test_target_exceeded_fails() -> None:
    payload = _price_payload()
    payload["policy"]["target_total_minor"] = 1
    result = _estimate(payload)
    assert result.status == "fail"
    target = next(check for check in result.checks if check.check_id == "target_total")
    assert target.status == "fail"


def test_alternate_without_price_is_listed_with_null_price() -> None:
    payload = _price_payload()
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if entry["mpn"] != "SHT40-AD1B-R2"
    ]
    result = _estimate(payload, lifecycle=_lifecycle())
    candidate = next(
        candidate
        for candidate in result.substitution_candidates
        if candidate.alternate_mpn == "SHT40-AD1B-R2"
    )
    assert candidate.alternate_unit_price_minor is None
    assert candidate.delta_minor is None


def test_markdown_projection_is_deterministic() -> None:
    result = _estimate(lifecycle=_lifecycle())
    assert bom_cost_markdown(result) == bom_cost_markdown(result)


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    payload = _price_payload()
    payload["revision"] = "r2"
    price_book = tmp_path / "price-book.json"
    output = tmp_path / "result.json"
    price_book.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/estimate_bom_cost.py"),
            "--graph",
            str(GRAPH_PATH),
            "--price-book",
            str(price_book),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()
