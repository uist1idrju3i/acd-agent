"""Deterministic diagnostic evidence writers for pipeline gate observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acd.core.design_predicates import (
    PREDICATE_EVALUATION_STAGE,
    PredicateResult,
    PredicateStatus,
)
from acd.schema.common import canonical_json_sha256


def _aggregate_status(statuses: list[PredicateStatus]) -> PredicateStatus:
    if "unknown" in statuses:
        return "unknown"
    if "fail" in statuses:
        return "fail"
    return "pass"


def _write_payload(out_dir: Path, filename: str, payload: dict[str, Any]) -> Path:
    evidence_dir = out_dir / "gate-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["content_sha256"] = canonical_json_sha256(body)
    path = evidence_dir / filename
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_gate_evidence(
    out_dir: Path,
    filename: str,
    *,
    target_revision: str,
    gate: str,
    status: str,
    message: str,
    observation: dict[str, Any],
) -> Path:
    """Write one canonical diagnostic payload and return its relative artifact path."""
    return _write_payload(
        out_dir,
        filename,
        {
            "schema_version": "0.1",
            "target_revision": target_revision,
            "gate": gate,
            "status": status,
            "message": message,
            "observation": observation,
        },
    )


def write_design_predicate_evidence(
    out_dir: Path,
    revision: str,
    predicates: tuple[PredicateResult, ...],
) -> Path:
    """Write all predicate outcomes, including non-applicable outcomes."""
    statuses: list[PredicateStatus] = [predicate.status for predicate in predicates]
    status = _aggregate_status(statuses)
    observation = {
        "evaluation_stages": {
            predicate.name: PREDICATE_EVALUATION_STAGE[predicate.name]
            for predicate in sorted(predicates, key=lambda item: item.name)
        },
        "predicates": [
            {
                **predicate.model_dump(mode="json"),
                "evaluation_stage": PREDICATE_EVALUATION_STAGE[predicate.name],
            }
            for predicate in sorted(predicates, key=lambda item: item.name)
        ],
    }
    return write_gate_evidence(
        out_dir,
        "design-predicates.json",
        target_revision=revision,
        gate="design_predicates",
        status=status,
        message="design predicate diagnostic observations; not gate authority",
        observation=observation,
    )


def unavailable_observation(reason: Exception | str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": f"{type(reason).__name__}: {reason}"
        if isinstance(reason, Exception)
        else str(reason),
    }


__all__ = [
    "unavailable_observation",
    "write_design_predicate_evidence",
    "write_gate_evidence",
]
