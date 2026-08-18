"""Structured, secret-free logging for non-authoritative ACD observations."""

from __future__ import annotations

import json
from typing import Final

from openhands.sdk.conversation.secret_registry import SecretRegistry
from openhands.sdk.logger import get_logger
from openhands.sdk.observability import observe
from pydantic import JsonValue, TypeAdapter, ValidationError

from acd.openhands.safety.secrets import build_acd_secret_mapping
from acd.schema.common import canonical_json_sha256
from acd.schema.observation import ObservationArtifactKind
from acd.schema.observation_log import ObservationLogRecord

ACD_OBSERVATION_LOGGER_NAME: Final[str] = "acd.observation"
OBSERVATION_LOG_SPAN_NAME: Final[str] = "acd.observation.write"
SECRET_MASK: Final[str] = "<secret-hidden>"

# Keys whose presence would give an observation pass authority or carry raw
# credential material. Observations are L3 only, so any of them fails closed.
FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "authoritative_evidence",
        "credential",
        "evidence",
        "evidence_hash",
        "evidence_path",
        "secret",
        "secrets",
        "supports_pass",
        "token",
    }
)

# Keys an observation may carry only while explicitly denying pass authority.
DENIED_AUTHORITY_KEYS: Final[frozenset[str]] = frozenset(
    {"authoritative", "pass_evidence"}
)

_OBSERVATION_ADAPTER: Final[TypeAdapter[dict[str, JsonValue]]] = TypeAdapter(
    dict[str, JsonValue]
)
_ARTIFACT_KIND_ADAPTER: Final[TypeAdapter[ObservationArtifactKind]] = TypeAdapter(
    ObservationArtifactKind
)

_logger = get_logger(ACD_OBSERVATION_LOGGER_NAME)


class ObservationLogError(ValueError):
    """Raised when an observation cannot be logged safely."""


def _assert_secret_free(serialized: str) -> None:
    """Reject payloads whose text carries allowlisted secret material.

    Detection goes through the SDK masking path, which is the canonical secret
    authority: any text the registry would mask must never reach the log.
    """
    if SECRET_MASK in serialized:
        raise ObservationLogError("observation payload contains masked secret material")
    registry = SecretRegistry()
    registry.update_secrets(build_acd_secret_mapping())
    if registry.mask_secrets_in_output(serialized) != serialized:
        raise ObservationLogError("observation payload contains secret material")


def _assert_no_pass_authority(value: JsonValue) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_PAYLOAD_KEYS:
                raise ObservationLogError(
                    f"observation payload must not carry pass authority: {key}"
                )
            if key in DENIED_AUTHORITY_KEYS and item is not False:
                raise ObservationLogError(
                    f"observation payload must declare {key} false"
                )
            _assert_no_pass_authority(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_pass_authority(item)


def redact_observation_payload(payload: dict[str, JsonValue]) -> list[str]:
    """Return the loggable field names after rejecting unsafe payloads.

    Field values are never returned: the structured log stream carries field
    names and hashes only.
    """
    if not payload:
        raise ObservationLogError("observation payload must not be empty")
    _assert_no_pass_authority(payload)
    try:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ObservationLogError("observation payload is not serializable") from exc
    _assert_secret_free(serialized)
    return sorted(payload)


def observation_log_record(
    payload: dict[str, JsonValue],
    store_path: str,
    contents: bytes,
    *,
    logger_name: str = ACD_OBSERVATION_LOGGER_NAME,
) -> ObservationLogRecord:
    """Build the structured log record describing one stored observation."""
    try:
        validated = _OBSERVATION_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ObservationLogError("observation payload is not JSON data") from exc
    fields = redact_observation_payload(validated)
    try:
        observation_kind = _ARTIFACT_KIND_ADAPTER.validate_python(
            validated.get("artifact_kind")
        )
    except ValidationError as exc:
        raise ObservationLogError("observation artifact kind is unknown") from exc
    try:
        return ObservationLogRecord(
            logger_name=logger_name,
            observation_kind=observation_kind,
            store_path=store_path,
            payload_hash=canonical_json_sha256(validated),
            payload_bytes=len(contents),
            payload_fields=fields,
        )
    except ValidationError as exc:
        raise ObservationLogError("observation log record is invalid") from exc


def observation_log_bytes(record: ObservationLogRecord) -> bytes:
    """Return the deterministic structured log bytes for one record."""
    return (
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


@observe(name=OBSERVATION_LOG_SPAN_NAME, ignore_input=True, ignore_output=True)
def emit_observation_log(record: ObservationLogRecord) -> None:
    """Emit one observation record through the SDK logger and observability path."""
    message = observation_log_bytes(record).decode("utf-8").rstrip("\n")
    try:
        _logger.info(
            message,
            extra={"acd_observation": record.model_dump(mode="json")},
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ObservationLogError("observation log emission failed") from exc
