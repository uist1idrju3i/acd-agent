"""Tests for non-authoritative ACD context memory and display-only views."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from openhands.sdk.context.view import View
from openhands.sdk.event import MessageEvent
from openhands.sdk.event.base import Event
from openhands.sdk.llm import LLM, Message, TextContent
from pydantic import TypeAdapter

from acd.openhands.session.bootstrap import build_acd_conversation
from acd.openhands.session.context import (
    ACD_MEMORY_INDEX_RELPATH,
    AcdContextError,
    AcdPassAuthorityError,
    assert_not_pass_authority,
    event_view_projection,
    is_context_artifact,
    load_acd_memory_context,
    memory_context_observation,
    reject_pass_authority,
    validate_event_view_projection,
    write_event_view_projection,
    write_memory_context_observation,
)
from acd.openhands.session.gate_critic import AcdEvidenceRequirement, AcdGateCritic
from acd.openhands.session.observation_store import ObservationStoreError
from acd.schema.context import EventViewProjection, MemoryContextObservation

CONTEXT_FIXTURES = Path("fixtures/context")
EVENT_LOG_PATH = CONTEXT_FIXTURES / "valid/event-log.json"
EVENT_VIEW_PATH = CONTEXT_FIXTURES / "valid/event-view.json"
MEMORY_INDEX_PATH = CONTEXT_FIXTURES / "valid/memory-index.md"
SECRET_MEMORY_PATH = CONTEXT_FIXTURES / "invalid/memory-index-with-secret.md"
SECRET_PLACEHOLDER = "acd-memory-fixture-secret-placeholder"

_EVENTS_ADAPTER = TypeAdapter(list[Event])


def _events() -> list[Event]:
    return _EVENTS_ADAPTER.validate_python(
        json.loads(EVENT_LOG_PATH.read_text(encoding="utf-8"))
    )


def _tracked_projection() -> EventViewProjection:
    return EventViewProjection.model_validate_json(
        EVENT_VIEW_PATH.read_text(encoding="utf-8")
    )


def _memory_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: Path | None,
) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    def _home() -> Path:
        return home

    monkeypatch.setattr(Path, "home", staticmethod(_home))
    workspace = tmp_path / "workspace"
    index = workspace / ACD_MEMORY_INDEX_RELPATH
    index.parent.mkdir(parents=True)
    if source is not None:
        index.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return workspace


def test_event_view_matches_tracked_projection() -> None:
    assert event_view_projection(_events()) == _tracked_projection()


def test_event_view_is_reproducible_from_the_same_event_log() -> None:
    first = event_view_projection(_events())
    second = event_view_projection(_events())
    assert first == second
    assert first.canonical_hash == second.canonical_hash


def test_event_view_only_displays_events_kept_by_condensation() -> None:
    projection = event_view_projection(_events())
    assert projection.source_event_count == 3
    assert [entry.event_id for entry in projection.entries] == [
        "22222222-2222-4222-8222-222222222222"
    ]
    assert projection.pass_evidence is False


def test_event_view_validation_accepts_its_own_event_log() -> None:
    validate_event_view_projection(_tracked_projection(), _events())


def test_event_view_hash_mismatch_fails_closed() -> None:
    projection = EventViewProjection.model_validate_json(
        (CONTEXT_FIXTURES / "invalid/event-view-hash-mismatch.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(AcdContextError, match="canonical hash"):
        validate_event_view_projection(projection, _events())


def test_event_view_differing_from_the_event_log_fails_closed() -> None:
    events = _events()
    with pytest.raises(AcdContextError, match="differs from the EventLog"):
        validate_event_view_projection(_tracked_projection(), events[:1])


def test_event_view_entry_absent_from_the_event_log_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    injected = MessageEvent(
        source="agent",
        llm_message=Message(role="assistant", content=[TextContent(text="injected")]),
    )

    def _from_events(events: Sequence[Event]) -> View:
        del events
        return View(events=[injected])

    monkeypatch.setattr(View, "from_events", staticmethod(_from_events))
    with pytest.raises(AcdContextError, match="absent from the EventLog"):
        event_view_projection(_events())


def test_event_view_is_written_as_an_observation(tmp_path: Path) -> None:
    path = tmp_path / "event-view.json"
    projection = write_event_view_projection(_events(), path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert projection == _tracked_projection()
    assert stored["artifact_kind"] == "event_view_projection"
    assert stored["pass_evidence"] is False


def test_memory_context_is_loaded_for_the_working_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    context = load_acd_memory_context(workspace)
    assert context is not None
    assert "ACD project memory" in context


def test_memory_observation_records_paths_and_hash_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    observation = memory_context_observation(workspace)
    serialized = json.dumps(observation.model_dump(mode="json"), ensure_ascii=False)
    assert observation.index_paths == [ACD_MEMORY_INDEX_RELPATH]
    assert observation.char_count > 0
    assert observation.context_hash.startswith("sha256:")
    assert observation.pass_evidence is False
    assert "ACD project memory" not in serialized


def test_memory_observation_is_reproducible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    assert memory_context_observation(workspace) == memory_context_observation(
        workspace
    )


def test_absent_memory_index_yields_an_empty_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, None)
    assert load_acd_memory_context(workspace) is None
    observation = memory_context_observation(workspace)
    assert observation.char_count == 0
    assert observation.index_paths == []
    assert observation.context_hash == "unknown"


def test_memory_context_with_secret_material_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, SECRET_MEMORY_PATH)
    monkeypatch.setenv("LLM_API_KEY", SECRET_PLACEHOLDER)
    with pytest.raises(AcdContextError, match="secret material"):
        load_acd_memory_context(workspace)


def test_memory_observation_is_written_as_an_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    path = tmp_path / "memory.json"
    observation = write_memory_context_observation(workspace, path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["artifact_kind"] == "memory_context_observation"
    assert stored["pass_evidence"] is False
    assert stored["context_hash"] == observation.context_hash


def test_memory_observation_write_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    blocked = tmp_path / "blocked"
    blocked.write_text("", encoding="utf-8")
    with pytest.raises(ObservationStoreError):
        write_memory_context_observation(workspace, blocked / "memory.json")


def test_context_artifacts_are_never_pass_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    artifacts: list[EventViewProjection | MemoryContextObservation] = [
        event_view_projection(_events()),
        memory_context_observation(workspace),
    ]
    for artifact in artifacts:
        with pytest.raises(AcdPassAuthorityError, match="pass authority"):
            assert_not_pass_authority(artifact)


def test_pass_authority_rejection_is_explicit() -> None:
    with pytest.raises(AcdPassAuthorityError):
        reject_pass_authority("memory_index")


def test_context_artifact_detection() -> None:
    assert is_context_artifact(json.loads(EVENT_VIEW_PATH.read_text(encoding="utf-8")))
    assert not is_context_artifact(
        json.loads(
            Path("fixtures/contracts/valid/evidence.json").read_text(encoding="utf-8")
        )
    )
    assert not is_context_artifact(["event_view_projection"])


def test_gate_critic_rejects_context_material_as_evidence() -> None:
    critic = AcdGateCritic(
        requirements=[
            AcdEvidenceRequirement(
                path=CONTEXT_FIXTURES / "invalid/event-view-as-evidence.json",
                evidence_id="ev-erc-r3-0001",
            )
        ],
        repo_root=Path.cwd(),
    )
    result = critic.evaluate([])
    assert result.score == 0.0
    assert "context material is not pass evidence" in str(result.metadata)


def test_bootstrap_persistent_memory_rejects_secret_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, SECRET_MEMORY_PATH)
    monkeypatch.setenv("LLM_API_KEY", SECRET_PLACEHOLDER)
    with pytest.raises(AcdContextError, match="secret material"):
        build_acd_conversation(
            repo_root=Path.cwd(),
            llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
            requirements=[
                AcdEvidenceRequirement(
                    path=Path("fixtures/contracts/valid/evidence.json"),
                    evidence_id="ev-erc-r3-0001",
                )
            ],
            workspace=workspace,
            persistence_dir=tmp_path / "sessions",
            enable_persistent_memory=True,
        )


def test_bootstrap_persistent_memory_is_disabled_by_default(tmp_path: Path) -> None:
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
        requirements=[
            AcdEvidenceRequirement(
                path=Path("fixtures/contracts/valid/evidence.json"),
                evidence_id="ev-erc-r3-0001",
            )
        ],
        persistence_dir=tmp_path / "sessions",
    )
    assert conversation.agent.agent_context is not None
    assert conversation.agent.agent_context.load_memory is False


def test_bootstrap_enables_persistent_memory_on_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _memory_workspace(tmp_path, monkeypatch, MEMORY_INDEX_PATH)
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
        requirements=[
            AcdEvidenceRequirement(
                path=Path("fixtures/contracts/valid/evidence.json"),
                evidence_id="ev-erc-r3-0001",
            )
        ],
        workspace=workspace,
        persistence_dir=tmp_path / "sessions",
        enable_persistent_memory=True,
    )
    assert conversation.agent.agent_context is not None
    assert conversation.agent.agent_context.load_memory is True
