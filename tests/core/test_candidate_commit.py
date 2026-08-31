"""Tests for the atomic accepted-candidate commit path."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from acd.core.candidate_commit import CandidateCommitError, commit_candidate_graph
from acd.schema import RationaleDocument
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    for name in ("graph.json", "requirements.json", "rationale.json"):
        (fixture / name).write_text(
            (FIXTURE / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return fixture


def _changed_graph(fixture: Path) -> DesignGraph:
    """Change one graph attribute that an existing rationale record covers."""
    graph = DesignGraph.model_validate_json(
        (fixture / "graph.json").read_text(encoding="utf-8")
    )
    document = RationaleDocument.model_validate_json(
        (fixture / "rationale.json").read_text(encoding="utf-8")
    )
    targets = {
        (node_id, attr)
        for record in document.records
        for node_id in record.subject_nodes
        for attr in record.subject_attrs
    }
    nodes: list[Any] = []
    mutated = False
    for node in graph.nodes:
        attrs = dict(node.attrs)
        for attr, value in attrs.items():
            if (node.id, attr) in targets and isinstance(value, (int, float)) and not (
                isinstance(value, bool)
            ):
                attrs[attr] = float(value) + 0.5
                mutated = True
                break
        else:
            nodes.append(node)
            continue
        nodes.append(node.model_copy(update={"attrs": attrs}))
    assert mutated
    return graph.model_copy(update={"nodes": nodes})


def test_commit_refreshes_rationale_and_writes_both_documents(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = RationaleDocument.model_validate_json(
        (fixture / "rationale.json").read_text(encoding="utf-8")
    )
    graph = _changed_graph(fixture)

    report = commit_candidate_graph(graph, fixture / "graph.json", fixture)

    after = RationaleDocument.model_validate_json(
        (fixture / "rationale.json").read_text(encoding="utf-8")
    )
    assert report["pass_evidence"] is False
    assert report["target_revision"] == graph.revision
    assert report["rationale_records"] == len(after.records)
    assert len(after.records) == len(before.records)
    assert all(record.target_revision == graph.revision for record in after.records)
    written = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    assert written["revision"] == graph.revision
    changed = {
        record.rationale_id
        for record, previous in zip(after.records, before.records, strict=True)
        if record.subject_hash != previous.subject_hash
    }
    assert changed


def test_missing_rationale_document_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    graph = _changed_graph(fixture)
    (fixture / "rationale.json").unlink()

    with pytest.raises(CandidateCommitError, match="rationale document is missing"):
        commit_candidate_graph(graph, fixture / "graph.json", fixture)


def test_malformed_rationale_document_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    graph = _changed_graph(fixture)
    (fixture / "rationale.json").write_text("{", encoding="utf-8")

    with pytest.raises(CandidateCommitError, match="rationale document is invalid"):
        commit_candidate_graph(graph, fixture / "graph.json", fixture)


def test_rationale_subject_removed_by_the_candidate_fails_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    graph = _changed_graph(fixture)
    document = RationaleDocument.model_validate_json(
        (fixture / "rationale.json").read_text(encoding="utf-8")
    )
    subject_nodes = {
        node_id for record in document.records for node_id in record.subject_nodes
    }
    pruned = [node for node in graph.nodes if node.id not in subject_nodes]
    assert len(pruned) < len(graph.nodes)

    with pytest.raises(CandidateCommitError, match="rationale could not be refreshed"):
        commit_candidate_graph(
            graph.model_copy(update={"nodes": pruned}), fixture / "graph.json", fixture
        )


def test_rationale_write_failure_restores_the_previous_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    original = (fixture / "graph.json").read_text(encoding="utf-8")
    original_rationale = (fixture / "rationale.json").read_text(encoding="utf-8")
    real_replace = os.replace
    calls: list[str] = []

    def flaky_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        calls.append(str(dst))
        if str(dst).endswith("rationale.json"):
            raise OSError("rationale replace failed")
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(CandidateCommitError, match="could not be written"):
        commit_candidate_graph(
            _changed_graph(fixture), fixture / "graph.json", fixture
        )

    monkeypatch.undo()
    assert len(calls) == 2
    assert (fixture / "graph.json").read_text(encoding="utf-8") == original
    assert (fixture / "rationale.json").read_text(encoding="utf-8") == original_rationale
    assert not list(fixture.glob("*.tmp"))
