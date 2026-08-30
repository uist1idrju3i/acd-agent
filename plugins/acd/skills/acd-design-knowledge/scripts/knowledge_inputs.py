# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@53b28a146b9dee957fd8dbaae9f5d9ab07f8bdc8",
# ]
# ///
"""Shared knowledge index, knowledge base and provenance helpers.

The design graph, rationale records, gate results, Evidence, generated documents
and git history are the only knowledge sources an answer may cite. Conversation
logs are internal only: a public audience never indexes them, and the exclusion
is recorded in the provenance instead of being left implicit. Every artifact
written here is an L3 observation with ``pass_evidence`` false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from acd.core.design_history import design_input_history, resolve_head_commit
from acd.core.knowledge_index import (
    KnowledgeIndexError,
    KnowledgeSourceLocation,
    build_knowledge_index,
    load_indexed_graph,
)
from acd.core.knowledge_qa import KnowledgeBase
from acd.core.troubleshooting import derive_troubleshooting_knowledge, load_pin_macros
from acd.schema.knowledge_index import KnowledgeAudience, KnowledgeIndex
from acd.schema.rationale import RationaleDocument

KNOWLEDGE_SCHEMA_VERSION = "0.1"
INDEX_NAME = "knowledge-index.json"
TROUBLESHOOTING_NAME = "troubleshooting-knowledge.json"


class KnowledgeInputError(ValueError):
    """Raised when the knowledge inputs cannot be resolved."""


@dataclass(frozen=True)
class KnowledgeInputPaths:
    """The declared locations of the knowledge sources on disk."""

    graph: Path
    rationale: Path | None
    documents: Path | None
    evidence: Path | None
    gate_results: Path | None
    conversation_logs: Path | None
    pins_header: Path | None
    repo_root: Path

    def locations(self) -> tuple[KnowledgeSourceLocation, ...]:
        declared = (
            ("rationale", self.rationale),
            ("gate_result", self.gate_results),
            ("evidence", self.evidence),
            ("generated_document", self.documents),
            ("conversation_log", self.conversation_logs),
        )
        return tuple(
            KnowledgeSourceLocation(kind=kind, path=path)  # type: ignore[arg-type]
            for kind, path in declared
            if path is not None
        )


def add_input_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the shared knowledge source arguments on a parser."""
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--rationale", type=Path)
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--gate-results", type=Path)
    parser.add_argument("--conversation-logs", type=Path)
    parser.add_argument("--pins-header", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())


def paths_from_args(args: argparse.Namespace) -> KnowledgeInputPaths:
    return KnowledgeInputPaths(
        graph=args.graph,
        rationale=args.rationale,
        documents=args.documents,
        evidence=args.evidence,
        gate_results=args.gate_results,
        conversation_logs=args.conversation_logs,
        pins_header=args.pins_header,
        repo_root=args.repo_root,
    )


def _load_rationale(path: Path | None) -> RationaleDocument | None:
    if path is None or not path.is_file():
        return None
    try:
        return RationaleDocument.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise KnowledgeInputError(f"rationale document {path} is not valid: {exc}") from exc


def _history_paths(paths: KnowledgeInputPaths, index: KnowledgeIndex) -> list[str]:
    tracked = {"design_graph", "rationale"}
    return [
        source.reference
        for source in index.sources
        if source.kind in tracked and source.status == "available"
    ]


def load_knowledge_base(
    paths: KnowledgeInputPaths, audience: KnowledgeAudience
) -> KnowledgeBase:
    """Build the knowledge index and resolve every indexed knowledge source."""
    try:
        graph = load_indexed_graph(paths.graph)
        index = build_knowledge_index(
            graph_path=paths.graph,
            locations=paths.locations(),
            audience=audience,
            base_dir=paths.repo_root,
            git_commit=resolve_head_commit(paths.repo_root),
        )
    except KnowledgeIndexError as exc:
        raise KnowledgeInputError(str(exc)) from exc
    macros = load_pin_macros(paths.pins_header) if paths.pins_header else {}
    troubleshooting = derive_troubleshooting_knowledge(graph, pin_macros=macros)
    return KnowledgeBase(
        index=index,
        graph=graph,
        rationale=_load_rationale(paths.rationale),
        troubleshooting=troubleshooting,
        history=design_input_history(
            paths.repo_root,
            _history_paths(paths, index),
            graph_path=relative_path(paths.graph, paths.repo_root),
        ),
    )


def sha256_file(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise KnowledgeInputError(f"cannot read {path}: {exc}") from exc


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def relative_path(path: Path, base_dir: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def dump_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_knowledge_artifact(
    *,
    artifact_kind: str,
    payload: object,
    out_dir: Path,
    name: str,
) -> Path:
    """Write a knowledge artifact as a non-authoritative JSON observation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(
        dump_json(
            {
                "schema_version": KNOWLEDGE_SCHEMA_VERSION,
                "artifact_kind": artifact_kind,
                "pass_evidence": False,
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    return path


def write_document_provenance(
    *,
    document_kind: str,
    document_path: Path,
    body: str,
    base: KnowledgeBase,
    generator: Path,
    base_dir: Path,
    excluded_kinds: list[str],
) -> Path:
    """Write the provenance record of a generated knowledge document."""
    provenance = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "artifact_kind": "generated_document",
        "pass_evidence": False,
        "document_kind": document_kind,
        "document_path": relative_path(document_path, base_dir),
        "document_hash": sha256_text(body),
        "graph_id": base.graph.graph_id,
        "target_revision": base.graph.revision,
        "audience": base.index.audience,
        "excluded_source_kinds": sorted(excluded_kinds),
        "generator": {"name": generator.name, "content_hash": sha256_file(generator)},
        "knowledge_sources": [
            source.model_dump(mode="json") for source in base.index.sources
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    provenance_path = document_path.with_name(f"{document_path.name}.provenance.json")
    provenance_path.write_text(dump_json(provenance), encoding="utf-8")
    return provenance_path


if __name__ == "__main__":  # pragma: no cover - dependency self-resolution check
    print("acd-design-knowledge shared inputs module")
