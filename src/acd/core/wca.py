"""Deterministic worst-case analysis for declared design variations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import cast

from acd.core.electrical import extract_electrical_lane
from acd.schema import (
    DesignGraph,
    SpiceCheck,
    SpiceResult,
    ToleranceTable,
    UseEnvironment,
    WcaComponent,
    WcaPowerBudget,
    WcaQuantity,
    WcaQuantityResult,
    WcaRequest,
    WcaResult,
)
from acd.schema.common import canonical_sha256

_VALUE_RE = re.compile(
    r"^\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
    r"(?:[eE][+-]?[0-9]+)?)\s*(meg|g|k|m|u|n|p|f)?",
    re.IGNORECASE,
)


class WcaInputError(ValueError):
    """Raised when WCA inputs cannot be associated with the graph."""


@dataclass(frozen=True)
class _Component:
    refdes: str
    value: float | None


def _parse_value(value: str) -> float | None:
    match = _VALUE_RE.fullmatch(value)
    if match is None:
        return None
    scale = {
        "": 1.0,
        "meg": 1e6,
        "g": 1e9,
        "k": 1e3,
        "m": 1e-3,
        "u": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
        "f": 1e-15,
    }[(match.group(2) or "").lower()]
    result = float(match.group(1)) * scale
    return result if math.isfinite(result) and result > 0 else None


def _check_revision(graph: DesignGraph, request: WcaRequest) -> None:
    if request.graph_id != graph.graph_id or request.revision != graph.revision:
        raise WcaInputError("graph/request graph_id or revision mismatch")


def _components(graph: DesignGraph) -> dict[str, _Component]:
    lane = extract_electrical_lane(graph)
    return {
        component.refdes: _Component(
            refdes=component.refdes,
            value=_parse_value(component.value),
        )
        for component in lane.components
    }


def _refs(inputs: dict[str, object], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = inputs.get(key)
        if isinstance(value, str) and value:
            return (value,)
        if isinstance(value, list):
            values = cast(list[object], value)
            if all(isinstance(item, str) and item for item in values):
                return tuple(cast(str, item) for item in values)
    return ()


def _target(quantity: WcaQuantity) -> str | None:
    value = quantity.inputs.get("target")
    return value if isinstance(value, str) and value else None


def _nominal(
    quantity: WcaQuantity,
    spice_result: SpiceResult | None,
) -> tuple[float | None, str | None]:
    if quantity.nominal_source == "declared":
        return quantity.nominal_value, None
    if spice_result is None:
        return None, "SPICE nominal requested but no SpiceResult was supplied"
    if spice_result.status != "pass":
        return None, "SPICE nominal is unavailable because SpiceResult is not pass"
    target = _target(quantity)
    if target is None:
        return None, "SPICE nominal quantity has no target"
    check: SpiceCheck | None = next(
        (
            item
            for item in spice_result.checks
            if item.target == target and item.status == "pass"
        ),
        None,
    )
    if check is None or check.measured is None or check.measured == 0:
        return None, "SPICE nominal is missing or degenerate"
    return check.measured, None


def _component_refs(quantity: WcaQuantity) -> tuple[str, ...]:
    inputs = quantity.inputs
    if quantity.kind == "divider_ratio":
        return _refs(inputs, "r1_refdes", "r1") + _refs(inputs, "r2_refdes", "r2")
    if quantity.kind == "series_current":
        return _refs(inputs, "resistor_refdes", "refdes")
    if quantity.kind in {"rc_time_constant", "i2c_rise_time"}:
        return _refs(inputs, "resistor_refdes") + _refs(
            inputs, "capacitor_refdes", "capacitance_refdes"
        )
    if quantity.kind == "ldo_output":
        return _refs(inputs, "ldo_refdes", "refdes")
    return ()


def _sensitivity(
    quantity: WcaQuantity,
    refdes: str,
    refs: tuple[str, ...],
    components: dict[str, _Component],
) -> float | None:
    if quantity.kind in {"rc_time_constant", "i2c_rise_time", "ldo_output"}:
        return 1.0
    if quantity.kind == "series_current":
        return -1.0
    if quantity.kind == "divider_ratio":
        if len(refs) != 2:
            return None
        first, second = refs
        r1 = components.get(first)
        r2 = components.get(second)
        if r1 is None or r2 is None or r1.value is None or r2.value is None:
            return None
        total = r1.value + r2.value
        if total <= 0:
            return None
        if refdes == first:
            return -r1.value / total
        if refdes == second:
            return r1.value / total
    return None


def _tolerance_entry(table: ToleranceTable, refdes: str, kind: str):
    exact = next(
        (entry for entry in table.entries if entry.part_class_or_refdes == refdes),
        None,
    )
    if exact is not None:
        return exact
    part_class = {
        "ldo_output": "ldo",
    }.get(kind, refdes.rstrip("0123456789") or refdes)
    return next(
        (
            entry
            for entry in table.entries
            if entry.part_class_or_refdes.lower() == part_class.lower()
        ),
        None,
    )


def _power_budget(
    quantity: WcaQuantity,
    budget: WcaPowerBudget | None,
) -> tuple[float | None, list[WcaComponent], list[WcaComponent], list[str]]:
    if budget is None:
        return None, [], [], ["power budget quantity has no power_budget declaration"]
    peak = sum(load.current_a["peak"] for load in budget.loads)
    return peak, [], [], []


def _quantity_result(
    quantity: WcaQuantity,
    table: ToleranceTable,
    environment: UseEnvironment | None,
    service_life_years: float,
    components: dict[str, _Component],
    spice_result: SpiceResult | None,
    power_budget: WcaPowerBudget | None,
) -> WcaQuantityResult:
    nominal, nominal_error = _nominal(quantity, spice_result)
    findings: list[str] = []
    hard_fail = False
    bias: list[WcaComponent] = []
    random: list[WcaComponent] = []
    refs = _component_refs(quantity)
    if quantity.kind == "power_budget_peak":
        nominal, power_bias, power_random, power_findings = _power_budget(
            quantity, power_budget
        )
        bias.extend(power_bias)
        random.extend(power_random)
        findings.extend(power_findings)
    elif nominal_error is not None:
        findings.append(nominal_error)
    if environment is None:
        findings.append("use environment is not declared")
    if quantity.kind != "power_budget_peak" and not refs:
        findings.append("quantity has no referenced component")

    values: list[tuple[str, float]] = []
    missing: list[str] = []
    for refdes in refs:
        entry = _tolerance_entry(table, refdes, quantity.kind)
        sensitivity = _sensitivity(quantity, refdes, refs, components)
        if entry is None:
            missing.append(refdes)
            continue
        if sensitivity is None:
            findings.append(f"{refdes}: sensitivity cannot be determined")
            continue
        random_value = abs(sensitivity) * entry.initial_tolerance_pct
        random.append(
            WcaComponent(
                source_refdes=refdes,
                kind="initial_tolerance",
                value_pct=random_value,
                signed=False,
            )
        )
        if entry.bias_pct is not None:
            signed = sensitivity * entry.bias_pct
            bias.append(
                WcaComponent(
                    source_refdes=refdes,
                    kind="initial_center_shift",
                    value_pct=signed,
                )
            )
        if entry.temp_coeff_ppm_per_c is not None and environment is not None:
            delta = max(
                abs(environment.temperature_c.min - 25.0),
                abs(environment.temperature_c.max - 25.0),
            )
            signed = sensitivity * entry.temp_coeff_ppm_per_c * delta / 10000.0
            bias.append(
                WcaComponent(
                    source_refdes=refdes,
                    kind="temperature",
                    value_pct=signed,
                )
            )
        if entry.aging_pct is not None and service_life_years > 0:
            fraction = min(service_life_years / entry.aging_pct.horizon_years, 1.0)
            signed = sensitivity * entry.aging_pct.value * fraction
            bias.append(
                WcaComponent(
                    source_refdes=refdes,
                    kind="aging",
                    value_pct=signed,
                )
            )
        values.append((refdes, sensitivity))

    if missing:
        findings.append("missing tolerance entries: " + ", ".join(sorted(missing)))
    if (
        quantity.kind == "power_budget_peak"
        and power_budget is not None
        and nominal is not None
        and nominal > power_budget.supply_capacity_a
    ):
        hard_fail = True

    if findings or nominal is None or len(values) != len(refs):
        return WcaQuantityResult(
            quantity_id=quantity.quantity_id,
            nominal=nominal,
            bias_components=bias,
            random_components=random,
            bias_total_pct=None,
            random_rss_pct=None,
            worst_low=None,
            worst_high=None,
            status="unknown",
            findings=findings,
        )

    bias_total = sum(component.value_pct for component in bias)
    random_rss = math.sqrt(
        sum(component.value_pct**2 for component in random)
    )
    worst_low = nominal * (1.0 + (bias_total / 100.0) - random_rss / 100.0)
    worst_high = nominal * (1.0 + (bias_total / 100.0) + random_rss / 100.0)
    status = "pass"
    if quantity.min is not None and worst_low < quantity.min:
        status = "fail"
        findings.append("worst-case lower bound is below the declared minimum")
    if quantity.max is not None and worst_high > quantity.max:
        status = "fail"
        findings.append("worst-case upper bound exceeds the declared maximum")
    if (
        quantity.kind == "power_budget_peak"
        and power_budget is not None
        and nominal > power_budget.supply_capacity_a
    ):
        status = "fail"
        findings.append("peak power demand exceeds declared supply capacity")
    if hard_fail:
        status = "fail"
    return WcaQuantityResult(
        quantity_id=quantity.quantity_id,
        nominal=nominal,
        bias_components=bias,
        random_components=random,
        bias_total_pct=bias_total,
        random_rss_pct=random_rss,
        worst_low=worst_low,
        worst_high=worst_high,
        status=status,
        findings=findings,
    )


def evaluate_wca(
    graph: DesignGraph,
    request: WcaRequest,
    tolerance_table: ToleranceTable,
    environment: UseEnvironment | None,
    spice_result: SpiceResult | None = None,
) -> WcaResult:
    """Evaluate nominal values with deterministic bias and RSS variation.

    For a quantity ``f(x)`` each declared input contributes
    ``(∂f/∂x)·x·δx/f``. Series current uses ``-δR/R``; RC and I2C rise
    time use ``+δR/R + δC/C``; LDO output uses ``+δV/V``; and divider
    ratio ``R2/(R1+R2)`` uses ``-R1/(R1+R2)·δR1/R1`` and
    ``+R1/(R1+R2)·δR2/R2``. Bias terms sum algebraically and independent
    initial tolerances combine by RSS.
    """
    _check_revision(graph, request)
    if environment is not None and (
        environment.graph_id != graph.graph_id
        or environment.revision != graph.revision
    ):
        raise WcaInputError("graph/environment graph_id or revision mismatch")
    if spice_result is not None and (
        spice_result.graph_id != graph.graph_id
        or spice_result.revision != graph.revision
    ):
        raise WcaInputError("graph/SpiceResult graph_id or revision mismatch")
    components = _components(graph)
    results = [
        _quantity_result(
            quantity,
            tolerance_table,
            environment,
            request.service_life_years,
            components,
            spice_result,
            request.power_budget,
        )
        for quantity in request.quantities
    ]
    statuses = [result.status for result in results]
    status = (
        "fail"
        if "fail" in statuses
        else "unknown"
        if "unknown" in statuses
        else "pass"
    )
    findings = [
        f"{result.quantity_id}: {finding}"
        for result in results
        for finding in result.findings
    ]
    return WcaResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        quantities=results,
        tolerance_table_sha256=canonical_sha256(tolerance_table),
        environment_sha256=(
            canonical_sha256(environment) if environment is not None else "unknown"
        ),
        spice_result_sha256=(
            canonical_sha256(spice_result) if spice_result is not None else "unknown"
        ),
        findings=findings,
        input_hashes={
            "graph": canonical_sha256(graph),
            "request": canonical_sha256(request),
            "tolerance_table": canonical_sha256(tolerance_table),
            "environment": (
                canonical_sha256(environment)
                if environment is not None
                else "unknown"
            ),
            "spice_result": (
                canonical_sha256(spice_result)
                if spice_result is not None
                else "unknown"
            ),
        },
    )


__all__ = ["WcaInputError", "evaluate_wca"]
