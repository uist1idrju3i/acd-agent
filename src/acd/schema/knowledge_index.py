"""Contracts for the non-authoritative design knowledge index.

The knowledge index enumerates the knowledge sources a question answering path
may cite: the design graph, rationale records, gate results, evidence records,
generated documents, git history and conversation logs. The index is an L3
observation: it records where an answer may come from, it never approves a
design and it never becomes a design input. Missing or unreadable sources are
recorded as ``unknown`` with a reason instead of being silently dropped, so a
question cannot be answered from a source that was never available.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

KnowledgeSourceKind = Literal[
    "design_graph",
    "rationale",
    "gate_result",
    "evidence",
    "generated_document",
    "git_history",
    "conversation_log",
]
KnowledgeSourceStatus = Literal["available", "unknown"]
# Public answers are published together with the design outputs; internal
# answers stay inside the design team. Conversation logs are internal only.
KnowledgeAudience = Literal["internal", "public"]
INTERNAL_ONLY_KINDS: tuple[KnowledgeSourceKind, ...] = ("conversation_log",)


class KnowledgeSource(AcdModel):
    """A single citable knowledge source with its provenance."""

    kind: KnowledgeSourceKind
    reference: NonEmptyStr
    status: KnowledgeSourceStatus
    content_hash: HashOrUnknown = "unknown"
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> KnowledgeSource:
        if self.status == "unknown":
            if self.reason is None:
                raise ValueError("unknown knowledge source requires a reason")
            if self.content_hash != "unknown":
                raise ValueError("unknown knowledge source cannot carry a content hash")
            return self
        if self.reason is not None:
            raise ValueError("available knowledge source cannot carry a reason")
        if self.content_hash == "unknown":
            raise ValueError("available knowledge source requires a content hash")
        return self

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.reference)


class KnowledgeIndex(AcdModel):
    """The knowledge sources an answer for one revision may cite."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    target_revision: Revision
    audience: KnowledgeAudience
    sources: list[KnowledgeSource] = Field(min_length=1)
    excluded_kinds: list[KnowledgeSourceKind] = Field(
        default_factory=list[KnowledgeSourceKind]
    )
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_sources(self) -> KnowledgeIndex:
        keys = [source.key for source in self.sources]
        if len(set(keys)) != len(keys):
            raise ValueError("knowledge sources must be unique per kind and reference")
        if keys != sorted(keys):
            raise ValueError("knowledge sources must be sorted by kind and reference")
        if len(set(self.excluded_kinds)) != len(self.excluded_kinds):
            raise ValueError("excluded_kinds entries must be unique")
        if self.excluded_kinds != sorted(self.excluded_kinds):
            raise ValueError("excluded_kinds entries must be sorted")
        excluded = set(self.excluded_kinds)
        present = {source.kind for source in self.sources}
        overlap = sorted(excluded & present)
        if overlap:
            raise ValueError(f"excluded kinds are still indexed: {', '.join(overlap)}")
        if self.audience == "public":
            for kind in INTERNAL_ONLY_KINDS:
                if kind in present:
                    raise ValueError(f"public knowledge index cannot index {kind}")
                if kind not in excluded:
                    raise ValueError(
                        f"public knowledge index must record {kind} as excluded"
                    )
        return self

    def available(self, kind: KnowledgeSourceKind) -> tuple[KnowledgeSource, ...]:
        """Return the available sources of one kind, in index order."""
        return tuple(
            source
            for source in self.sources
            if source.kind == kind and source.status == "available"
        )

    def unknown_sources(self) -> tuple[KnowledgeSource, ...]:
        """Return every source that could not be resolved."""
        return tuple(source for source in self.sources if source.status == "unknown")
