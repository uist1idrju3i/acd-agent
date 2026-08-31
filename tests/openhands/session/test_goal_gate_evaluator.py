"""Tests for the deterministic Evidence gate evaluator of the goal loop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest
from openhands.sdk.conversation.base import BaseConversation

from acd.openhands.session.goal_loop import build_evidence_gate_evaluator
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim, EvidenceStatus
from acd.schema.tool_envelope import ToolEnvelope

GRAPH_PATH = Path("fixtures/golden-design-1/graph.json")
CONTAINER_DIGEST = "sha256:" + "e" * 64


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _evidence(
    revision: str,
    *,
    context: Literal["container", "host", "unknown"] = "container",
    digest: str | None = CONTAINER_DIGEST,
    status: EvidenceStatus = "valid",
) -> Evidence:
    now = datetime.now(UTC)
    envelope = ToolEnvelope(
        tool_name="kicad-cli",
        tool_version="10.0.5",
        format_version="json",
        config_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        output_hash="sha256:" + "c" * 64,
        execution_env=f"linux-x86_64; container={digest or 'none'}",
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions="test",
        convergence_state="converged",
        target_revision=revision,
        started_at=now,
        finished_at=now,
        exit_code=0,
    )
    return Evidence(
        evidence_id="ev.gd1.electrical",
        target_revision=revision,
        status=status,
        envelope=envelope,
        claims=[
            EvidenceClaim(
                subject_node="board.gd1",
                property="erc_errors",
                value=0,
                verified=True,
            )
        ],
        created_at=now,
    )


def _write(path: Path, evidence: Evidence) -> Path:
    path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    return path


def _conversation() -> BaseConversation:
    return cast(BaseConversation, object())


def _graph_copy(tmp_path: Path) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_authoritative_evidence_of_current_revision_passes(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    evidence_path = _write(
        tmp_path / "evidence.json", _evidence(_graph().revision)
    )

    evaluate = build_evidence_gate_evaluator(graph_path, [evidence_path])

    assert evaluate(_conversation()) == (True, True)


def test_stale_revision_fails_closed(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    evidence_path = _write(tmp_path / "evidence.json", _evidence("r999"))

    evaluate = build_evidence_gate_evaluator(graph_path, [evidence_path])

    assert evaluate(_conversation()) == (False, False)


def test_provisional_host_evidence_fails_closed(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    evidence_path = _write(
        tmp_path / "evidence.json",
        _evidence(_graph().revision, context="host", digest=None),
    )

    evaluate = build_evidence_gate_evaluator(graph_path, [evidence_path])

    assert evaluate(_conversation()) == (False, False)


def test_unknown_container_digest_fails_closed(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    evidence_path = _write(
        tmp_path / "evidence.json",
        _evidence(_graph().revision, digest="unknown"),
    )

    evaluate = build_evidence_gate_evaluator(graph_path, [evidence_path])

    assert evaluate(_conversation()) == (False, False)


def test_one_invalid_record_fails_the_whole_evaluation(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    revision = _graph().revision
    first = _write(tmp_path / "a.json", _evidence(revision))
    second = _write(
        tmp_path / "b.json", _evidence(revision, status="stale")
    )

    evaluate = build_evidence_gate_evaluator(graph_path, [first, second])

    assert evaluate(_conversation()) == (False, False)


def test_missing_and_malformed_evidence_fail_closed(tmp_path: Path) -> None:
    graph_path = _graph_copy(tmp_path)
    missing = tmp_path / "missing.json"

    assert build_evidence_gate_evaluator(graph_path, [missing])(
        _conversation()
    ) == (False, False)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert build_evidence_gate_evaluator(graph_path, [malformed])(
        _conversation()
    ) == (False, False)


def test_evaluator_requires_declared_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one Evidence path"):
        build_evidence_gate_evaluator(_graph_copy(tmp_path), [])
