"""Tests for the non-authoritative hook rejection summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.event import UserRejectObservation
from openhands.sdk.event.llm_convertible import MessageEvent
from openhands.sdk.llm import Message, TextContent

from acd.openhands.session.rejection_summary import (
    summarize_rejections,
    write_rejection_summary,
)
from acd.schema.rejection_summary import RejectionGroup, RejectionSummaryReport


def _rejection(
    *,
    tool_name: str,
    reason: str,
    source: str,
    action_id: str,
) -> UserRejectObservation:
    return UserRejectObservation(
        tool_name=tool_name,
        tool_call_id=f"call-{action_id}",
        rejection_reason=reason,
        rejection_source=source,  # pyright: ignore[reportArgumentType]
        action_id=action_id,
    )


def _message() -> MessageEvent:
    return MessageEvent(
        source="agent",
        llm_message=Message(role="assistant", content=[TextContent(text="hello")]),
    )


def test_summary_without_rejections_is_empty() -> None:
    report = summarize_rejections([_message()])
    assert report.status == "pass"
    assert report.total == 0
    assert report.groups == []
    assert report.pass_evidence is False


def test_summary_groups_by_source_tool_and_reason() -> None:
    events = [
        _rejection(
            tool_name="execute_bash",
            reason="derived projection is protected",
            source="hook",
            action_id="a2",
        ),
        _rejection(
            tool_name="execute_bash",
            reason="derived projection is protected",
            source="hook",
            action_id="a1",
        ),
        _rejection(
            tool_name="str_replace_editor",
            reason="order evidence is required",
            source="hook",
            action_id="a3",
        ),
        _rejection(
            tool_name="execute_bash",
            reason="User rejected the action",
            source="user",
            action_id="a4",
        ),
        _message(),
    ]
    report = summarize_rejections(events)
    assert report.status == "pass"
    assert report.total == 4
    assert report.hook_blocked == 3
    assert report.user_rejected == 1
    assert report.unknown_source == 0
    assert [(group.source, group.tool_name, group.count) for group in report.groups] == [
        ("hook", "execute_bash", 2),
        ("hook", "str_replace_editor", 1),
        ("user", "execute_bash", 1),
    ]
    assert report.groups[0].action_ids == ["a1", "a2"]


def test_unknown_rejection_source_is_reported_not_dropped() -> None:
    """A source outside the pinned SDK literal must not be silently dropped."""
    event = _rejection(
        tool_name="execute_bash",
        reason="blocked",
        source="hook",
        action_id="a1",
    )
    unknown_source = event.model_copy(update={"rejection_source": "external"})
    report = summarize_rejections([unknown_source])
    assert report.total == 1
    assert report.unknown_source == 1
    assert report.groups[0].source == "unknown"


def test_write_rejection_summary_persists_non_authoritative_observation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rejections.json"
    report = write_rejection_summary(
        [
            _rejection(
                tool_name="execute_bash",
                reason="gate is required after an input change",
                source="hook",
                action_id="a1",
            )
        ],
        path,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert report.hook_blocked == 1
    assert document["artifact_kind"] == "hook_rejection_summary"
    assert document["pass_evidence"] is False
    assert document["summary"]["hook_blocked"] == 1
    assert document["summary"]["pass_evidence"] is False


def test_report_rejects_inconsistent_totals() -> None:
    group = RejectionGroup(
        source="hook",
        tool_name="execute_bash",
        reason="blocked",
        count=1,
        action_ids=["a1"],
    )
    with pytest.raises(ValueError):
        RejectionSummaryReport(status="pass", total=2, hook_blocked=2, groups=[group])


def test_report_rejects_unsorted_groups() -> None:
    first = RejectionGroup(
        source="user",
        tool_name="execute_bash",
        reason="blocked",
        count=1,
        action_ids=["a1"],
    )
    second = RejectionGroup(
        source="hook",
        tool_name="execute_bash",
        reason="blocked",
        count=1,
        action_ids=["a2"],
    )
    with pytest.raises(ValueError):
        RejectionSummaryReport(
            status="pass",
            total=2,
            hook_blocked=1,
            user_rejected=1,
            groups=[first, second],
        )


def test_report_rejects_pass_with_reason() -> None:
    with pytest.raises(ValueError):
        RejectionSummaryReport(status="pass", reason="explained")


def test_report_requires_reason_when_unknown() -> None:
    with pytest.raises(ValueError):
        RejectionSummaryReport(status="unknown")
