"""Electrical Evidence assembly and gate-result summaries for the board pipeline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import RuleCheckResult
from acd.adapters.kicad.gates import GateError
from acd.core.electrical.electrical import ElectricalLane
from acd.core.knowledge.design_predicates import (
    OPT_IN_PREDICATES,
    PREDICATE_CATALOG,
    PredicateResult,
)
from acd.core.knowledge.naming import evidence_id
from acd.schema.evidence import Evidence, EvidenceClaim
from acd.schema.tool_envelope import ToolEnvelope


def check_rotation_offsets(
    lane: ElectricalLane,
    declared_rotation_offsets: Mapping[str, float],
    verified_rotation_offsets: Mapping[str, float],
    evidence_dir: Path,
) -> None:
    """Fail when a declared CPL rotation offset disagrees with LCSC Evidence."""
    components = {component.refdes: component for component in lane.components}
    for ref, offset in verified_rotation_offsets.items():
        effective = declared_rotation_offsets.get(ref, 0.0)
        if abs(effective - offset) <= 0.01:
            continue
        component = components.get(ref)
        declared = component.cpl_rotation_offset_deg if component is not None else None
        basis = component.cpl_rotation_evidence_basis if component is not None else None
        raise ValueError(
            f"{ref}: graph CPL rotation offset differs from LCSC Evidence "
            f"(declared cpl_rotation_offset_deg={declared!r} deg, effective offset "
            f"applied to CPL={effective:.2f} deg, LCSC Evidence offset={offset:.2f} "
            f"deg, cpl_rotation_evidence_basis={basis!r}); the effective offset is "
            "forced to 0.0 unless the basis is 'confirmed' with full provenance — "
            f"next step: check {evidence_dir / f'{ref}.json'}, then declare "
            f"cpl_rotation_offset_deg={offset:.2f} with cpl_rotation_evidence_basis "
            "'confirmed' (method, revision, note, source_url, evidence_at), or "
            "correct the lcsc part number; the tolerance (0.01 deg) is unchanged"
        )


def summarize_width_violations(
    result: RuleCheckResult,
    net_name: str,
    report_path: Path,
) -> dict[str, object]:
    error_count = result.error_count
    unconnected_items = result.unconnected_items
    violations = result.violations
    width_violations = tuple(
        violation
        for violation in violations
        if "width" in json.dumps(violation, sort_keys=True).lower()
    )
    target_width_violations = tuple(
        violation
        for violation in width_violations
        if any(
            f"[{net_name}]" in str(item.get("description", ""))
            for item in cast(list[dict[str, object]], violation.get("items", []))
        )
    )
    return {
        "drc_error_count": error_count,
        "drc_unconnected_count": len(unconnected_items),
        "width_violation_count": len(width_violations),
        "target_net_width_violation_count": len(target_width_violations),
        "width_violation_types": sorted({str(item.get("type", "")) for item in width_violations}),
        "width_violation_messages": sorted(
            {str(item.get("description", "")) for item in width_violations}
        ),
        "width_violation_samples": list(width_violations[:3]),
        "report_path": str(report_path),
    }


def build_electrical_evidence(
    *,
    graph_id: str = "golden-design-1",
    revision: str,
    subject_node: str,
    envelope: ToolEnvelope,
    erc_errors: object,
    erc_unconnected: object,
    routing_converged: object,
    drc_errors: object,
    drc_unconnected: object,
    silkscreen_status: object,
    dfm_status: object,
    order_readiness_status: object,
    design_predicates: object,
    functional_block_contract: object,
    declared_blocks: object,
) -> Evidence:
    """Build electrical Evidence from completed deterministic gate results."""
    if not subject_node:
        raise ValueError("electrical evidence subject node is unknown (fail-closed)")
    if not isinstance(erc_errors, int) or not isinstance(erc_unconnected, int):
        raise ValueError("electrical ERC results are unknown (fail-closed)")
    if not isinstance(routing_converged, bool):
        raise ValueError("electrical routing result is unknown (fail-closed)")
    if not isinstance(drc_errors, int) or not isinstance(drc_unconnected, int):
        raise ValueError("electrical DRC results are unknown (fail-closed)")
    for name, value in (
        ("silkscreen", silkscreen_status),
        ("DFM", dfm_status),
        ("order readiness", order_readiness_status),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"electrical {name} result is unknown (fail-closed)")
    silkscreen = cast(str, silkscreen_status)
    dfm = cast(str, dfm_status)
    order_readiness = cast(str, order_readiness_status)
    if not isinstance(design_predicates, tuple):
        raise ValueError("electrical design predicates are unknown (fail-closed)")
    candidate_predicates = cast(tuple[object, ...], design_predicates)
    if not all(isinstance(item, PredicateResult) for item in candidate_predicates):
        raise ValueError("electrical design predicates are unknown (fail-closed)")
    typed_predicates = cast(tuple[PredicateResult, ...], design_predicates)
    names = tuple(predicate.name for predicate in typed_predicates)
    core_names = set(PREDICATE_CATALOG) - OPT_IN_PREDICATES
    if (
        len(names) != len(set(names))
        or not core_names.issubset(set(names))
        or not set(names).issubset(set(PREDICATE_CATALOG))
    ):
        raise ValueError("electrical design predicate set is incomplete (fail-closed)")
    for predicate in typed_predicates:
        if predicate.status not in {"pass", "not_applicable"}:
            raise GateError(f"{predicate.name}: status={predicate.status!r} ({predicate.detail})")
    candidate_blocks = cast(tuple[object, ...], declared_blocks)
    if (
        not isinstance(functional_block_contract, str)
        or not functional_block_contract
        or not isinstance(declared_blocks, tuple)
        or not declared_blocks
        or not all(isinstance(item, str) and item for item in candidate_blocks)
    ):
        raise ValueError("functional block evidence claims are unknown (fail-closed)")
    typed_declared_blocks = cast(tuple[str, ...], candidate_blocks)
    if envelope.target_revision != revision:
        raise ValueError("electrical evidence envelope revision mismatch (fail-closed)")
    if (
        erc_errors != 0
        or erc_unconnected != 0
        or not routing_converged
        or drc_errors != 0
        or drc_unconnected != 0
        or silkscreen_status != "measured_pass"
        or dfm_status != "pass"
        or order_readiness_status != "ready"
    ):
        raise ValueError("electrical deterministic gate did not pass (fail-closed)")
    predicate_claims = [
        EvidenceClaim(
            subject_node=subject_node,
            property=predicate.name,
            value=predicate.status,
            verified=predicate.status == "pass",
        )
        for predicate in typed_predicates
        if predicate.status != "not_applicable"
    ]
    return Evidence(
        evidence_id=evidence_id(graph_id, "electrical"),
        target_revision=revision,
        status="valid",
        envelope=envelope,
        claims=[
            EvidenceClaim(
                subject_node=subject_node,
                property="erc_error_count",
                value=erc_errors,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="functional_block_contract",
                value=functional_block_contract,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="declared_functional_blocks",
                value=",".join(sorted(typed_declared_blocks)),
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="erc_unconnected_count",
                value=erc_unconnected,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="routing_converged",
                value=routing_converged,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="drc_error_count",
                value=drc_errors,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="drc_unconnected_count",
                value=drc_unconnected,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="silkscreen_status",
                value=silkscreen,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="dfm_status",
                value=dfm,
                verified=True,
            ),
            EvidenceClaim(
                subject_node=subject_node,
                property="order_readiness_status",
                value=order_readiness,
                verified=True,
            ),
            *predicate_claims,
        ],
        created_at=datetime.now(UTC),
    )
