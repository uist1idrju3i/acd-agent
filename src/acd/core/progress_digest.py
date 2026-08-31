"""Surface the L3 records of a run so progress reaches the conversation.

A run already writes timing records and exploration reports under its output
directory, but reading them requires opening files the conversation never sees.
This module collects those records deterministically and renders them as text
plus a machine-readable report. Everything here stays an L3 observation: an
unreadable or hash-mismatched record is reported as ``unknown`` rather than
skipped, and no record ever grants pass authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from acd.schema.common import canonical_json_sha256
from acd.schema.progress_digest import (
    ProgressDigestReport,
    ProgressRecord,
    ProgressRecordKind,
)

TIMING_RECORD_NAME = "timing-record.json"
EXPLORATION_REPORT_SUFFIX = "exploration-report.json"
EXPLORATION_KINDS: frozenset[str] = frozenset(
    {
        "board_exploration_report",
        "enclosure_exploration_report",
        "firmware_exploration_report",
    }
)


def _load(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        body: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"record is unreadable: {exc}"
    if not isinstance(body, dict):
        return None, "record is not a JSON object"
    document = cast(dict[str, Any], body)
    declared = document.get("content_sha256")
    if isinstance(declared, str):
        expected = canonical_json_sha256(
            {key: value for key, value in document.items() if key != "content_sha256"}
        )
        if declared != expected:
            return None, "record content hash does not match its contents"
    return document, None


def _optional_str(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    return value if isinstance(value, str) and value else None


def _optional_int(document: Mapping[str, Any], key: str) -> int | None:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_bool(document: Mapping[str, Any], key: str) -> bool | None:
    value = document.get(key)
    return value if isinstance(value, bool) else None


def _timing_record(path: Path, document: Mapping[str, Any]) -> ProgressRecord:
    stages: object = document.get("stages")
    stage_list: list[object] = cast(list[object], stages) if isinstance(stages, list) else []
    durations: list[float] = []
    for stage in stage_list:
        if not isinstance(stage, dict):
            continue
        duration: object = cast(dict[str, Any], stage).get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, int | float):
            continue
        durations.append(float(duration))
    return ProgressRecord(
        kind="timing_record",
        path=str(path),
        status="read",
        target_revision=_optional_str(document, "target_revision"),
        stage_count=len(stage_list),
        duration_seconds=sum(durations),
    )


def _exploration_record(
    path: Path, document: Mapping[str, Any], kind: ProgressRecordKind
) -> ProgressRecord:
    return ProgressRecord(
        kind=kind,
        path=str(path),
        status="read",
        record_status=_optional_str(document, "status"),
        termination_reason=_optional_str(document, "termination_reason"),
        target_revision=_optional_str(document, "target_revision"),
        evaluated_candidates=_optional_int(document, "evaluated_candidates"),
        remaining_budget=_optional_int(document, "remaining_budget"),
        winner_candidate_id=_optional_str(document, "winner_candidate_id"),
        winner_written=_optional_bool(document, "winner_written"),
    )


def _record(path: Path) -> ProgressRecord:
    document, error = _load(path)
    if document is None:
        return ProgressRecord(
            kind="unknown",
            path=str(path),
            status="unknown",
            reason=error or "record is unreadable",
        )
    if path.name == TIMING_RECORD_NAME:
        return _timing_record(path, document)
    artifact_kind = _optional_str(document, "artifact_kind")
    if artifact_kind in EXPLORATION_KINDS:
        return _exploration_record(path, document, artifact_kind)  # pyright: ignore[reportArgumentType]
    return ProgressRecord(
        kind="unknown",
        path=str(path),
        status="unknown",
        reason=f"record artifact kind is unknown: {artifact_kind or 'absent'}",
    )


def collect_progress_digest(out_dir: Path) -> ProgressDigestReport:
    """Collect the timing and exploration records written under ``out_dir``."""
    if not out_dir.is_dir():
        return ProgressDigestReport(
            status="unknown",
            out_dir=str(out_dir),
            reason=f"output directory is missing: {out_dir}",
        )
    paths = sorted(
        {
            *out_dir.rglob(TIMING_RECORD_NAME),
            *out_dir.rglob(f"*{EXPLORATION_REPORT_SUFFIX}"),
        },
        key=str,
    )
    records = [_record(path) for path in paths]
    unreadable = sum(1 for record in records if record.status == "unknown")
    return ProgressDigestReport(
        status="unknown" if unreadable else "pass",
        out_dir=str(out_dir),
        records=records,
        unreadable_records=unreadable,
        reason=(
            f"{unreadable} progress record(s) could not be read" if unreadable else None
        ),
    )


def render_progress_digest(report: ProgressDigestReport) -> str:
    """Render the digest as conversation text without claiming pass authority."""
    lines = [
        f"ACD progress digest (L3 observation, not pass evidence): {report.status}",
        f"out_dir: {report.out_dir}",
    ]
    if report.reason is not None:
        lines.append(f"reason: {report.reason}")
    if not report.records:
        lines.append("no timing or exploration record found")
    for record in report.records:
        if record.status == "unknown":
            lines.append(f"- {record.path}: unknown ({record.reason})")
            continue
        if record.kind == "timing_record":
            lines.append(
                f"- {record.path}: {record.stage_count} stage(s), "
                f"{record.duration_seconds:.3f}s total"
            )
            continue
        lines.append(
            f"- {record.path}: {record.record_status}"
            f" ({record.termination_reason})"
            f", evaluated={record.evaluated_candidates}"
            f", remaining_budget={record.remaining_budget}"
            f", winner={record.winner_candidate_id}"
            f", winner_written={record.winner_written}"
        )
    return "\n".join(lines)


__all__ = [
    "collect_progress_digest",
    "render_progress_digest",
]
