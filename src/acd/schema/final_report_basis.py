"""Contracts for the machine-generated final-report basis (L3, diagnostic)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from acd.schema.common import AcdModel


class SourceChangeSection(AcdModel):
    """Verbatim git facts backing the report's source-change statement."""

    status: Literal["clean", "changed", "unknown"]
    bootstrap_record: str | None = None
    bootstrap_revision: str | None = None
    head_revision: str | None = None
    committed_commits: list[str] = Field(default_factory=list[str])
    committed_log: str = ""
    worktree_status: str = ""
    worktree_diff_stat: str = ""
    worktree_changed_paths: list[str] = Field(default_factory=list[str])
    reason: str | None = None


class DesignComponentValue(AcdModel):
    """One component's declared values for the report's design-value table."""

    refdes: str
    value: str | None = None
    mpn: str | None = None
    lcsc: str | None = None
    footprint: str | None = None
    pads: dict[str, str | None] = Field(default_factory=dict)


class DesignNetValue(AcdModel):
    """One net's connections, rendered as ``refdes.pad`` members."""

    net_id: str
    connections: list[str] = Field(default_factory=list[str])


class DesignValueSection(AcdModel):
    """Component and net values extracted from a spec or graph file."""

    source: str
    source_kind: Literal["spec", "graph"]
    design_name: str | None = None
    graph_id: str | None = None
    revision: str | None = None
    components: list[DesignComponentValue] = Field(default_factory=list[DesignComponentValue])
    nets: list[DesignNetValue] = Field(default_factory=list[DesignNetValue])


class FinalReportBasis(AcdModel):
    """Machine-generated basis for the final report (never pass authority)."""

    schema_version: Literal["0.1"] = "0.1"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    authoritative_evidence: Literal["unverified"] = "unverified"
    status: Literal["pass", "unknown"]
    source_changes: SourceChangeSection
    design_values: DesignValueSection | None = None
    notes: list[str] = Field(default_factory=list[str])


__all__ = [
    "DesignComponentValue",
    "DesignNetValue",
    "DesignValueSection",
    "FinalReportBasis",
    "SourceChangeSection",
]
