"""Tests for the conversation-visible L3 progress digest."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.progress_digest import collect_progress_digest, render_progress_digest
from acd.schema.common import canonical_json_sha256


def _write(path: Path, body: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _exploration_body() -> dict[str, object]:
    return {
        "artifact_kind": "board_exploration_report",
        "status": "candidate_found",
        "termination_reason": "candidate_survived_gates",
        "target_revision": "rev-2",
        "evaluated_candidates": 2,
        "remaining_budget": 1,
        "winner_candidate_id": "candidate-2",
        "winner_written": True,
    }


def test_digest_collects_timing_and_exploration_records(tmp_path: Path) -> None:
    _write(tmp_path / "round-1" / "exploration-report.json", _exploration_body())
    _write(
        tmp_path / "round-1" / "timing-record.json",
        {
            "record_class": "L3",
            "pass_evidence": False,
            "target_revision": "rev-2",
            "stages": [
                {"name": "board[1/12]", "duration_seconds": 1.5},
                {"name": "board[2/12]", "duration_seconds": 0.5},
            ],
        },
    )
    report = collect_progress_digest(tmp_path)
    assert report.status == "pass"
    assert report.record_class == "L3"
    assert report.pass_evidence is False
    kinds = {record.kind: record for record in report.records}
    assert kinds["timing_record"].stage_count == 2
    assert kinds["timing_record"].duration_seconds == 2.0
    exploration = kinds["board_exploration_report"]
    assert exploration.record_status == "candidate_found"
    assert exploration.remaining_budget == 1
    assert exploration.winner_candidate_id == "candidate-2"
    text = render_progress_digest(report)
    assert "not pass evidence" in text
    assert "candidate_survived_gates" in text


def test_digest_reports_malformed_record_as_unknown(tmp_path: Path) -> None:
    (tmp_path / "exploration-report.json").write_text("{", encoding="utf-8")
    report = collect_progress_digest(tmp_path)
    assert report.status == "unknown"
    assert report.unreadable_records == 1
    assert report.records[0].kind == "unknown"
    assert report.reason is not None


def test_digest_rejects_hash_mismatch(tmp_path: Path) -> None:
    body = _exploration_body()
    body["content_sha256"] = canonical_json_sha256(body)
    body["remaining_budget"] = 5
    _write(tmp_path / "enclosure-exploration-report.json", body)
    report = collect_progress_digest(tmp_path)
    assert report.status == "unknown"
    assert report.records[0].status == "unknown"


def test_digest_reports_missing_out_dir_as_unknown(tmp_path: Path) -> None:
    report = collect_progress_digest(tmp_path / "absent")
    assert report.status == "unknown"
    assert report.records == []


def test_digest_reports_unknown_artifact_kind(tmp_path: Path) -> None:
    _write(tmp_path / "exploration-report.json", {"status": "candidate_found"})
    report = collect_progress_digest(tmp_path)
    assert report.status == "unknown"
    assert report.records[0].reason is not None
