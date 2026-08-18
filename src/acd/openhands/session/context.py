"""Non-authoritative ACD context memory and display-only event views."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from openhands.sdk.context.memory import MEMORY_INDEX_RELPATH, load_memory
from openhands.sdk.context.view import View
from openhands.sdk.conversation.secret_registry import SecretRegistry
from openhands.sdk.event.base import Event
from pydantic import JsonValue, TypeAdapter, ValidationError

from acd.openhands.safety.secrets import build_acd_secret_mapping
from acd.openhands.session.observation_store import (
    ObservationPayload,
    write_observation_payload,
)
from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.context import (
    ContextSource,
    EventViewCheckReport,
    EventViewEntry,
    EventViewProjection,
    MemoryContextObservation,
)

ACD_MEMORY_INDEX_RELPATH: Final[str] = MEMORY_INDEX_RELPATH
SECRET_MASK: Final[str] = "<secret-hidden>"

CONTEXT_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {"event_view_projection", "memory_context_observation"}
)

_JSON_OBJECT_ADAPTER: Final[TypeAdapter[dict[str, JsonValue]]] = TypeAdapter(
    dict[str, JsonValue]
)
_EVENT_LOG_ADAPTER: Final[TypeAdapter[list[Event]]] = TypeAdapter(list[Event])


class AcdContextError(ValueError):
    """Raised when context memory or an event view cannot be used safely."""


class AcdPassAuthorityError(AcdContextError):
    """Raised when context material is offered as pass authority."""


def reject_pass_authority(source: ContextSource) -> None:
    """Reject any attempt to derive a verdict from context material."""
    raise AcdPassAuthorityError(f"{source} must not be used as pass authority")


def assert_not_pass_authority(
    artifact: EventViewProjection | MemoryContextObservation,
) -> None:
    """Reject context artifacts on Evidence and pass-decision paths."""
    reject_pass_authority(artifact.source)


def is_context_artifact(payload: object) -> bool:
    """Return whether a loaded JSON payload is context material."""
    try:
        mapping = _JSON_OBJECT_ADAPTER.validate_python(payload)
    except ValidationError:
        return False
    kind = mapping.get("artifact_kind")
    return isinstance(kind, str) and kind in CONTEXT_ARTIFACT_KINDS


def _assert_secret_free(text: str, subject: str) -> None:
    """Reject text carrying allowlisted secret material."""
    if SECRET_MASK in text:
        raise AcdContextError(f"{subject} contains masked secret material")
    registry = SecretRegistry()
    registry.update_secrets(build_acd_secret_mapping())
    if registry.mask_secrets_in_output(text) != text:
        raise AcdContextError(f"{subject} contains secret material")


def _event_content_hash(event: Event) -> Sha256:
    try:
        return canonical_json_sha256(event.model_dump(mode="json"))
    except (TypeError, ValueError) as exc:
        raise AcdContextError("event view entry is not serializable") from exc


def event_view_projection_hash(projection: EventViewProjection) -> Sha256:
    """Return the canonical hash of an event view projection."""
    value = projection.model_dump(mode="json")
    value["canonical_hash"] = "unknown"
    return canonical_json_sha256(value)


def build_event_view(events: Sequence[Event]) -> View:
    """Build the SDK view for an EventLog without altering the log."""
    try:
        return View.from_events(events)
    except (TypeError, ValueError) as exc:
        raise AcdContextError("event view cannot be built") from exc


def event_view_projection(events: Sequence[Event]) -> EventViewProjection:
    """Project an EventLog into a display-only view reconciled with the log.

    Every displayed event must exist in the original EventLog with identical
    content: a view that cannot be reconciled fails closed instead of being
    displayed.
    """
    view = build_event_view(events)
    source_hashes = {event.id: _event_content_hash(event) for event in events}
    entries: list[EventViewEntry] = []
    for index, event in enumerate(view.events):
        source_hash = source_hashes.get(event.id)
        if source_hash is None:
            raise AcdContextError("event view entry is absent from the EventLog")
        content_hash = _event_content_hash(event)
        if content_hash != source_hash:
            raise AcdContextError("event view entry differs from the EventLog")
        entries.append(
            EventViewEntry(
                index=index,
                event_id=event.id,
                event_kind=type(event).__name__,
                content_hash=content_hash,
            )
        )
    projection = EventViewProjection(
        source_event_count=len(events),
        entries=entries,
    )
    return projection.model_copy(
        update={"canonical_hash": event_view_projection_hash(projection)}
    )


def validate_event_view_projection(
    projection: EventViewProjection,
    events: Sequence[Event],
) -> None:
    """Reject a projection that no longer matches its source EventLog."""
    if projection.canonical_hash != event_view_projection_hash(projection):
        raise AcdContextError("event view canonical hash is invalid")
    if projection != event_view_projection(events):
        raise AcdContextError("event view differs from the EventLog")


def load_event_log(path: Path) -> list[Event]:
    """Load a serialized EventLog, failing closed on unusable material."""
    try:
        return _EVENT_LOG_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError, ValueError) as exc:
        raise AcdContextError(f"EventLog is invalid: {path}") from exc


def load_event_view_projection(path: Path) -> EventViewProjection:
    """Load a tracked event view projection, failing closed when unusable."""
    try:
        return EventViewProjection.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError, ValueError) as exc:
        raise AcdContextError(f"event view is invalid: {path}") from exc


def event_view_check_report(
    projection: EventViewProjection,
    events: Sequence[Event],
) -> EventViewCheckReport:
    """Report whether a tracked view replays from its source EventLog."""
    try:
        validate_event_view_projection(projection, events)
    except AcdContextError as exc:
        return EventViewCheckReport(
            status="unknown",
            canonical_hash="unknown",
            reason=str(exc),
        )
    return EventViewCheckReport(
        status="pass",
        canonical_hash=projection.canonical_hash,
    )


def load_acd_memory_context(working_dir: str | Path) -> str | None:
    """Load persistent memory text for the working context only.

    The text is intended for prompt context. Secret contamination fails closed
    so that memory can never carry credential material into a conversation.
    """
    try:
        context = load_memory(working_dir)
    except (OSError, TypeError, ValueError) as exc:
        raise AcdContextError("memory context cannot be loaded") from exc
    if context is None:
        return None
    _assert_secret_free(context, "memory context")
    return context


def memory_context_observation(
    working_dir: str | Path,
) -> MemoryContextObservation:
    """Observe loaded memory by path and hash, never by content."""
    context = load_acd_memory_context(working_dir)
    if context is None:
        return MemoryContextObservation(char_count=0)
    index_paths: list[str] = []
    for root in (Path.home(), Path(working_dir)):
        index_path = root / ACD_MEMORY_INDEX_RELPATH
        if index_path.is_file():
            index_paths.append(ACD_MEMORY_INDEX_RELPATH)
            break
    if not index_paths:
        raise AcdContextError("memory context has no readable index")
    observation = MemoryContextObservation(
        index_paths=index_paths,
        char_count=len(context),
    )
    return observation.model_copy(
        update={"context_hash": canonical_json_sha256(context)}
    )


def write_memory_context_observation(
    working_dir: str | Path,
    path: Path,
) -> MemoryContextObservation:
    """Write the content-free memory observation as an L3 observation."""
    observation = memory_context_observation(working_dir)
    payload = ObservationPayload.model_validate(observation.model_dump(mode="json"))
    write_observation_payload(payload, path)
    return observation


def write_event_view_projection(
    events: Sequence[Event],
    path: Path,
) -> EventViewProjection:
    """Write the display-only event view as an L3 observation."""
    projection = event_view_projection(events)
    payload = ObservationPayload.model_validate(projection.model_dump(mode="json"))
    write_observation_payload(payload, path)
    return projection
