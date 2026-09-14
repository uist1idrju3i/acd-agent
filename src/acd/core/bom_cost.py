"""Deterministic opt-in BOM cost estimation."""

from __future__ import annotations

from typing import Any

from acd.core.bom import build_bom, group_bom_rows_by_mpn
from acd.core.electrical import ElectricalLane
from acd.schema.bom_cost import (
    BomCostCheckResult,
    BomCostDriver,
    BomCostEstimate,
    BomCostLine,
    BomCostStatus,
    BomCostSubstitutionCandidate,
    BomCostWarning,
    PartPriceBook,
    PartPriceEntry,
)
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.part_lifecycle import PartLifecycleRegistry

_COST_DRIVER_LIMIT = 5


def _check(
    check_id: str,
    status: BomCostStatus,
    reason: str,
    subject_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> BomCostCheckResult:
    return BomCostCheckResult(
        check_id=check_id,
        status=status,
        reason=reason,
        subject_ids=sorted(set(subject_ids or [])),
        details=details or {},
    )


def _aggregate_status(statuses: list[BomCostStatus]) -> BomCostStatus:
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def _price_for_quantity(
    entry: PartPriceEntry,
    quantity: int,
) -> tuple[int, int] | None:
    applicable = [
        price_break
        for price_break in entry.price_breaks
        if price_break.min_qty <= quantity
    ]
    if not applicable:
        return None
    selected = max(applicable, key=lambda price_break: price_break.min_qty)
    return selected.min_qty, selected.unit_price_minor


def _price_entry_is_usable(
    entry: PartPriceEntry,
    price_book: PartPriceBook,
) -> tuple[bool, str]:
    source = entry.source
    if source.fetched_at.date() > price_book.as_of:
        return False, "price source was fetched after the price-book as_of date"
    if source.valid_until is not None and source.valid_until.date() < price_book.as_of:
        return False, "price source is expired at the price-book as_of date"
    if price_book.policy.require_primary_basis and entry.basis != "primary":
        return False, "price entry basis is inference, but primary basis is required"
    return True, ""


def _alternate_price(
    entry: PartPriceEntry,
    quantity: int,
    price_book: PartPriceBook,
) -> int | None:
    usable, _ = _price_entry_is_usable(entry, price_book)
    if not usable:
        return None
    selected = _price_for_quantity(entry, quantity)
    return selected[1] if selected is not None else None


def estimate_bom_cost(
    graph: DesignGraph,
    lane: ElectricalLane,
    price_book: PartPriceBook,
    lifecycle_registry: PartLifecycleRegistry | None = None,
) -> BomCostEstimate:
    """Estimate a deterministic BOM cost without changing the design graph."""
    if graph.graph_id != price_book.graph_id or graph.revision != price_book.revision:
        raise ValueError("price book graph_id/revision does not match graph")
    if lifecycle_registry is not None and (
        graph.graph_id != lifecycle_registry.graph_id
        or graph.revision != lifecycle_registry.revision
    ):
        raise ValueError("lifecycle registry graph_id/revision does not match graph")

    rows = build_bom(lane)
    rows_by_mpn = group_bom_rows_by_mpn(rows)
    entries = {entry.mpn: entry for entry in price_book.entries}
    valid_extended: dict[str, int] = {}
    selected_prices: dict[str, int] = {}
    selected_breaks: dict[str, int] = {}
    missing: list[str] = []
    unusable: dict[str, str] = {}
    no_mpn_refdes: list[str] = []
    lines: list[BomCostLine] = []

    for mpn in sorted(rows_by_mpn):
        rows_for_mpn = rows_by_mpn[mpn]
        refdes = sorted(
            {refdes for row in rows_for_mpn for refdes in row.refdes}
        )
        qty_per_board = len(refdes)
        extended_qty = qty_per_board * price_book.build_quantity
        if not mpn:
            no_mpn_refdes.extend(refdes)
            lines.append(
                BomCostLine(
                    mpn="no_mpn",
                    refdes=refdes,
                    qty_per_board=qty_per_board,
                    extended_qty=extended_qty,
                    status="not_applicable",
                )
            )
            continue
        entry = entries.get(mpn)
        if entry is None:
            missing.append(mpn)
            lines.append(
                BomCostLine(
                    mpn=mpn,
                    refdes=refdes,
                    qty_per_board=qty_per_board,
                    extended_qty=extended_qty,
                    status="unknown",
                )
            )
            continue
        usable, reason = _price_entry_is_usable(entry, price_book)
        selected = _price_for_quantity(entry, extended_qty)
        if not usable:
            unusable[mpn] = reason
        elif selected is None:
            unusable[mpn] = "no price break applies to the extended quantity"
        else:
            selected_breaks[mpn], selected_prices[mpn] = selected
            valid_extended[mpn] = extended_qty
        lines.append(
            BomCostLine(
                mpn=mpn,
                refdes=refdes,
                qty_per_board=qty_per_board,
                extended_qty=extended_qty,
                unit_price_minor=selected_prices.get(mpn),
                extended_minor=(
                    selected_prices[mpn] * extended_qty
                    if mpn in selected_prices
                    else None
                ),
                price_break_used=selected_breaks.get(mpn),
                status="pass" if mpn in selected_prices else "unknown",
            )
        )

    non_empty_mpns = sorted(mpn for mpn in rows_by_mpn if mpn)
    unknown_mpns = sorted(
        set(missing) | set(unusable)
    )
    coverage_pct = (
        100.0 * len(valid_extended) / len(non_empty_mpns)
        if non_empty_mpns
        else 100.0
    )
    partial_total_minor = sum(
        selected_prices[mpn] * valid_extended[mpn] for mpn in valid_extended
    )
    complete = not unknown_mpns and len(valid_extended) == len(non_empty_mpns)
    total_minor = partial_total_minor if complete else None
    line_by_mpn = {line.mpn: line for line in lines if line.mpn != "no_mpn"}
    for mpn, line in line_by_mpn.items():
        if total_minor is not None and line.extended_minor is not None:
            line_by_mpn[mpn] = line.model_copy(
                update={
                    "share_pct": (
                        100.0 * line.extended_minor / total_minor
                        if total_minor
                        else 0.0
                    )
                }
            )
    lines = [
        line_by_mpn.get(line.mpn, line)
        for line in lines
    ]

    coverage = _check(
        "price_coverage",
        "pass" if complete else "unknown",
        "all BOM MPNs have usable primary price entries"
        if complete
        else "one or more BOM MPNs lack a usable price entry",
        unknown_mpns,
        {
            "missing_mpn": sorted(missing),
            "unusable_mpn": unusable,
            "no_mpn_refdes": sorted(no_mpn_refdes),
            "partial_total_minor": partial_total_minor,
        },
    )

    over_target = (
        total_minor is not None
        and price_book.policy.target_total_minor is not None
        and total_minor > price_book.policy.target_total_minor
    )
    target_status: BomCostStatus = (
        "unknown" if total_minor is None else "fail" if over_target else "pass"
    )
    target = _check(
        "target_total",
        target_status,
        "estimated total is within the declared target"
        if target_status == "pass"
        else "estimated total exceeds the declared target"
        if target_status == "fail"
        else "target comparison requires complete price coverage",
        [],
        {
            "target_total_minor": price_book.policy.target_total_minor,
            "total_minor": total_minor,
        },
    )

    warnings: list[BomCostWarning] = []
    max_share = price_book.policy.max_unit_share_pct
    if total_minor is not None and max_share is not None:
        for line in lines:
            if (
                line.mpn != "no_mpn"
                and line.share_pct is not None
                and line.share_pct > max_share
            ):
                warnings.append(
                    BomCostWarning(
                        check_id="max_unit_share",
                        mpn=line.mpn,
                        reason="part exceeds the declared maximum share of total cost",
                        share_pct=line.share_pct,
                    )
                )
    share_check = _check(
        "max_unit_share",
        "pass",
        "unit cost share warnings are non-gating"
        if not warnings
        else "one or more parts exceed the declared cost-share warning threshold",
        [warning.mpn for warning in warnings],
        {
            "max_unit_share_pct": max_share,
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
        },
    )

    drivers = [
        BomCostDriver(
            mpn=line.mpn,
            extended_minor=line.extended_minor or 0,
            share_pct=line.share_pct or 0.0,
        )
        for line in sorted(
            (
                line
                for line in lines
                if line.mpn != "no_mpn" and line.extended_minor is not None
            ),
            key=lambda item: (-(item.extended_minor or 0), item.mpn),
        )[:_COST_DRIVER_LIMIT]
    ]

    candidates: list[BomCostSubstitutionCandidate] = []
    if lifecycle_registry is not None:
        lifecycle_entries = {
            entry.mpn: entry for entry in lifecycle_registry.entries
        }
        for mpn in non_empty_mpns:
            lifecycle_entry = lifecycle_entries.get(mpn)
            if lifecycle_entry is None:
                continue
            qty = (
                sum(len(row.refdes) for row in rows_by_mpn[mpn])
                * price_book.build_quantity
            )
            for alternate in lifecycle_entry.alternates:
                if alternate.equivalence not in {
                    "drop_in",
                    "footprint_compatible_value_check",
                }:
                    continue
                alternate_entry = entries.get(alternate.mpn)
                alternate_price = (
                    _alternate_price(alternate_entry, qty, price_book)
                    if alternate_entry is not None
                    else None
                )
                current_price = selected_prices.get(mpn)
                if alternate_price is not None and current_price is not None:
                    delta = alternate_price - current_price
                else:
                    delta = None
                note = (
                    "candidate price available; ACD does not substitute the graph"
                    if alternate_price is not None
                    else "alternate has no usable price entry"
                )
                candidates.append(
                    BomCostSubstitutionCandidate(
                        mpn=mpn,
                        alternate_mpn=alternate.mpn,
                        equivalence=alternate.equivalence,
                        alternate_unit_price_minor=alternate_price,
                        delta_minor=delta,
                        note=note,
                    )
                )
    candidates.sort(key=lambda item: (item.mpn, item.alternate_mpn))

    checks = [coverage, target, share_check]
    return BomCostEstimate(
        price_book_id=price_book.price_book_id,
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=_aggregate_status([check.status for check in checks]),
        currency=price_book.currency,
        minor_unit_digits=price_book.minor_unit_digits,
        build_quantity=price_book.build_quantity,
        checks=checks,
        lines=lines,
        total_minor=total_minor,
        partial_total_minor=partial_total_minor,
        coverage_pct=coverage_pct,
        over_target=over_target if total_minor is not None else None,
        cost_drivers=drivers,
        substitution_candidates=candidates,
        warnings=warnings,
        input_hashes={
            "graph": canonical_sha256(graph),
            "price_book": canonical_sha256(price_book),
            **(
                {"lifecycle_registry": canonical_sha256(lifecycle_registry)}
                if lifecycle_registry is not None
                else {}
            ),
        },
    )


def bom_cost_markdown(estimate: BomCostEstimate) -> str:
    """Render a deterministic L3 estimate projection."""
    lines = [
        "# BOMコスト見積",
        "",
        "見積（estimate）・発注権限なし",
        "",
        f"- status: `{estimate.status}`",
        f"- currency: `{estimate.currency}`",
        f"- build quantity: `{estimate.build_quantity}`",
        f"- coverage: `{estimate.coverage_pct:.2f}%`",
        f"- total minor: `{estimate.total_minor}`",
        f"- partial total minor: `{estimate.partial_total_minor}`",
        "",
        "## 部品別",
        "",
        "| MPN | RefDes | Qty/board | Extended qty | Unit price minor | "
        "Extended minor | Share | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for line in estimate.lines:
        share = "" if line.share_pct is None else f"{line.share_pct:.2f}%"
        lines.append(
            "| "
            + " | ".join(
                [
                    line.mpn,
                    ", ".join(line.refdes),
                    str(line.qty_per_board),
                    str(line.extended_qty),
                    "" if line.unit_price_minor is None else str(line.unit_price_minor),
                    "" if line.extended_minor is None else str(line.extended_minor),
                    share,
                    line.status,
                ]
            )
            + " |"
        )
    lines.extend(["", "## コストドライバ", ""])
    for driver in estimate.cost_drivers:
        lines.append(
            f"- `{driver.mpn}`: {driver.extended_minor} "
            f"({driver.share_pct:.2f}%)"
        )
    lines.extend(["", "## 代替候補", ""])
    for candidate in estimate.substitution_candidates:
        lines.append(
            f"- `{candidate.mpn}` → `{candidate.alternate_mpn}` "
            f"({candidate.equivalence}): "
            f"{candidate.alternate_unit_price_minor} "
            f"delta={candidate.delta_minor}; {candidate.note}"
        )
    lines.extend(["", "## 警告", ""])
    if estimate.warnings:
        for warning in estimate.warnings:
            lines.append(
                f"- `{warning.mpn}`: {warning.reason} "
                f"({warning.share_pct:.2f}%)"
            )
    else:
        lines.append("- なし")
    return "\n".join(lines) + "\n"


__all__ = ["bom_cost_markdown", "estimate_bom_cost"]
