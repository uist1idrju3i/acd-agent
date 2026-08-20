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


class ToolRegistrationReport(AcdModel):
    """Deterministic drift report for the ACD tool registration surface."""

    status: ToolRegistrationStatus
    manifest_hash: HashOrUnknown = "unknown"
    registered_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    missing_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    undeclared_agent_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    reason: NonEmptyStr | None = None
    pass_evidence: Literal[False] = False
