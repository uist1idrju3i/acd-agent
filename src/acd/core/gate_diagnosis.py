"""Fail-closed summaries of diagnostic gate and exploration reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from acd.schema.common import canonical_json_sha256


class GateDiagnosisError(ValueError):
    """Raised when diagnostic artifacts cannot be trusted."""


def _load_hashed(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateDiagnosisError(f"diagnostic artifact is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise GateDiagnosisError(f"diagnostic artifact is not an object: {path}")
    payload = cast(dict[str, Any], value)
    content_hash = cast(str | None, payload.get("content_sha256"))
    body = dict(payload)
    body.pop("content_sha256", None)
    if content_hash != canonical_json_sha256(body):
        raise GateDiagnosisError(f"diagnostic artifact hash mismatch: {path}")
    return payload


def diagnose_gate_failure(out_dir: Path) -> dict[str, Any]:
    """Read and summarize hashed gate-evidence and exploration artifacts."""
    if not out_dir.is_dir():
        raise GateDiagnosisError(f"output directory is missing: {out_dir}")
    evidence_paths = sorted((out_dir / "gate-evidence").glob("*.json"))
    exploration_paths = sorted(out_dir.glob("**/*exploration*report*.json"))
    report_paths = sorted(out_dir.glob("**/*stitch*report*.json"))
    paths = evidence_paths + exploration_paths + report_paths
    if not paths:
        raise GateDiagnosisError("no diagnostic artifacts found")
    failed_predicates: list[str] = []
    remediation_dimensions: set[str] = set()
    unconnected_nets: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        value = _load_hashed(path)
        artifacts.append({"path": str(path), "content_sha256": value["content_sha256"]})
        observation = cast(dict[str, Any] | None, value.get("observation"))
        if isinstance(observation, dict):
            predicates = cast(list[Any] | None, observation.get("predicates"))
            if isinstance(predicates, list):
                for predicate in predicates:
                    if not isinstance(predicate, dict):
                        raise GateDiagnosisError(f"malformed predicate report: {path}")
                    predicate = cast(dict[str, Any], predicate)
                    if predicate.get("status") in {"fail", "unknown"}:
                        name = predicate.get("name")
                        if not isinstance(name, str):
                            raise GateDiagnosisError(f"malformed predicate name: {path}")
                        failed_predicates.append(name)
                        remediation = predicate.get("remediation")
                        if isinstance(remediation, dict):
                            remediation = cast(dict[str, Any], remediation)
                            raw_dimensions: object = remediation.get(
                                "change_dimensions", []
                            )
                            dimension_values = cast(list[object], raw_dimensions)
                            if not isinstance(raw_dimensions, list) or not all(
                                isinstance(item, str) for item in dimension_values
                            ):
                                raise GateDiagnosisError(
                                    f"malformed remediation dimensions: {path}"
                                )
                            dimensions = cast(list[str], raw_dimensions)
                            remediation_dimensions.update(dimensions)
            for key in ("unconnected_nets", "unconnected_net_ids"):
                raw_values: object = observation.get(key)
                values = cast(list[object] | None, raw_values)
                if values is not None:
                    net_values = cast(list[object], raw_values)
                    if not isinstance(raw_values, list) or not all(
                        isinstance(item, str) for item in net_values
                    ):
                        raise GateDiagnosisError(f"malformed unconnected nets: {path}")
                    unconnected_nets.update(
                        cast(list[str], net_values)
                    )
    return {
        "artifact_kind": "gate_failure_diagnosis",
        "status": "diagnosed",
        "pass_evidence": False,
        "record_class": "L3",
        "failed_predicates": sorted(set(failed_predicates)),
        "remediation_change_dimensions": sorted(remediation_dimensions),
        "unconnected_nets": sorted(unconnected_nets),
        "artifacts": artifacts,
    }


__all__ = ["GateDiagnosisError", "diagnose_gate_failure"]
