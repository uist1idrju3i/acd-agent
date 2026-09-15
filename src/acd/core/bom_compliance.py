"""Deterministic, non-authoritative BOM compliance declaration summaries."""

from __future__ import annotations

from datetime import date
from typing import Literal

from acd.core.bom import BomRow, build_bom, group_bom_rows_by_mpn
from acd.core.electrical import ElectricalLane
from acd.schema.bom_compliance import (
    BomCompliancePartSummary,
    BomComplianceRegimeSummary,
    BomComplianceSummary,
    ComplianceCounts,
    ComplianceDeclaration,
    ComplianceDeclarationRegistry,
    ComplianceDeclaredStatus,
    ComplianceRegime,
    MslLevel,
)
from acd.schema.common import canonical_sha256
from acd.schema.design_graph import DesignGraph

ALL_REGIMES: tuple[ComplianceRegime, ...] = (
    "rohs",
    "reach_svhc",
    "halogen_free",
    "conflict_minerals",
    "msl",
    "pfas",
)
PartStatus = ComplianceDeclaredStatus | Literal[
    "missing_entry",
    "no_mpn",
    "stale",
]


def _is_stale(
    declaration: ComplianceDeclaration,
    *,
    as_of: date,
    max_age_days: int,
) -> bool:
    age_days = (as_of - declaration.source.observed_at).days
    return (
        age_days < 0
        or age_days > max_age_days
        or (
            declaration.source.valid_until is not None
            and declaration.source.valid_until < as_of
        )
    )


def _rows_for_mpn(
    rows_by_mpn: dict[str, tuple[BomRow, ...]], mpn: str
) -> tuple[BomRow, ...]:
    return rows_by_mpn.get(mpn, ())


