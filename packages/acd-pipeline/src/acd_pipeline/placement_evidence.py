"""Deterministic summaries for large placement evidence payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast


def summarize_placement_evidence(
    evidence: dict[str, Any],
    *,
    example_limit: int = 5,
) -> dict[str, Any]:
    """Keep acceptance data and a bounded, hash-linked rejection summary."""
    if example_limit <= 0:
        raise ValueError("example_limit must be positive")
    encoded = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    rejected_value: Any = evidence.get("rejected_candidates")
    rejected = rejected_value
    if not isinstance(rejected, list):
        raise ValueError("placement evidence rejected_candidates is malformed")
    counts: dict[str, int] = {}
    rejected_candidates = cast(list[Any], rejected)
    for candidate in rejected_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("placement evidence candidate is malformed")
        candidate_dict = cast(dict[str, Any], candidate)
        reason = candidate_dict.get("reason")
        if not isinstance(reason, str):
            raise ValueError("placement evidence reason is malformed")
        counts[reason] = counts.get(reason, 0) + 1
    summary: dict[str, Any] = {
        "summary_version": "1",
        "node_id": evidence.get("node_id"),
        "role": evidence.get("role"),
        "resolution": evidence.get("resolution", "accepted"),
        "accepted_position_mm": evidence.get("accepted_position_mm"),
        "accepted_rotation_deg": evidence.get("accepted_rotation_deg"),
        "placement_order": evidence.get("placement_order"),
        "rejection_counts": dict(sorted(counts.items())),
        "rejection_examples": rejected_candidates[:example_limit],
        "full_evidence_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    if not isinstance(summary["node_id"], str) or not isinstance(
        summary["resolution"], str
    ):
        raise ValueError("placement evidence identity is malformed")
    return summary
