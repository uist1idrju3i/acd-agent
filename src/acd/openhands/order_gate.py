"""Deterministic pre-order gate checks at the OpenHands boundary."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openhands.sdk.git.exceptions import GitError

from acd.core.order_total import OrderTotalResult
from acd.openhands.evidence.git import design_input_changes, is_design_input
from acd.openhands.evidence.revision import resolve
from acd.schema import (
    DesignGraph,
    Evidence,
    EvidenceReference,
    OrderPolicy,
    PreOrderGateRecord,
)
from acd.schema.common import Timestamp, canonical_sha256, contains_unknown
from acd.schema.order_policy import (
    resolve_required_evidence_ids,
    validate_order_policy_for_graph,
)


class PreOrderGateError(ValueError):
    """Raised when the final pre-order gate cannot allow an order."""


def evaluate_pre_order_gate(
    *,
    repository: Path,
    policy: OrderPolicy,
    design_graph_path: Path,
    order_total: OrderTotalResult,
    evidence_paths: Sequence[Path],
    evaluated_at: Timestamp,
) -> PreOrderGateRecord:
    """Validate authoritative Evidence and the 7.2 total without side effects."""
    try:
        repository_root = repository.resolve()
    except OSError as exc:
        raise PreOrderGateError(
            f"repository path could not be resolved: {repository}"
        ) from exc
    candidate = (
        design_graph_path
        if design_graph_path.is_absolute()
        else repository / design_graph_path
    )
    try:
        graph_path = candidate.resolve()
        relative_path = graph_path.relative_to(repository_root).as_posix()
    except (OSError, ValueError) as exc:
        raise PreOrderGateError(
            f"design graph path must remain within repository: {design_graph_path}"
        ) from exc
    if not any(
        relative_path.startswith(f"{root}/") for root in policy.design_graph_roots
    ):
        raise PreOrderGateError("design graph path is outside declared policy roots")
    if not is_design_input(relative_path):
        raise PreOrderGateError("design graph path is not a design input")
    try:
        graph = DesignGraph.model_validate_json(
            graph_path.read_text(encoding="utf-8")
        )
        validate_order_policy_for_graph(policy, graph.graph_id)
    except (OSError, ValueError) as exc:
        raise PreOrderGateError(f"design graph policy validation failed: {exc}") from exc
    current_revision = resolve([graph_path])
    if current_revision is None:
        raise PreOrderGateError(
            "design graph paths must resolve exactly one valid revision"
        )
    try:
        changed_design_inputs = design_input_changes(repository, ref="HEAD")
    except GitError as exc:
        raise PreOrderGateError(f"git observation failed: {exc}") from exc
    if changed_design_inputs:
        raise PreOrderGateError("design input is dirty")
    if order_total.target_revision != current_revision:
        raise PreOrderGateError("order total target revision does not match")
    if (
        order_total.total.currency != policy.order_total_limit.currency
        or order_total.total.minor_unit_digits
        != policy.order_total_limit.minor_unit_digits
    ):
        raise PreOrderGateError("order total currency does not match policy limit")
    if order_total.total.amount_minor > policy.order_total_limit.amount_minor:
        raise PreOrderGateError("order total exceeds policy limit")

    evidence_by_id: dict[str, Evidence] = {}
    for path in evidence_paths:
        try:
            evidence = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PreOrderGateError(f"could not parse Evidence: {path}") from None
        if evidence.evidence_id in evidence_by_id:
            raise PreOrderGateError("duplicate Evidence identifier supplied")
        evidence_by_id[evidence.evidence_id] = evidence

    references: list[EvidenceReference] = []
    for evidence_id in sorted(
        resolve_required_evidence_ids(policy, graph.graph_id)
    ):
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise PreOrderGateError(f"required Evidence is missing: {evidence_id}")
        if not evidence.supports_authoritative_pass(current_revision):
            raise PreOrderGateError(
                f"Evidence does not support authoritative pass: {evidence_id}"
            )
        if any(
            not claim.verified or contains_unknown(claim.value)
            for claim in evidence.claims
        ):
            raise PreOrderGateError(
                f"Evidence claims are not fully verified: {evidence_id}"
            )
        references.append(
            EvidenceReference(
                evidence_id=evidence_id,
                canonical_hash=canonical_sha256(evidence),
            )
        )

    policy_hash = canonical_sha256(policy)
    return PreOrderGateRecord.create(
        target_revision=current_revision,
        total=order_total.total,
        upper_limit=policy.order_total_limit,
        breakdown_hash=order_total.breakdown_hash,
        evidence=references,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
    )
