"""Tests for the design knowledge index contract and its construction."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from acd.core.knowledge_index import (
    KnowledgeIndexError,
    KnowledgeSourceLocation,
    build_knowledge_index,
    git_history_source,
)
from acd.schema.knowledge_index import (
    KnowledgeAudience,
    KnowledgeIndex,
    KnowledgeSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = REPO_ROOT / "fixtures/golden-design-1/graph.json"
RATIONALE_PATH = REPO_ROOT / "fixtures/golden-design-1/rationale.json"
COMMIT = "0" * 40


def _index(
    *,
    audience: KnowledgeAudience = "internal",
    locations: Sequence[KnowledgeSourceLocation] | None = None,
    git_commit: str = COMMIT,
) -> KnowledgeIndex:
    return build_knowledge_index(
        graph_path=GRAPH_PATH,
        locations=(
            locations
            if locations is not None
            else [KnowledgeSourceLocation(kind="rationale", path=RATIONALE_PATH)]
        ),
        audience=audience,
        base_dir=REPO_ROOT,
        git_commit=git_commit,
    )


def test_index_records_available_sources_with_hashes() -> None:
    index = _index()

    assert index.graph_id == "golden-design-1"
    assert index.target_revision == "r1"
    assert index.pass_evidence is False
    graph_sources = index.available("design_graph")
    assert len(graph_sources) == 1
    assert graph_sources[0].reference == "fixtures/golden-design-1/graph.json"
    assert graph_sources[0].content_hash.startswith("sha256:")
    assert index.available("rationale")
    assert index.unknown_sources() == ()


def test_index_records_missing_source_as_unknown(tmp_path: Path) -> None:
    index = _index(
        locations=[
            KnowledgeSourceLocation(kind="gate_result", path=tmp_path / "absent.json")
        ]
    )

    unknown = index.unknown_sources()
    assert [source.kind for source in unknown] == ["gate_result"]
    assert unknown[0].reason is not None
    assert index.available("gate_result") == ()


def test_public_index_excludes_conversation_logs(tmp_path: Path) -> None:
    log_path = tmp_path / "conversation.md"
    log_path.write_text("internal discussion\n", encoding="utf-8")

    index = _index(
        audience="public",
        locations=[KnowledgeSourceLocation(kind="conversation_log", path=log_path)],
    )

    assert index.excluded_kinds == ["conversation_log"]
    assert all(source.kind != "conversation_log" for source in index.sources)


def test_internal_index_keeps_conversation_logs(tmp_path: Path) -> None:
    log_path = tmp_path / "conversation.md"
    log_path.write_text("internal discussion\n", encoding="utf-8")

    index = _index(
        locations=[KnowledgeSourceLocation(kind="conversation_log", path=log_path)]
    )

    assert index.available("conversation_log")
    assert index.excluded_kinds == []


def test_directory_location_indexes_contained_documents(tmp_path: Path) -> None:
    documents = tmp_path / "docs"
    documents.mkdir()
    (documents / "b.md").write_text("second\n", encoding="utf-8")
    (documents / "a.md").write_text("first\n", encoding="utf-8")
    (documents / "ignored.svg").write_text("<svg/>\n", encoding="utf-8")

    index = _index(
        locations=[
            KnowledgeSourceLocation(kind="generated_document", path=documents)
        ]
    )

    references = [source.reference for source in index.available("generated_document")]
    assert [Path(reference).name for reference in references] == ["a.md", "b.md"]


def test_unresolved_git_commit_is_unknown() -> None:
    index = _index(git_commit="")

    unknown = [source.kind for source in index.unknown_sources()]
    assert unknown == ["git_history"]


def test_git_history_source_hashes_the_commit() -> None:
    source = git_history_source(COMMIT)

    assert source.status == "available"
    assert source.reference == f"git:{COMMIT}"
    assert source.content_hash.startswith("sha256:")


def test_malformed_graph_fails_closed(tmp_path: Path) -> None:
    broken = tmp_path / "graph.json"
    broken.write_text("{", encoding="utf-8")

    with pytest.raises(KnowledgeIndexError):
        build_knowledge_index(
            graph_path=broken,
            locations=[],
            audience="internal",
            base_dir=tmp_path,
            git_commit=COMMIT,
        )


def test_invalid_graph_payload_fails_closed(tmp_path: Path) -> None:
    broken = tmp_path / "graph.json"
    broken.write_text(json.dumps({"graph_id": "x"}), encoding="utf-8")

    with pytest.raises(KnowledgeIndexError):
        build_knowledge_index(
            graph_path=broken,
            locations=[],
            audience="internal",
            base_dir=tmp_path,
            git_commit=COMMIT,
        )


def test_unsorted_sources_are_rejected() -> None:
    sources = [
        KnowledgeSource(
            kind="rationale",
            reference="b.json",
            status="available",
            content_hash="sha256:" + "a" * 64,
        ),
        KnowledgeSource(
            kind="rationale",
            reference="a.json",
            status="available",
            content_hash="sha256:" + "b" * 64,
        ),
    ]

    with pytest.raises(ValueError, match="sorted"):
        KnowledgeIndex(
            graph_id="g",
            target_revision="r1",
            audience="internal",
            sources=sources,
        )


def test_public_index_must_record_exclusion() -> None:
    source = KnowledgeSource(
        kind="design_graph",
        reference="graph.json",
        status="available",
        content_hash="sha256:" + "a" * 64,
    )

    with pytest.raises(ValueError, match="excluded"):
        KnowledgeIndex(
            graph_id="g",
            target_revision="r1",
            audience="public",
            sources=[source],
        )


def test_unknown_source_requires_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        KnowledgeSource(kind="rationale", reference="a.json", status="unknown")


def test_available_source_requires_hash() -> None:
    with pytest.raises(ValueError, match="content hash"):
        KnowledgeSource(kind="rationale", reference="a.json", status="available")
