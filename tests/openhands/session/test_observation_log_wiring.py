"""Tests for structured observation logging wired into the observation store."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from openhands.sdk.io import InMemoryFileStore

from acd.openhands.session.observation_log import (
    ACD_OBSERVATION_LOGGER_NAME,
    ObservationLogError,
    emit_observation_log,
    observation_log_bytes,
    observation_log_record,
)
from acd.openhands.session.observation_store import (
    AcdObservationStore,
    ObservationPayload,
    ObservationStoreError,
)

FIXTURE_PATH = Path("fixtures/observations/valid/conversation-metrics.json")


def _payload() -> ObservationPayload:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return ObservationPayload.model_validate(raw)


def test_store_write_returns_matching_log_record() -> None:
    store = AcdObservationStore(InMemoryFileStore())
    record = store.write("observations/metrics.json", _payload())
    stored = store.file_store.read("observations/metrics.json")
    assert record.store_path == "observations/metrics.json"
    assert record.payload_bytes == len(stored.encode("utf-8"))
    assert record.observation_kind == "conversation_metrics"
    assert record.pass_evidence is False


def test_store_write_is_reproducible() -> None:
    first = AcdObservationStore(InMemoryFileStore()).write(
        "observations/metrics.json", _payload()
    )
    second = AcdObservationStore(InMemoryFileStore()).write(
        "observations/metrics.json", _payload()
    )
    assert observation_log_bytes(first) == observation_log_bytes(second)


def test_store_write_failure_fails_closed() -> None:
    class FailingStore(InMemoryFileStore):
        def write(self, path: str, contents: str | bytes) -> None:
            raise OSError("write failed")

    store = AcdObservationStore(FailingStore())
    with pytest.raises(ObservationStoreError):
        store.write("observations/metrics.json", _payload())


def test_store_rejects_secret_contamination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACD_API_KEY", "acd-secret-token-value")
    payload = ObservationPayload.model_validate(
        {
            "artifact_kind": "conversation_metrics",
            "pass_evidence": False,
            "description": "leaked acd-secret-token-value",
        }
    )
    store = AcdObservationStore(InMemoryFileStore())
    with pytest.raises(ObservationLogError):
        store.write("observations/leaked.json", payload)
    assert store.file_store.list("") == []


def test_emitted_log_carries_record_without_payload_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = observation_log_record(
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
        "observations/metrics.json",
        b"{}\n",
    )
    with caplog.at_level(logging.INFO, logger=ACD_OBSERVATION_LOGGER_NAME):
        emit_observation_log(record)
    messages = [item.getMessage() for item in caplog.records]
    assert any(record.payload_hash in message for message in messages)
    assert all("observation-model" not in message for message in messages)
