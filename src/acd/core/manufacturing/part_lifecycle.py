"""Deterministic opt-in part lifecycle and second-source checks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from acd.core.electrical.electrical import ElectricalLane
from acd.core.manufacturing.bom import BomRow, build_bom, group_bom_rows_by_mpn
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.part_lifecycle import (
    PartLifecycleCheckResult,
    PartLifecycleEntry,
    PartLifecyclePartResult,
    PartLifecycleRegistry,
    PartLifecycleResult,
    PartLifecycleResultStatus,
)


def _check(
    check_id: str,
    status: str,
    reason: str,
    subject_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> PartLifecycleCheckResult:
    return PartLifecycleCheckResult(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        subject_ids=sorted(set(subject_ids or [])),
        details=details or {},
    )


def _risk_classes_by_refdes(graph: DesignGraph) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in graph.nodes:
        if node.kind != "electrical.component":
            continue
        refdes = node.attrs.get("refdes")
        if not isinstance(refdes, str) or not refdes:
            continue
        values = {
            value
            for key in ("risk_class", "part_kind", "kind")
            for value in (node.attrs.get(key),)
            if isinstance(value, str) and value
        }
        result[refdes] = values
    return result


def _aggregate_status(statuses: list[str]) -> PartLifecycleResultStatus:
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def _requires_second_source(
    registry: PartLifecycleRegistry,
    row: BomRow,
    risk_classes_by_refdes: dict[str, set[str]],
) -> tuple[bool, bool]:
    policy = registry.policy
    if policy.require_second_source_for == "none":
        return False, False
    if policy.require_second_source_for == "all":
        return True, False
    expected = set(policy.risk_classes or [])
    matched = {
        risk_class
        for refdes in row.refdes
        for risk_class in risk_classes_by_refdes.get(refdes, set())
        if risk_class in expected
    }
    if matched:
        return True, False
    if any(not risk_classes_by_refdes.get(refdes) for refdes in row.refdes):
        return False, True
    return False, False


def _alternate_for_footprint(entry: PartLifecycleEntry, footprint: str) -> bool:
    return any(
        alternate.equivalence in {"drop_in", "footprint_compatible_value_check"}
        and alternate.footprint == footprint
        for alternate in entry.alternates
    )


def evaluate_part_lifecycle(
    graph: DesignGraph,
    lane: ElectricalLane,
    registry: PartLifecycleRegistry,
) -> PartLifecycleResult:
    """Evaluate lifecycle declarations against the deterministic lane BOM."""
    if graph.graph_id != registry.graph_id or graph.revision != registry.revision:
        raise ValueError("part lifecycle registry graph_id/revision does not match graph")

    rows = build_bom(lane)
    rows_by_mpn = group_bom_rows_by_mpn(rows)
    entries = {entry.mpn: entry for entry in registry.entries}
    risk_classes_by_refdes = _risk_classes_by_refdes(graph)
    statuses_by_mpn: dict[str, list[str]] = defaultdict(list)
    no_mpn = [refdes for row in rows if not row.mpn for refdes in row.refdes]
    missing = sorted(mpn for mpn in rows_by_mpn if mpn and mpn not in entries)
    if missing:
        for mpn in missing:
            statuses_by_mpn[mpn].append("unknown")
    coverage = _check(
        "coverage",
        "unknown" if missing else "pass",
        "BOM MPN declarations are complete"
        if not missing
        else "BOM MPNs are missing from the lifecycle registry",
        missing,
        {"missing_mpn": missing, "no_mpn_refdes": sorted(no_mpn)},
    )

    stale: list[str] = []
    freshness_details: dict[str, dict[str, str]] = {}
    governed_entries = {mpn: entries[mpn] for mpn in rows_by_mpn if mpn and mpn in entries}
    for mpn, entry in governed_entries.items():
        age_days = (registry.as_of - entry.status_source.observed_at).days
        detail = {
            "observed_at": entry.status_source.observed_at.isoformat(),
            "as_of": registry.as_of.isoformat(),
            "age_days": str(age_days),
        }
        if entry.status_source.valid_until is not None:
            detail["valid_until"] = entry.status_source.valid_until.isoformat()
        freshness_details[mpn] = detail
        if (
            age_days < 0
            or age_days > registry.policy.max_status_age_days
            or (
                entry.status_source.valid_until is not None
                and entry.status_source.valid_until < registry.as_of
            )
        ):
            stale.append(mpn)
            statuses_by_mpn[mpn].append("unknown")
    freshness = _check(
        "status_freshness",
        "unknown" if stale else "pass",
        "lifecycle status declarations are within the freshness policy"
        if not stale
        else "lifecycle status declarations are stale or expired",
        stale,
        {"stale_mpn": sorted(stale), "entries": freshness_details},
    )

    rejected: list[str] = []
    unknown_status: list[str] = []
    warnings: dict[str, str] = {}
    status_details: dict[str, str] = {}
    for mpn, entry in governed_entries.items():
        lifecycle_status = entry.lifecycle_status
        status_details[mpn] = lifecycle_status
        if lifecycle_status in registry.policy.reject_statuses:
            rejected.append(mpn)
            statuses_by_mpn[mpn].append("fail")
        elif lifecycle_status in registry.policy.warn_statuses:
            warnings[mpn] = lifecycle_status
        elif lifecycle_status == "unknown":
            unknown_status.append(mpn)
            statuses_by_mpn[mpn].append("unknown")
    lifecycle = _check(
        "lifecycle_status",
        "fail" if rejected else "unknown" if unknown_status else "pass",
        "lifecycle statuses satisfy the reject policy"
        if not rejected and not unknown_status
        else "one or more parts have a rejected lifecycle status"
        if rejected
        else "one or more lifecycle statuses are explicitly unknown",
        rejected or unknown_status,
        {"rejected": sorted(rejected), "unknown": sorted(unknown_status), "warnings": warnings},
    )

    second_source_failures: list[str] = []
    second_source_unknown: list[str] = []
    second_source_details: dict[str, Any] = {}
    for mpn, rows_for_mpn in rows_by_mpn.items():
        if not mpn or mpn not in entries:
            continue
        row = rows_for_mpn[0]
        required, applicability_unknown = _requires_second_source(
            registry, row, risk_classes_by_refdes
        )
        entry = entries[mpn]
        valid = all(
            _alternate_for_footprint(entry, candidate.footprint) for candidate in rows_for_mpn
        )
        second_source_details[mpn] = {
            "required": required,
            "applicability_unknown": applicability_unknown,
            "alternates": [alternate.model_dump(mode="json") for alternate in entry.alternates],
        }
        if applicability_unknown:
            second_source_unknown.append(mpn)
            statuses_by_mpn[mpn].append("unknown")
        elif required and not valid:
            second_source_failures.append(mpn)
            statuses_by_mpn[mpn].append("fail")
    second_source = _check(
        "second_source",
        "fail" if second_source_failures else "unknown" if second_source_unknown else "pass",
        "required second sources are declared"
        if not second_source_failures and not second_source_unknown
        else "required second sources are missing or footprint-incompatible"
        if second_source_failures
        else "risk class is unavailable for second-source applicability",
        second_source_failures or second_source_unknown,
        {
            "failures": sorted(second_source_failures),
            "unknown": sorted(second_source_unknown),
            "parts": second_source_details,
        },
    )

    footprint_conflicts: list[str] = []
    footprint_details: dict[str, list[dict[str, Any]]] = {}
    for mpn, rows_for_mpn in rows_by_mpn.items():
        if not mpn or mpn not in entries:
            continue
        bom_footprints = sorted({row.footprint for row in rows_for_mpn})
        declared_bom_footprint: str | list[str] = (
            bom_footprints[0] if len(bom_footprints) == 1 else bom_footprints
        )
        conflicts = [
            {
                "alternate_mpn": alternate.mpn,
                "declared_footprint": alternate.footprint,
                "bom_footprint": declared_bom_footprint,
            }
            for alternate in entries[mpn].alternates
            if alternate.equivalence == "drop_in"
            and any(alternate.footprint != row.footprint for row in rows_for_mpn)
        ]
        if conflicts:
            footprint_conflicts.append(mpn)
            statuses_by_mpn[mpn].append("fail")
            footprint_details[mpn] = conflicts
    footprint_consistency = _check(
        "alternate_footprint_consistency",
        "fail" if footprint_conflicts else "pass",
        "drop-in alternates declare the BOM footprint"
        if not footprint_conflicts
        else "drop-in alternates contradict the BOM footprint",
        footprint_conflicts,
        {"conflicts": footprint_details},
    )

    checks = [
        coverage,
        freshness,
        lifecycle,
        second_source,
        footprint_consistency,
    ]
    per_part: list[PartLifecyclePartResult] = []
    for mpn in sorted(rows_by_mpn):
        rows_for_mpn = rows_by_mpn[mpn]
        if not mpn:
            per_part.append(
                PartLifecyclePartResult(
                    refdes=sorted({refdes for row in rows_for_mpn for refdes in row.refdes}),
                    mpn="no_mpn",
                    lifecycle_status="no_mpn",
                    alternates_count=0,
                    status="pass",
                )
            )
            continue
        entry = entries.get(mpn)
        per_part.append(
            PartLifecyclePartResult(
                refdes=sorted({refdes for row in rows_for_mpn for refdes in row.refdes}),
                mpn=mpn,
                lifecycle_status=entry.lifecycle_status if entry else "unknown",
                alternates_count=len(entry.alternates) if entry else 0,
                status=_aggregate_status(statuses_by_mpn.get(mpn, [])),
            )
        )
    return PartLifecycleResult(
        registry_id=registry.registry_id,
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=_aggregate_status([check.status for check in checks]),
        checks=checks,
        per_part=per_part,
        input_hashes={
            "graph": canonical_sha256(graph),
            "registry": canonical_sha256(registry),
        },
    )


__all__ = ["evaluate_part_lifecycle"]
