"""Deterministic stitch-candidate evidence tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.pipeline.stitch_candidate_evidence import (
    summarize_stitch_candidate_report,
    write_stitch_candidate_report,
)


def _report() -> dict[str, object]:
    return {
        "candidate_total": 2,
        "selected_count": 1,
        "exclusion_counts": {"keepout": 1, "inter_via_spacing": 0},
        "exclusion_combinations": {"keepout": 1},
        "board_edge_inset_basis": "inset",
        "footprint_clearance_method": "bbox",
        "candidates": [
            {
                "position_mm": [1.0, 2.0],
                "selected": True,
                "exclusion_reasons": [],
            },
            {
                "position_mm": [2.0, 2.0],
                "selected": False,
                "exclusion_reasons": ["keepout"],
            },
        ],
        "allowed_points_override": False,
        "selected_points": [[1.0, 2.0]],
    }


def test_summary_is_bounded_and_hash_linked() -> None:
    summary = summarize_stitch_candidate_report(_report())
    assert set(summary) == {
        "candidate_total",
        "selected_count",
        "exclusion_counts",
        "exclusion_combinations",
        "board_edge_inset_basis",
        "footprint_clearance_method",
        "fallback_used",
        "fallback_candidate_count",
        "fallback_excluded_count",
        "full_report_sha256",
    }


def test_writer_is_byte_deterministic(tmp_path: Path) -> None:
    payload: dict[str, Any] = {
        "schema_version": "0.1",
        "target_revision": "r1",
        "reports": [{"iteration": 0, "phase": "initial", "report": _report()}],
        "coverage_measurements": [
            {
                "iteration": 1,
                "via_count": 1,
                "uncovered_count": 0,
                "uncovered_vias": [],
            }
        ],
    }
    first = write_stitch_candidate_report(tmp_path, payload)
    first_bytes = first.read_bytes()
    first_hash = json.loads(first_bytes)["content_sha256"]
    second = write_stitch_candidate_report(tmp_path, payload)
    assert second.read_bytes() == first_bytes
    assert json.loads(second.read_bytes())["content_sha256"] == first_hash


def test_writer_rejects_malformed_report(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_stitch_candidate_report(
            tmp_path,
            {"reports": [{"iteration": 0, "phase": "initial", "report": {}}]},
        )


def test_summary_rejects_unsorted_candidates() -> None:
    report = _report()
    report["candidates"] = list(reversed(report["candidates"]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not sorted"):
        summarize_stitch_candidate_report(report)
