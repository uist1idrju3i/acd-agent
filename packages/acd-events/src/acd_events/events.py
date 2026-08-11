"""ACD events carried on the OpenHands SDK ``EventLog``.

The SDK's ``Event`` base already provides id/timestamp/source and a ``kind``
discriminator (the subclass name). Reading these events back therefore
requires importing this package; without it, the SDK's discriminated-union
resolution raises instead of skipping or keeping the event opaque
(fail-closed). ``read_acd_event`` makes that contract explicit.
"""

from __future__ import annotations

from openhands.sdk.event.base import Event

from acd_schema import (
    ApprovalPayload,
    CommitSideEffectReceiptPayload,
    GateResultPayload,
)


class AcdGateResultEvent(Event):
    """Deterministic gate result for one gate on one revision."""

    payload: GateResultPayload


class AcdApprovalEvent(Event):
    """Recorded approval decision (never a pass verdict by itself)."""

    payload: ApprovalPayload


class AcdCommitSideEffectReceiptEvent(Event):
    """Reference to a receipt of an irreversible, committed side effect."""

    payload: CommitSideEffectReceiptPayload


AcdEvent = AcdGateResultEvent | AcdApprovalEvent | AcdCommitSideEffectReceiptEvent

_ACD_EVENT_TYPES: dict[str, type[Event]] = {
    cls.__name__: cls
    for cls in (AcdGateResultEvent, AcdApprovalEvent, AcdCommitSideEffectReceiptEvent)
}


def read_acd_event(data: dict[str, object]) -> AcdEvent:
    """Deserialize a stored ACD event, failing closed on unknown kinds.

    ``Event.model_validate`` resolves any registered SDK event subclass; this
    helper additionally rejects events whose ``kind`` is not a known ACD event,
    so callers cannot accidentally treat other SDK events (or unknown future
    ACD kinds) as ACD events.
    """
    kind = data.get("kind")
    event_type = _ACD_EVENT_TYPES.get(kind) if isinstance(kind, str) else None
    if event_type is None:
        raise ValueError(f"unknown ACD event kind: {kind!r} (fail-closed)")
    event = event_type.model_validate(dict(data))
    assert isinstance(
        event, AcdGateResultEvent | AcdApprovalEvent | AcdCommitSideEffectReceiptEvent
    )
    return event
