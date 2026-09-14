"""Deterministic rough estimate for an idea record (L3 observation)."""

from __future__ import annotations

from pathlib import Path

from acd.schema.idea import IdeaField, IdeaRecord
from acd.schema.idea_estimate import (
    EstimateFinding,
    EstimateLine,
    EstimateRange,
    EstimateTotals,
    IdeaEstimateCatalog,
    IdeaRoughEstimate,
    UnknownFunction,
)


class IdeaEstimateError(ValueError):
    """Raised when an estimate input cannot be loaded or validated."""


def load_estimate_catalog(path: Path) -> IdeaEstimateCatalog:
    """Load an estimate catalog; any parse or validation failure is an error."""
    try:
        return IdeaEstimateCatalog.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise IdeaEstimateError(
            f"estimate catalog {path} is not valid: {exc}"
        ) from exc


def _sum_range(ranges: list[EstimateRange]) -> EstimateRange:
    return EstimateRange(
        min=sum(item.min for item in ranges),
        max=sum(item.max for item in ranges),
    )


def _finding(
    name: str,
    field: IdeaField,
    bound: EstimateRange | float,
    expected_unit: str,
    incomplete: bool,
) -> EstimateFinding:
    """Compare one confirmed numeric constraint against an estimate bound."""
    if field.status != "confirmed":
        return EstimateFinding(
            constraint=name,
            status="not_comparable",
            detail=f"{name} constraint is open",
        )
    value = field.value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return EstimateFinding(
            constraint=name,
            status="not_comparable",
            detail=f"{name} constraint value {value!r} is not numeric",
        )
    if field.unit != expected_unit:
        return EstimateFinding(
            constraint=name,
            status="not_comparable",
            detail=(
                f"{name} constraint unit {field.unit!r} is not "
                f"{expected_unit!r}"
            ),
        )
    limit = float(value)
    if isinstance(bound, EstimateRange):
        low, high = bound.min, bound.max
    else:
        low = high = bound
    suffix = " (estimate excludes unknown functions)" if incomplete else ""
    if low > limit:
        return EstimateFinding(
            constraint=name,
            status="stop",
            detail=(
                f"estimated {name} lower bound {low} exceeds the confirmed "
                f"limit {limit}{suffix}"
            ),
        )
    if high > limit:
        return EstimateFinding(
            constraint=name,
            status="risk",
            detail=(
                f"estimated {name} range [{low}, {high}] straddles the "
                f"confirmed limit {limit}{suffix}"
            ),
        )
    return EstimateFinding(
        constraint=name,
        status="within",
        detail=f"estimated {name} upper bound {high} within the confirmed "
        f"limit {limit}{suffix}",
    )


def estimate_idea(
    record: IdeaRecord, catalog: IdeaEstimateCatalog
) -> IdeaRoughEstimate:
    """Estimate cost, power, and footprint for every declared function.

    The result is an estimate: lines cover only catalog-known function
    classes, unknown functions are reported, and findings are observations
    that never act as approval.
    """
    by_class = {entry.function_class: entry for entry in catalog.entries}
    lines: list[EstimateLine] = []
    unknown: list[UnknownFunction] = []
    for function in record.functions:
        if function.function_class is None:
            unknown.append(
                UnknownFunction(
                    function_id=function.function_id,
                    reason="function_class undeclared",
                )
            )
            continue
        entry = by_class.get(function.function_class)
        if entry is None:
            unknown.append(
                UnknownFunction(
                    function_id=function.function_id,
                    reason=(
                        f"function_class {function.function_class!r} "
                        "not in catalog"
                    ),
                )
            )
            continue
        lines.append(
            EstimateLine(
                function_id=function.function_id,
                function_class=entry.function_class,
                typical_part=entry.typical_part,
                unit_cost_jpy=entry.unit_cost_jpy,
                power_mw=entry.power_mw,
                footprint_mm2=entry.footprint_mm2,
                source=entry.source,
            )
        )
    totals = EstimateTotals(
        cost_jpy=_sum_range([line.unit_cost_jpy for line in lines]),
        power_mw=_sum_range([line.power_mw for line in lines]),
        footprint_mm2=sum(line.footprint_mm2 for line in lines),
        covers_all_functions=not unknown,
    )
    incomplete = bool(unknown)
    findings = [
        _finding(
            "cost",
            record.constraints.cost,
            totals.cost_jpy,
            "JPY",
            incomplete,
        ),
        _finding(
            "power",
            record.constraints.power,
            totals.power_mw,
            "mW",
            incomplete,
        ),
        _finding(
            "dimensions",
            record.constraints.dimensions,
            totals.footprint_mm2,
            "mm2",
            incomplete,
        ),
    ]
    return IdeaRoughEstimate(
        idea_id=record.idea_id,
        revision=record.revision,
        catalog_id=catalog.catalog_id,
        lines=lines,
        unknown_functions=unknown,
        totals=totals,
        findings=findings,
    )
