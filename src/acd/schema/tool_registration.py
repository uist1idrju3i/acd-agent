"""Contracts for the ACD SDK ToolDefinition registration surface."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    SchemaVersion,
)

ToolRegistrationStatus = Literal["pass", "fail", "unknown"]


class AcdToolContract(AcdModel):
    """One ACD ToolDefinition that ``register_acd_tools()`` registers."""

    tool_name: NonEmptyStr
    definition_class: NonEmptyStr


class AcdToolRegistrationManifest(AcdModel):
    """The registration surface exposed to conversations and to the doctor.

    The doctor Skill cannot import ``acd``, so this manifest is the asset it
    reads to diagnose whether the agent definitions and the registration entry
    point agree on the ACD tool names.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    entry_point: NonEmptyStr
    tools: list[AcdToolContract] = Field(min_length=1)
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_tools(self) -> AcdToolRegistrationManifest:
        names = [tool.tool_name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        if names != sorted(names):
            raise ValueError("tools must be sorted by tool_name")
        return self


class ToolFallback(AcdModel):
    """The deterministic CLI path that replaces one unavailable ACD tool."""

    tool_name: NonEmptyStr
    command: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_command(self) -> ToolFallback:
        if not self.command and self.reason is None:
            raise ValueError("a fallback without a command requires a reason")
        if self.command and self.reason is not None:
            raise ValueError("a fallback command must not carry a reason")
        return self


class AmbientToolAvailabilityReport(AcdModel):
    """Whether one conversation exposes the ACD tools a command declares.

    The ambient installed-plugin path can present a conversation that has no ACD
    ToolDefinition registered. This report detects that fail-closed and carries
    the deterministic CLI path for every tool the conversation is missing.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    status: ToolRegistrationStatus
    command_path: NonEmptyStr
    declared_tools: list[NonEmptyStr] = Field(min_length=1)
    available_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    missing_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    fallbacks: list[ToolFallback] = Field(default_factory=list[ToolFallback])
    reason: NonEmptyStr | None = None
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_report(self) -> AmbientToolAvailabilityReport:
        for names in (self.declared_tools, self.available_tools, self.missing_tools):
            if names != sorted(names):
                raise ValueError("tool names must be sorted")
            if len(names) != len(set(names)):
                raise ValueError("tool names must be unique")
        if [item.tool_name for item in self.fallbacks] != self.missing_tools:
            raise ValueError("fallbacks must cover exactly the missing tools")
        if self.status == "pass":
            if self.missing_tools:
                raise ValueError("a passing report must not miss declared tools")
            if self.reason is not None:
                raise ValueError("a passing report must not carry a reason")
        elif self.reason is None:
            raise ValueError("a non-passing report requires a reason")
        return self


class ToolRegistrationReport(AcdModel):
    """Deterministic drift report for the ACD tool registration surface."""

    status: ToolRegistrationStatus
    manifest_hash: HashOrUnknown = "unknown"
    registered_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    missing_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    undeclared_agent_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    reason: NonEmptyStr | None = None
    pass_evidence: Literal[False] = False
