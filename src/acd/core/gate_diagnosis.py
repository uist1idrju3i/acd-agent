"""Fail-closed summaries of diagnostic gate and exploration reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from acd.core.lane_preflight import run_lane_preflight
from acd.core.lane_recovery import resolve_lane_recovery
from acd.core.rationale import check_rationale_coverage
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.rationale import RationaleDocument


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


def _subject(predicate: dict[str, Any], remediation: dict[str, Any]) -> dict[str, Any]:
    subject: dict[str, Any] = {
        "predicate": predicate.get("name"),
        "status": predicate.get("status"),
        "change_dimensions": sorted(
            cast(list[str], remediation.get("change_dimensions", []))
        ),
    }
    for key in ("refdes", "target_refdes", "net", "node_id", "subject"):
        value = remediation.get(key)
        if isinstance(value, str):
            subject[key] = value
    return subject


def _fixture_rationale_coverage(fixture_dir: Path) -> dict[str, Any]:
    graph_path = fixture_dir / "graph.json"
    rationale_path = fixture_dir / "rationale.json"
    try:
        graph = DesignGraph.model_validate_json(
            graph_path.read_text(encoding="utf-8")
        )
        document = RationaleDocument.model_validate_json(
            rationale_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise GateDiagnosisError(
            f"fixture rationale inputs cannot be read: {fixture_dir}: {exc}"
        ) from exc
    report = check_rationale_coverage(graph, document)
    return {
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "status": report.status,
        "graph_id_match": report.graph_id_match,
        "revision_match": report.revision_match,
        "missing": [item.model_dump(mode="json") for item in report.missing],
        "stale": [item.model_dump(mode="json") for item in report.stale],
        "unclassified": [
            item.model_dump(mode="json") for item in report.unclassified
        ],
    }


def _fixture_lane_preflight(fixture_dir: Path) -> dict[str, Any]:
    graph_path = fixture_dir / "graph.json"
    try:
        graph = DesignGraph.model_validate_json(
            graph_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise GateDiagnosisError(
            f"fixture graph cannot be read: {graph_path}: {exc}"
        ) from exc
    return run_lane_preflight(graph).model_dump(mode="json")


def diagnose_gate_failure(
    out_dir: Path,
    fixture_dir: Path | None = None,
    lane_id: str | None = None,
) -> dict[str, Any]:
    """Read and summarize hashed gate-evidence and exploration artifacts.

    With a fixture directory the summary also carries the fixture-side rationale
    coverage and lane preflight declarations, and with a lane id it carries the
    declared recovery dimensions of that lane. All of it stays L3 observation:
    only deterministic gates decide a verdict.
    """
    if not out_dir.is_dir():
        raise GateDiagnosisError(f"output directory is missing: {out_dir}")
    evidence_paths = sorted((out_dir / "gate-evidence").glob("*.json"))
    exploration_paths = sorted(out_dir.glob("**/*exploration*report*.json"))
    report_paths = sorted(out_dir.glob("**/*stitch*report*.json"))
    paths = evidence_paths + exploration_paths + report_paths
    if not paths:
        raise GateDiagnosisError("no diagnostic artifacts found")
    failed_predicates: list[str] = []
    failed_subjects: list[dict[str, Any]] = []
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
                            failed_subjects.append(_subject(predicate, remediation))
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
    diagnosis: dict[str, Any] = {
        "artifact_kind": "gate_failure_diagnosis",
        "status": "diagnosed",
        "pass_evidence": False,
        "record_class": "L3",
        "failed_predicates": sorted(set(failed_predicates)),
        "failed_subjects": failed_subjects,
        "remediation_change_dimensions": sorted(remediation_dimensions),
        "unconnected_nets": sorted(unconnected_nets),
        "artifacts": artifacts,
    }
    if fixture_dir is not None:
        diagnosis["rationale_coverage"] = _fixture_rationale_coverage(fixture_dir)
        diagnosis["lane_preflight"] = _fixture_lane_preflight(fixture_dir)
    if lane_id is not None:
        plan = resolve_lane_recovery(lane_id)
        recovery = plan.as_diagnostic()
        recovery.pop("record_class", None)
        recovery.pop("pass_evidence", None)
        diagnosis["lane_recovery"] = recovery
        diagnosis["required_declarations"] = (
            []
            if plan.supported
            else [
                {
                    "lane_id": lane_id,
                    "declaration": "contracts/lane-recovery-declaration.json",
                    "next_step_action": plan.next_step_action,
                    "reason": plan.reason,
                }
            ]
        )
    return diagnosis


__all__ = ["GateDiagnosisError", "diagnose_gate_failure"]
