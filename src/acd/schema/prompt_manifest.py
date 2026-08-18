"""Contracts for deterministic ACD role prompt manifests."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    SchemaVersion,
    Sha256,
)

PromptCacheTier = Literal["static"]
PromptManifestStatus = Literal["pass", "fail", "unknown"]


class RolePromptManifestEntry(AcdModel):
    role: NonEmptyStr
    asset_path: NonEmptyStr
    asset_hash: Sha256
    prompt_hash: Sha256
    section_name: NonEmptyStr
    cache_tier: PromptCacheTier


class RolePromptManifest(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    entries: list[RolePromptManifestEntry] = Field(min_length=1)
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_entries(self) -> RolePromptManifest:
        roles = [entry.role for entry in self.entries]
        paths = [entry.asset_path for entry in self.entries]
        sections = [entry.section_name for entry in self.entries]
        if len(roles) != len(set(roles)):
            raise ValueError("prompt manifest roles must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("prompt manifest asset paths must be unique")
        if len(sections) != len(set(sections)):
            raise ValueError("prompt manifest section names must be unique")
        if roles != sorted(roles):
            raise ValueError("prompt manifest entries must be sorted by role")
        return self


class PromptDriftReport(AcdModel):
    status: PromptManifestStatus
    drifted_roles: list[NonEmptyStr] = Field(default_factory=list)
    missing_roles: list[NonEmptyStr] = Field(default_factory=list)
    extra_roles: list[NonEmptyStr] = Field(default_factory=list)
    reason: NonEmptyStr | None = None
