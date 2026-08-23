"""Deterministic evidence for stitch-via candidate selection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from acd.schema.common import canonical_json_sha256

_SUMMARY_KEYS = (
    "candidate_total",
    "selected_count",
    "exclusion_counts",
    "exclusion_combinations",
    "board_edge_inset_basis",
    "footprint_clearance_method",
)


def _validated_report(report: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in _SUMMARY_KEYS if key not in report]
    if missing:
        raise ValueError("stitch candidate report is missing: " + ", ".join(missing))
    for key in ("candidate_total", "selected_count"):
        value = report[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"stitch candidate report {key} is malformed")
    if not isinstance(report["exclusion_counts"], Mapping):
        raise ValueError("stitch candidate report exclusion_counts is malformed")
    if not isinstance(report["exclusion_combinations"], Mapping):
        raise ValueError("stitch candidate report exclusion_combinations is malformed")
    if not isinstance(report["board_edge_inset_basis"], str) or not report[
        "board_edge_inset_basis"
    ]:
        raise ValueError("stitch candidate report board_edge_inset_basis is malformed")
    if not isinstance(report["footprint_clearance_method"], str) or not report[
        "footprint_clearance_method"
    ]:
        raise ValueError("stitch candidate report footprint_clearance_method is malformed")
    candidates_value = report.get("candidates")
    if not isinstance(candidates_value, list):
        raise ValueError("stitch candidate report candidates is malformed")
    candidates = cast(list[object], candidates_value)
    if len(candidates) != report["candidate_total"]:
        raise ValueError("stitch candidate report candidate_total does not match candidates")
    previous: tuple[float, float] | None = None
    selected_candidate_count = 0
    for candidate_value in candidates:
        if not isinstance(candidate_value, Mapping):
            raise ValueError("stitch candidate report candidate is malformed")
        candidate = cast(Mapping[str, Any], candidate_value)
        position_value = candidate.get("position_mm")
        reasons_value = candidate.get("exclusion_reasons")
        selected = candidate.get("selected")
        if not isinstance(position_value, list):
            raise ValueError("stitch candidate report candidate fields are malformed")
        position = cast(list[object], position_value)
        if len(position) != 2 or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in position
        ):
            raise ValueError("stitch candidate report candidate fields are malformed")
        if not isinstance(reasons_value, list):
            raise ValueError("stitch candidate report candidate fields are malformed")
        reasons = cast(list[object], reasons_value)
        if any(not isinstance(reason, str) for reason in reasons):
            raise ValueError("stitch candidate report candidate fields are malformed")
        if not isinstance(selected, bool):
            raise ValueError("stitch candidate report candidate fields are malformed")
        x, y = position
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or isinstance(y, bool)
            or not isinstance(y, (int, float))
        ):
            raise ValueError("stitch candidate report candidate fields are malformed")
        point = (float(x), float(y))
        if previous is not None and point < previous:
            raise ValueError("stitch candidate report candidates are not sorted")
        previous = point
        if selected and reasons:
            raise ValueError("selected stitch candidate has exclusion reasons")
        if selected:
            selected_candidate_count += 1
    if (
        report.get("allowed_points_override") is not True
        and selected_candidate_count != report["selected_count"]
    ):
        raise ValueError("stitch candidate report selected_count does not match candidates")
    return dict(report)


def summarize_stitch_candidate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded summary embedded in the DFM report."""
    validated = _validated_report(report)
    return {
        **{key: validated[key] for key in _SUMMARY_KEYS},
        "full_report_sha256": canonical_json_sha256(validated),
    }


def _validate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    reports = payload.get("reports")
    if not isinstance(reports, list):
        raise ValueError("stitch candidate evidence reports must be a list")
    iterations: set[int] = set()
    normalized_reports: list[dict[str, Any]] = []
    for item_value in cast(list[object], reports):
        if not isinstance(item_value, Mapping):
            raise ValueError("stitch candidate evidence report entry is malformed")
        item = cast(Mapping[str, Any], item_value)
        iteration = item.get("iteration")
        phase = item.get("phase")
        report = item.get("report")
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
            raise ValueError("stitch candidate evidence iteration is malformed")
        if not isinstance(phase, str) or not phase:
            raise ValueError("stitch candidate evidence phase is malformed")
        if iteration in iterations:
            raise ValueError("stitch candidate evidence iterations must be unique")
        iterations.add(iteration)
        if not isinstance(report, Mapping):
            raise ValueError("stitch candidate evidence report is malformed")
        report_mapping = cast(Mapping[str, Any], report)
        normalized_reports.append(
            {
                "iteration": iteration,
                "phase": phase,
                "report": _validated_report(report_mapping),
            }
        )
    measurements = payload.get("coverage_measurements", [])
    if not isinstance(measurements, list):
        raise ValueError("stitch candidate coverage_measurements must be a list")
    for measurement_value in cast(list[object], measurements):
        if not isinstance(measurement_value, Mapping):
            raise ValueError("stitch candidate coverage measurement is malformed")
        measurement = cast(Mapping[str, Any], measurement_value)
        if "iteration" not in measurement or "uncovered_count" not in measurement:
            raise ValueError("stitch candidate coverage measurement is incomplete")
    return {**payload, "reports": sorted(normalized_reports, key=lambda item: item["iteration"])}


def write_stitch_candidate_report(out_dir: Path, payload: Mapping[str, Any]) -> Path:
    """Write one canonical stitch-candidate artifact and return its path."""
    body = _validate_payload(payload)
    body["content_sha256"] = canonical_json_sha256(body)
    path = out_dir / "stitch-candidate-report.json"
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = ["summarize_stitch_candidate_report", "write_stitch_candidate_report"]
