"""Regression tests for structured, secret-free observation logging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

from acd.openhands.session.observation_log import (
    ObservationLogError,
    observation_log_bytes,
    observation_log_record,
)
from acd.schema.observation_log import ObservationLogRecord

REPO_ROOT = Path(__file__).parents[2]
OBSERVATION_FIXTURES = REPO_ROOT / "fixtures/observations"
_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(
    dict[str, JsonValue]
)


def _load_payload(kind: str, name: str) -> dict[str, JsonValue]:
    raw = (OBSERVATION_FIXTURES / kind / name).read_text(encoding="utf-8")
    return _PAYLOAD_ADAPTER.validate_python(json.loads(raw))


def _store_bytes(payload: dict[str, JsonValue]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def test_expected_record_matches_tracked_fixture() -> None:
    payload = _load_payload("valid", "conversation-metrics.json")
    record = observation_log_record(
        payload,
        "observations/conversation-metrics.json",
        _store_bytes(payload),
    )
    expected = json.loads(
        (OBSERVATION_FIXTURES / "valid/conversation-metrics.log.json").read_text(
            encoding="utf-8"
        )
    )
    assert record.model_dump(mode="json") == expected


def test_log_bytes_are_deterministic() -> None:
    payload = _load_payload("valid", "conversation-metrics.json")
    contents = _store_bytes(payload)
    first = observation_log_record(payload, "observations/metrics.json", contents)
    second = observation_log_record(payload, "observations/metrics.json", contents)
    assert observation_log_bytes(first) == observation_log_bytes(second)
    assert first.payload_hash == second.payload_hash


def test_log_record_withholds_payload_values() -> None:
    payload = _load_payload("valid", "conversation-metrics.json")
    contents = _store_bytes(payload)
    record = observation_log_record(payload, "observations/metrics.json", contents)
    emitted = observation_log_bytes(record).decode("utf-8")
    assert "observation-model" not in emitted
    assert record.payload_fields == [
        "artifact_kind",
        "description",
        "metrics",
        "pass_evidence",
    ]
    assert record.pass_evidence is False


@pytest.mark.parametrize(
    "name",
    [
        "unknown-artifact-kind.json",
        "pass-evidence-true.json",
        "evidence-field.json",
        "authoritative-goal-result.json",
    ],
)
def test_unsafe_payloads_fail_closed(name: str) -> None:
    payload = _load_payload("invalid", name)
    with pytest.raises(ObservationLogError):
        observation_log_record(payload, "observations/rejected.json", b"{}\n")


def test_secret_material_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACD_API_KEY", "acd-secret-token-value")
    payload = _load_payload("valid", "conversation-metrics.json")
    payload["description"] = "leaked acd-secret-token-value"
    with pytest.raises(ObservationLogError):
        observation_log_record(payload, "observations/leaked.json", b"{}\n")


def test_masked_secret_marker_fails_closed() -> None:
    payload = _load_payload("valid", "conversation-metrics.json")
    payload["description"] = "value <secret-hidden>"
    with pytest.raises(ObservationLogError):
        observation_log_record(payload, "observations/masked.json", b"{}\n")


def test_log_record_rejects_unsorted_fields() -> None:
    payload = _load_payload("valid", "conversation-metrics.json")
    record = observation_log_record(payload, "observations/metrics.json", b"{}\n")
    dumped = record.model_dump(mode="json")
    dumped["payload_fields"] = ["metrics", "artifact_kind"]
    with pytest.raises(ValueError):
        ObservationLogRecord.model_validate(dumped)
