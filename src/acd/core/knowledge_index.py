"""Deterministic construction of the design knowledge index.

The index is built from the authoritative design graph plus the declared
knowledge source locations. Resolution is fail-closed for the graph itself:
without a valid graph there is no revision to answer questions for. Every other
declared source that cannot be read is recorded as ``unknown`` with a reason so
an answering path can say "unknown" instead of assuming the source was empty.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.knowledge_index import (
    INTERNAL_ONLY_KINDS,
    KnowledgeAudience,
    KnowledgeIndex,
    KnowledgeSource,
    KnowledgeSourceKind,
)

# Only these file types are indexed when a declared location is a directory.
INDEXED_SUFFIXES: tuple[str, ...] = (".json", ".md")


class KnowledgeIndexError(ValueError):
    """Raised when the knowledge index cannot be built."""


@dataclass(frozen=True)
class KnowledgeSourceLocation:
    """A declared knowledge source location on disk."""

    kind: KnowledgeSourceKind
    path: Path


def _file_hash(path: Path) -> Sha256:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, base_dir: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_indexed_graph(path: Path) -> DesignGraph:
    """Load the design graph the index is anchored to, failing closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KnowledgeIndexError(f"cannot read design graph {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeIndexError(f"design graph {path} is not valid JSON: {exc}") from exc
    try:
        return DesignGraph.model_validate(payload)
    except ValueError as exc:
        raise KnowledgeIndexError(f"design graph {path} is not valid: {exc}") from exc


def _expand(location: KnowledgeSourceLocation) -> tuple[Path, ...]:
    if location.path.is_dir():
        return tuple(
            sorted(
                item
                for item in location.path.rglob("*")
                if item.is_file() and item.suffix in INDEXED_SUFFIXES
            )
        )
    return (location.path,)


def _resolve_file(
    kind: KnowledgeSourceKind, path: Path, base_dir: Path
) -> KnowledgeSource:
    reference = _relative(path, base_dir)
    if not path.is_file():
        return KnowledgeSource(
            kind=kind,
            reference=reference,
            status="unknown",
            reason="declared knowledge source is missing",
        )
    try:
        content_hash = _file_hash(path)
    except OSError as exc:
        return KnowledgeSource(
            kind=kind,
            reference=reference,
            status="unknown",
            reason=f"declared knowledge source is unreadable: {exc}",
        )
    return KnowledgeSource(
        kind=kind, reference=reference, status="available", content_hash=content_hash
    )


def git_history_source(commit: str | None) -> KnowledgeSource:
    """Return the git history source for a resolved commit, or unknown."""
    if commit is None or not commit.strip():
        return KnowledgeSource(
            kind="git_history",
            reference="git:HEAD",
            status="unknown",
            reason="git history commit could not be resolved",
        )
    normalized = commit.strip()
    return KnowledgeSource(
        kind="git_history",
        reference=f"git:{normalized}",
        status="available",
        content_hash=canonical_json_sha256({"commit": normalized}),
    )


def build_knowledge_index(
    *,
    graph_path: Path,
    locations: Sequence[KnowledgeSourceLocation],
    audience: KnowledgeAudience,
    base_dir: Path,
    git_commit: str | None = None,
) -> KnowledgeIndex:
    """Build the knowledge index for one graph revision and one audience."""
    graph = load_indexed_graph(graph_path)
    excluded: set[KnowledgeSourceKind] = set()
    if audience == "public":
        excluded.update(INTERNAL_ONLY_KINDS)
    sources: list[KnowledgeSource] = [
        _resolve_file("design_graph", graph_path, base_dir)
    ]
    for location in locations:
        if location.kind in excluded:
            continue
        for path in _expand(location):
            sources.append(_resolve_file(location.kind, path, base_dir))
    sources.append(git_history_source(git_commit))
    return KnowledgeIndex(
        graph_id=graph.graph_id,
        target_revision=graph.revision,
        audience=audience,
        sources=_unique_sorted(sources),
        excluded_kinds=sorted(excluded),
    )


def _unique_sorted(sources: Iterable[KnowledgeSource]) -> list[KnowledgeSource]:
    by_key: dict[tuple[str, str], KnowledgeSource] = {}
    for source in sources:
        existing = by_key.get(source.key)
        # An unknown resolution wins over an available duplicate: the same
        # reference must not look resolved because it was declared twice.
        if existing is None or (
            existing.status == "available" and source.status == "unknown"
        ):
            by_key[source.key] = source
    return [by_key[key] for key in sorted(by_key)]
