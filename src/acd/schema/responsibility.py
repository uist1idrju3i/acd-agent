"""Responsibility-allocation declaration and gate contracts (ADR-0049 §7)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
)

ResponsibilityDomain = Literal[
    "mechanism",
    "mechanical",
    "electrical",
    "firmware",
    "pc_software",
    "server",
    "mobile_app",
]

ResponsibilityCriterion = Literal[
    "response_time",
    "power",
    "cost",
    "update_frequency",
    "safety",
    "communication_availability",
    "maintainability",
]

Unknown = Literal["unknown"]


class FunctionNeed(AcdModel):
    """Declared needs of one function; unknown fields fail the gate."""

    function_id: NodeId
    gpio_count: int | Unknown = Field(default="unknown", ge=0)
    communication: list[NonEmptyStr] | Unknown = "unknown"
    memory_kb: int | Unknown = Field(default="unknown", ge=0)
    power_source: NonEmptyStr | Unknown = "unknown"
    motion: bool | Unknown = "unknown"


class DomainCapability(AcdModel):
    """Declared capabilities of one allocation domain."""

    domain: ResponsibilityDomain
    gpio_count: int | Unknown = "unknown"
    communication: list[NonEmptyStr] | Unknown = "unknown"
    memory_kb: int | Unknown = "unknown"
    power_sources: list[NonEmptyStr] | Unknown = "unknown"
    motion: bool | Unknown = "unknown"


class FunctionDependency(AcdModel):
    """A dependency between two functions."""

    function_id: NodeId
    depends_on: NodeId

    @model_validator(mode="after")
    def _distinct(self) -> FunctionDependency:
        if self.function_id == self.depends_on:
            raise ValueError("function_id and depends_on must differ")
        return self


class CrossDomainInterface(AcdModel):
    """A declared interface between two domains; may be one-sided."""

    interface_id: NodeId
    domains: tuple[ResponsibilityDomain, ResponsibilityDomain]
    signal: NonEmptyStr
    protocol: NonEmptyStr
    power: NonEmptyStr
    declared_by: list[ResponsibilityDomain]

    @model_validator(mode="after")
    def _sorted_distinct_domains(self) -> CrossDomainInterface:
        first, second = self.domains
        if first == second:
            raise ValueError("domains entries must be distinct")
        if self.domains != tuple(sorted(self.domains)):
            raise ValueError("domains entries must be sorted")
        return self


class SharedAssignmentContract(AcdModel):
    """Explicit contract permitting one function across multiple domains."""

    function_id: NodeId
    domains: list[ResponsibilityDomain] = Field(min_length=2)
    split: NonEmptyStr

    @model_validator(mode="after")
    def _distinct_domains(self) -> SharedAssignmentContract:
        if len(set(self.domains)) != len(self.domains):
            raise ValueError("domains entries must be distinct")
        return self


class ResponsibilityDeclaration(AcdModel):
    """The responsibility declaration stored beside graph.json."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    graph_id: NonEmptyStr
    revision: Revision
    functions: list[FunctionNeed] = Field(default_factory=list[FunctionNeed])
    capabilities: list[DomainCapability] = Field(
        default_factory=list[DomainCapability]
    )
    dependencies: list[FunctionDependency] = Field(
        default_factory=list[FunctionDependency]
    )
    interfaces: list[CrossDomainInterface] = Field(
        default_factory=list[CrossDomainInterface]
    )
    shared_assignments: list[SharedAssignmentContract] = Field(
        default_factory=list[SharedAssignmentContract]
    )

    @model_validator(mode="after")
    def _unique_entries(self) -> ResponsibilityDeclaration:
        function_ids = [item.function_id for item in self.functions]
        if len(set(function_ids)) != len(function_ids):
            raise ValueError("functions function_id entries must be unique")
        domains = [item.domain for item in self.capabilities]
        if len(set(domains)) != len(domains):
            raise ValueError("capabilities domain entries must be unique")
        interface_ids = [item.interface_id for item in self.interfaces]
        if len(set(interface_ids)) != len(interface_ids):
            raise ValueError("interfaces interface_id entries must be unique")
        shared_ids = [item.function_id for item in self.shared_assignments]
        if len(set(shared_ids)) != len(shared_ids):
            raise ValueError("shared_assignments function_id entries must be unique")
        return self


class Assignment(AcdModel):
    """One resolved function-to-domain assignment."""

    function_id: NodeId
    domain: ResponsibilityDomain
    node_id: NodeId
    criteria: list[ResponsibilityCriterion] = Field(
        default_factory=list[ResponsibilityCriterion]
    )


ResponsibilityFindingCode = Literal[
    "graph_mismatch",
    "unassigned",
    "multiple_assignment",
    "undeclared_function",
    "invalid_domain",
    "invalid_function_id",
    "invalid_criteria",
    "missing_capability",
    "unknown_state",
    "capability_conflict",
    "missing_interface",
    "one_sided_interface",
]


class ResponsibilityFinding(AcdModel):
    """One deterministic gate finding; findings fail the gate."""

    code: ResponsibilityFindingCode
    subject: NonEmptyStr
    detail: NonEmptyStr


class ResponsibilityGateResult(AcdModel):
    """Deterministic responsibility-assignment gate result."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    gate: Literal["responsibility_assignment"] = "responsibility_assignment"
    graph_id: NonEmptyStr
    revision: Revision
    status: Literal["pass", "fail"]
    assignments: list[Assignment] = Field(default_factory=list[Assignment])
    findings: list[ResponsibilityFinding] = Field(
        default_factory=list[ResponsibilityFinding]
    )


__all__ = [
    "Assignment",
    "CrossDomainInterface",
    "DomainCapability",
    "FunctionDependency",
    "FunctionNeed",
    "ResponsibilityCriterion",
    "ResponsibilityDeclaration",
    "ResponsibilityDomain",
    "ResponsibilityFinding",
    "ResponsibilityFindingCode",
    "ResponsibilityGateResult",
    "SharedAssignmentContract",
]
