from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.core.electrical.wca import evaluate_wca
from acd.schema import (
    DesignGraph,
    SpiceResult,
    ToleranceTable,
    UseEnvironment,
    WcaRequest,
)

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/wca/gd1-request.json"
TABLE_PATH = ROOT / "fixtures/wca/gd1-tolerances.json"
ENVIRONMENT_PATH = ROOT / "fixtures/use-environment/gd1-indoor-usb.json"
SPICE_PATH = ROOT / "fixtures/wca/gd1-spice-result.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs() -> tuple[
    DesignGraph, WcaRequest, ToleranceTable, UseEnvironment, SpiceResult
]:
    return (
        DesignGraph.model_validate(_json(GRAPH_PATH)),
        WcaRequest.model_validate(_json(REQUEST_PATH)),
        ToleranceTable.model_validate(_json(TABLE_PATH)),
        UseEnvironment.model_validate(_json(ENVIRONMENT_PATH)),
        SpiceResult.model_validate(_json(SPICE_PATH)),
    )


def test_gd1_wca_passes_and_records_composition() -> None:
    graph, request, table, environment, spice = _inputs()
    result = evaluate_wca(graph, request, table, environment, spice)
    assert result.status == "pass"
    assert result.authority == "estimate"
    assert result.composition_method == "bias_sum_plus_rss"
    assert [quantity.status for quantity in result.quantities] == [
        "pass",
        "pass",
        "pass",
        "pass",
    ]
    peak = result.quantities[-1]
    assert peak.nominal == pytest.approx(0.362)
    assert peak.worst_high == pytest.approx(0.362)


def test_missing_tolerance_is_unknown() -> None:
    graph, request, table, environment, spice = _inputs()
    payload = table.model_dump(mode="json")
    payload["entries"] = [
        entry for entry in payload["entries"] if entry["part_class_or_refdes"] != "R"
    ]
    result = evaluate_wca(
        graph,
        request,
        ToleranceTable.model_validate(payload),
        environment,
        spice,
    )
    assert result.status == "unknown"
    assert result.quantities[0].status == "unknown"


def test_missing_environment_is_unknown() -> None:
    graph, request, table, _, spice = _inputs()
    result = evaluate_wca(graph, request, table, None, spice)
    assert result.status == "unknown"
    assert all(quantity.status == "unknown" for quantity in result.quantities)


def test_tightened_maximum_fails() -> None:
    graph, request, table, environment, spice = _inputs()
    payload = request.model_dump(mode="json")
    payload["quantities"][1]["max"] = 2.1e-7
    result = evaluate_wca(
        graph,
        WcaRequest.model_validate(payload),
        table,
        environment,
        spice,
    )
    assert result.status == "fail"
    assert result.quantities[1].status == "fail"


def test_peak_exceeds_capacity_even_when_typical_is_below() -> None:
    graph, request, table, environment, spice = _inputs()
    payload = request.model_dump(mode="json")
    payload["power_budget"]["supply_capacity_a"] = 0.3
    typical = sum(
        load["current_a"]["typical"] for load in payload["power_budget"]["loads"]
    )
    assert typical < payload["power_budget"]["supply_capacity_a"]
    result = evaluate_wca(
        graph,
        WcaRequest.model_validate(payload),
        table,
        environment,
        spice,
    )
    assert result.status == "fail"
    assert result.quantities[-1].status == "fail"
    assert result.quantities[-1].nominal == pytest.approx(0.362)


def test_missing_spice_nominal_is_unknown() -> None:
    graph, request, table, environment, _ = _inputs()
    result = evaluate_wca(graph, request, table, environment, None)
    assert result.status == "unknown"
    assert result.quantities[0].status == "unknown"
    assert result.quantities[1].status == "unknown"


def test_revision_mismatch_is_rejected() -> None:
    graph, request, table, environment, spice = _inputs()
    payload = request.model_dump(mode="json")
    payload["revision"] = "r2"
    with pytest.raises(ValueError, match="mismatch"):
        evaluate_wca(
            graph,
            WcaRequest.model_validate(payload),
            table,
            environment,
            spice,
        )


def test_result_is_deterministic() -> None:
    graph, request, table, environment, spice = _inputs()
    first = evaluate_wca(graph, request, table, environment, spice)
    second = evaluate_wca(graph, request, table, environment, spice)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
