"""ACD event round-trip and fail-closed behavior on the SDK event model."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from openhands.sdk.event.base import Event
from pydantic import ValidationError

from acd_events import (
    AcdApprovalEvent,
    AcdCommitSideEffectReceiptEvent,
    AcdGateResultEvent,
    read_acd_event,
)
from acd_schema import (
    ApprovalPayload,
    CommitSideEffectReceiptPayload,
    GateResultPayload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "contracts"


def gate_result_event() -> AcdGateResultEvent:
    data = json.loads((FIXTURES / "valid" / "event-payload.json").read_text(encoding="utf-8"))
    return AcdGateResultEvent(source="environment", payload=GateResultPayload.model_validate(data))


def test_gate_result_event_roundtrip() -> None:
    event = gate_result_event()
    dumped = event.model_dump(mode="json")
    assert dumped["kind"] == "AcdGateResultEvent"
    restored = read_acd_event(dumped)
    assert restored == event
    # The SDK's polymorphic entrypoint resolves it too once this package is imported.
    assert Event.model_validate(dumped) == event


def test_approval_and_receipt_events_roundtrip() -> None:
    approval = AcdApprovalEvent(
        source="user",
        payload=ApprovalPayload(
            target_revision="r3", approval_id="ap-0001", subject="order-pcb", approved=True
        ),
    )
    receipt = AcdCommitSideEffectReceiptEvent(
        source="environment",
        payload=CommitSideEffectReceiptPayload(
            target_revision="r3", receipt_ref="receipt-0001", idempotency_key="order-r3-0001"
        ),
    )
    for event in (approval, receipt):
        assert read_acd_event(event.model_dump(mode="json")) == event


def test_unknown_event_kind_fails_closed() -> None:
    dumped = gate_result_event().model_dump(mode="json")
    dumped["kind"] = "AcdFutureEvent"
    with pytest.raises(ValueError, match="unknown ACD event kind"):
        read_acd_event(dumped)


def test_non_acd_sdk_event_kind_is_rejected() -> None:
    dumped = gate_result_event().model_dump(mode="json")
    dumped["kind"] = "MessageEvent"
    with pytest.raises(ValueError, match="unknown ACD event kind"):
        read_acd_event(dumped)


def test_unknown_payload_field_is_rejected() -> None:
    dumped = gate_result_event().model_dump(mode="json")
    payload = dumped["payload"]
    assert isinstance(payload, dict)
    payload["confidence"] = 0.99
    with pytest.raises(ValidationError):
        read_acd_event(dumped)


def test_unknown_event_payload_kind_fixture_is_rejected() -> None:
    bad_payload = json.loads(
        (FIXTURES / "invalid" / "event-payload-unknown-kind.json").read_text(encoding="utf-8")
    )
    dumped = gate_result_event().model_dump(mode="json")
    dumped["payload"] = bad_payload
    with pytest.raises(ValidationError):
        read_acd_event(dumped)


def test_readback_without_acd_import_fails_closed() -> None:
    """Reading an ACD event back through the SDK without importing acd_events raises."""
    dumped = gate_result_event().model_dump(mode="json")
    script = (
        "import json, sys\n"
        "from openhands.sdk.event.base import Event\n"
        "data = json.loads(sys.stdin.read())\n"
        "try:\n"
        "    Event.model_validate(data)\n"
        "except ValueError:\n"
        "    sys.exit(42)\n"
        "sys.exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(dumped),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 42, result.stderr
