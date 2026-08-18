"""Tests for fail-closed observation storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk import LLM
from openhands.sdk.conversation.conversation_stats import ConversationStats
from openhands.sdk.io import InMemoryFileStore
from openhands.sdk.llm.utils.metrics import Metrics

from acd.openhands.session.bootstrap import (
    write_conversation_metrics,
    write_conversation_stats,
)
from acd.openhands.session.goal_loop import AcdGoalResult, write_goal_result
from acd.openhands.session.observation_store import (
    AcdObservationStore,
    ObservationPayload,
    ObservationStoreError,
    write_observation_payload,
)
from acd.openhands.session.routing import (
    model_routing_policy_hash,
    write_model_routing_report,
)
from acd.schema.model_routing import ModelRoutingPolicy


def _policy() -> ModelRoutingPolicy:
    policy = ModelRoutingPolicy.model_validate(
        {
            "bindings": [
                {
                    "role": "agent",
                    "model": "agent-model",
                    "usage_id": "agent-usage",
                    "profile": "agent-profile",
                },
                {
                    "role": "judge",
                    "model": "judge-model",
                    "usage_id": "judge-usage",
                    "profile": "judge-profile",
                },
            ]
        }
    )
    return policy.model_copy(
        update={"canonical_hash": model_routing_policy_hash(policy)}
    )


def _payload() -> ObservationPayload:
    return ObservationPayload.model_validate(
        {
            "artifact_kind": "conversation_metrics",
            "pass_evidence": False,
            "description": "This is not pass evidence.",
            "metrics": Metrics().model_dump(mode="json"),
        }
    )


def test_in_memory_observation_bytes_are_deterministic() -> None:
    file_store = InMemoryFileStore()
    store = AcdObservationStore(file_store)
    payload = _payload()

    store.write("metrics.json", payload)
    first = file_store.read("metrics.json")
    store.write("metrics.json", payload)

    assert file_store.read("metrics.json") == first
    assert first.encode("utf-8") == (
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


@pytest.mark.parametrize(
    "path",
    ["", ".", "metrics/.", "../metrics.json", "/metrics.json", r"..\\metrics.json"],
)
def test_observation_store_rejects_unsafe_paths(path: str) -> None:
    store = AcdObservationStore(InMemoryFileStore())
    with pytest.raises(ObservationStoreError):
        store.write(path, _payload())


def test_observation_store_rejects_evidence_payload() -> None:
    with pytest.raises(ValueError):
        ObservationPayload.model_validate(
            {
                "artifact_kind": "conversation_metrics",
                "pass_evidence": True,
                "description": "not evidence",
            }
        )
    with pytest.raises(ValueError):
        ObservationPayload.model_validate(
            {
                "artifact_kind": "evidence",
                "pass_evidence": False,
                "description": "not evidence",
            }
        )


def test_explicit_store_supports_all_observation_writers() -> None:
    file_store = InMemoryFileStore()
    write_conversation_metrics(
        Metrics(),
        Path("metrics.json"),
        file_store=file_store,
    )
    write_goal_result(
        AcdGoalResult(
            objective="observe",
            status="complete",
            iterations=1,
            verdict=None,
            gate_passed=False,
            authoritative=False,
        ),
        Path("goal.json"),
        file_store=file_store,
    )
    routing_report = write_model_routing_report(
        _policy(),
        {
            "agent": LLM(model="agent-model", usage_id="agent-usage"),
            "judge": LLM(model="judge-model", usage_id="judge-usage"),
        },
        Path("routing.json"),
        file_store=file_store,
    )

    assert json.loads(file_store.read("metrics.json"))["pass_evidence"] is False
    assert json.loads(file_store.read("goal.json"))["artifact_kind"] == "goal_result"
    assert (
        json.loads(file_store.read("routing.json"))["artifact_kind"]
        == "model_routing_observation"
    )
    assert file_store.read("routing.json").encode("utf-8") == (
        json.dumps(
            routing_report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def test_existing_path_writer_keeps_legacy_json_bytes(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    write_conversation_metrics(Metrics(), path)
    expected = {
        "artifact_kind": "conversation_metrics",
        "description": "This is not pass evidence.",
        "metrics": Metrics().model_dump(mode="json"),
        "pass_evidence": False,
    }
    assert path.read_bytes() == (
        json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def test_stats_writer_uses_observation_store(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    stats = ConversationStats()
    write_conversation_stats(stats, path)
    snapshot = stats.model_dump(context={"use_snapshot": True})
    expected = {
        "artifact_kind": "conversation_stats",
        "combined_metrics": stats.get_combined_metrics().model_dump(mode="json"),
        "description": "This is not pass evidence.",
        "pass_evidence": False,
        "usage_to_metrics": snapshot["usage_to_metrics"],
    }
    assert path.read_bytes() == (
        json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["pass_evidence"] is False


def test_unavailable_store_root_fails_closed() -> None:
    class BrokenStore(InMemoryFileStore):
        def get_absolute_path(self, path: str) -> str:
            raise OSError("unavailable")

    with pytest.raises(ObservationStoreError):
        AcdObservationStore(BrokenStore())


def test_absolute_path_is_rejected_when_store_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(ObservationStoreError):
        write_observation_payload(
            _payload(),
            tmp_path / "metrics.json",
            file_store=InMemoryFileStore(),
        )