def summarize_bom_compliance(
    graph: DesignGraph,
    lane: ElectricalLane,
    registry: ComplianceDeclarationRegistry,
) -> BomComplianceSummary:
    """Summarize declarations without asserting regulatory compliance."""
    if graph.graph_id != registry.graph_id or graph.revision != registry.revision:
        raise ValueError(
            "compliance registry graph_id/revision does not match graph"
        )

    rows_by_mpn = group_bom_rows_by_mpn(build_bom(lane))
    governed_mpns = sorted(mpn for mpn in rows_by_mpn if mpn)
    entries = {entry.mpn: entry for entry in registry.entries}
    declarations_by_mpn = {
        mpn: {declaration.regime: declaration for declaration in entry.declarations}
        for mpn, entry in entries.items()
    }
    part_statuses: dict[str, dict[ComplianceRegime, PartStatus]] = {
        mpn: {} for mpn in governed_mpns
    }
    regime_summaries: list[BomComplianceRegimeSummary] = []

    for regime in ALL_REGIMES:
        in_scope = regime in registry.regimes
        counts: dict[str, int] = {
            "declared_compliant": 0,
            "declared_non_compliant": 0,
            "exempt": 0,
            "not_declared": 0,
            "unknown": 0,
            "missing_entry": 0,
            "stale": 0,
        }
        unknown_parts: list[str] = []
        non_compliant_parts: list[str] = []
        msl_level_counts: dict[MslLevel, int] = {}

        for mpn in governed_mpns:
            entry = entries.get(mpn)
            declaration = declarations_by_mpn.get(mpn, {}).get(regime)
            if not in_scope:
                counts["unknown"] += 1
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = "unknown"
                continue
            if entry is None:
                counts["missing_entry"] += 1
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = "missing_entry"
                continue
            if declaration is None:
                counts["not_declared"] += 1
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = "not_declared"
                continue

            counts[declaration.declared_status] += 1
            if declaration.msl_level is not None:
                msl_level_counts[declaration.msl_level] = (
                    msl_level_counts.get(declaration.msl_level, 0) + 1
                )
            if declaration.declared_status == "declared_non_compliant":
                non_compliant_parts.append(mpn)
            stale = _is_stale(
                declaration,
                as_of=registry.as_of,
                max_age_days=registry.policy.max_declaration_age_days,
            )
            if stale:
                counts["stale"] += 1
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = "stale"
                continue
            if declaration.declared_status == "exempt" and (
                declaration.exemption_reference is None
            ):
                counts["unknown"] += 1
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = "unknown"
            elif declaration.declared_status in {"not_declared", "unknown"}:
                unknown_parts.append(mpn)
                part_statuses[mpn][regime] = declaration.declared_status
            else:
                part_statuses[mpn][regime] = declaration.declared_status

        regime_summaries.append(
            BomComplianceRegimeSummary(
                regime=regime,
                in_scope=in_scope,
                counts=ComplianceCounts(**counts),
                unknown_parts=sorted(set(unknown_parts)),
                non_compliant_parts=sorted(set(non_compliant_parts)),
                msl_level_counts=msl_level_counts,
            )
        )

    required = set(registry.policy.required_regimes)
    required_summaries = [
        summary for summary in regime_summaries if summary.regime in required
    ]
    if any(summary.non_compliant_parts for summary in required_summaries):
        status = "fail"
    elif any(summary.unknown_parts for summary in required_summaries):
        status = "unknown"
    else:
        status = "pass"

    per_part: list[BomCompliancePartSummary] = []
    for mpn in governed_mpns:
        rows = _rows_for_mpn(rows_by_mpn, mpn)
        per_part.append(
            BomCompliancePartSummary(
                refdes=sorted({refdes for row in rows for refdes in row.refdes}),
                mpn=mpn,
                statuses={
                    regime: status
                    for regime, status in sorted(part_statuses[mpn].items())
                },
                msl_levels=sorted(
                    {
                        declaration.msl_level
                        for declaration in declarations_by_mpn.get(mpn, {}).values()
                        if declaration.msl_level is not None
                    }
                ),
            )
        )
    empty_rows = rows_by_mpn.get("", ())
    if empty_rows:
        per_part.append(
            BomCompliancePartSummary(
                refdes=sorted(
                    {refdes for row in empty_rows for refdes in row.refdes}
                ),
                mpn="no_mpn",
                statuses={regime: "no_mpn" for regime in ALL_REGIMES},
            )
        )

    return BomComplianceSummary(
        registry_id=registry.registry_id,
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        per_regime=regime_summaries,
        per_part=per_part,
        input_hashes={
            "graph": canonical_sha256(graph),
            "registry": canonical_sha256(registry),
        },
    )


def compliance_summary_markdown(summary: BomComplianceSummary) -> str:
    """Render a deterministic L3 declaration summary from a typed result."""
    lines = [
        "# BOMコンプライアンス申告状況サマリー",
        "",
        "この文書は申告状況の集計であり、適合判定または認証verdictではない。",
        "",
        f"- status: `{summary.status}`",
        f"- authority: `{summary.authority}`",
        "- compliance_verdict: `null`",
        "",
        "| regime | in_scope | declared_compliant | declared_non_compliant | "
        "exempt | not_declared | unknown | missing_entry | stale |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for regime in summary.per_regime:
        counts = regime.counts
        lines.append(
            f"| {regime.regime} | {str(regime.in_scope).lower()} | "
            f"{counts.declared_compliant} | {counts.declared_non_compliant} | "
            f"{counts.exempt} | {counts.not_declared} | {counts.unknown} | "
            f"{counts.missing_entry} | {counts.stale} |"
        )
    lines.extend(["", "## Unknown parts", ""])
    for regime in summary.per_regime:
        if regime.unknown_parts:
            lines.append(
                f"- `{regime.regime}`: {', '.join(regime.unknown_parts)}"
            )
    if not any(regime.unknown_parts for regime in summary.per_regime):
        lines.append("- none")
    lines.extend(["", "## Non-compliant declarations", ""])
    for regime in summary.per_regime:
        if regime.non_compliant_parts:
            lines.append(
                f"- `{regime.regime}`: {', '.join(regime.non_compliant_parts)}"
            )
    if not any(regime.non_compliant_parts for regime in summary.per_regime):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


__all__ = ["compliance_summary_markdown", "summarize_bom_compliance"]
