"""Aggregate hook and confirmation rejections into an L3 observation.

Hook blocks surface as SDK ``UserRejectObservation`` events. Reviewing a run
otherwise requires reading the raw event stream, so this module summarizes the
blocks deterministically. The summary is an L3 observation: it never creates or
promotes Evidence, and it never turns a blocked run into a pass.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from openhands.sdk.event import Event, UserRejectObservation
from openhands.sdk.io import FileStore
from pydantic import ValidationError

from acd.openhands.session.observation_store import (
    ObservationPayload,
    write_observation_payload,
)
from acd.schema.rejection_summary import (
    RejectionGroup,
    RejectionSource,
    RejectionSummaryReport,
)

REJECTION_SUMMARY_ARTIFACT_KIND = "hook_rejection_summary"
UNKNOWN_PLACEHOLDER = "unknown"

_KNOWN_SOURCES: frozenset[str] = frozenset({"hook", "user"})


def _source(observation: UserRejectObservation) -> RejectionSource:
    raw = str(observation.rejection_source)
    return raw if raw in _KNOWN_SOURCES else "unknown"  # pyright: ignore[reportReturnType]


def _text(value: object) -> str:
    text = str(value).strip()
    return text or UNKNOWN_PLACEHOLDER


def summarize_rejections(events: Iterable[Event]) -> RejectionSummaryReport:
    """Group rejection observations by source, tool, and reason.

    Unknown rejection sources are reported as ``unknown`` rather than dropped so
    that a run with unreadable blocks never looks clean.
    """
    grouped: dict[tuple[RejectionSource, str, str], list[str]] = defaultdict(list)
    try:
        for event in events:
            if not isinstance(event, UserRejectObservation):
                continue
            key = (
                _source(event),
                _text(event.tool_name),
                _text(event.rejection_reason),
            )
            grouped[key].append(_text(event.action_id))
    except (AttributeError, TypeError, ValueError) as exc:
        return RejectionSummaryReport(status="unknown", reason=str(exc))

    groups: list[RejectionGroup] = []
    for source, tool_name, reason in sorted(grouped):
        action_ids = sorted(grouped[(source, tool_name, reason)])
        groups.append(
            RejectionGroup(
                source=source,
                tool_name=tool_name,
                reason=reason,
                count=len(action_ids),
                action_ids=action_ids,
            )
        )
    counts: dict[RejectionSource, int] = {"hook": 0, "user": 0, "unknown": 0}
    for group in groups:
        counts[group.source] += group.count
    try:
        return RejectionSummaryReport(
            status="pass",
            total=sum(counts.values()),
            hook_blocked=counts["hook"],
            user_rejected=counts["user"],
            unknown_source=counts["unknown"],
            groups=groups,
        )
    except ValidationError as exc:
        return RejectionSummaryReport(status="unknown", reason=str(exc))


def write_rejection_summary(
    events: Sequence[Event],
    path: Path,
    *,
    file_store: FileStore | None = None,
) -> RejectionSummaryReport:
    """Write the rejection summary as a non-authoritative observation."""
    report = summarize_rejections(events)
    payload = ObservationPayload.model_validate(
        {
            "artifact_kind": REJECTION_SUMMARY_ARTIFACT_KIND,
            "pass_evidence": False,
            "description": "This is not pass evidence.",
            "summary": report.model_dump(mode="json"),
        }
    )
    write_observation_payload(payload, path, file_store=file_store)
    return report


__all__ = [
    "REJECTION_SUMMARY_ARTIFACT_KIND",
    "summarize_rejections",
    "write_rejection_summary",
]
