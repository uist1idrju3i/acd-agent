"""Contracts for secret-free ACD agent settings, profiles, and credentials."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    HashOrUnknown,
    NonEmptyStr,
    SchemaVersion,
)
from acd.schema.model_routing import RoutingRole

AcdSettingsStatus = Literal["pass", "unknown"]

# A credential is referenced by its registered secret name only, never by value.
SecretReferenceName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
ProfileName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]


class AcdCredentialReference(AcdModel):
    """One credential named by its SecretRegistry reference.

    The reference carries the registered secret name only: values stay in the
    registry so that settings material remains secret-free at rest.
    """

    secret_name: SecretReferenceName
    description: NonEmptyStr | None = None


class AcdProfileSetting(AcdModel):
    """Settings for one routing role, bound to a secret-free SDK profile."""

    role: RoutingRole
    profile_name: ProfileName
    llm_profile_ref: ProfileName
    credential: AcdCredentialReference

    @model_validator(mode="after")
    def reject_unknown_values(self) -> AcdProfileSetting:
        if "unknown" in (self.profile_name, self.llm_profile_ref):
            raise ValueError("agent settings values must not be unknown")
        return self


class AcdSettingsManifest(AcdModel):
    """Canonical, hash-fixed ACD settings and profile material."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    profiles: list[AcdProfileSetting] = Field(min_length=1)
    canonical_hash: HashOrUnknown = "unknown"

    @model_validator(mode="after")
    def validate_profiles(self) -> AcdSettingsManifest:
        roles = [profile.role for profile in self.profiles]
        if len(roles) != len(set(roles)):
            raise ValueError("agent settings roles must be unique")
        if roles != sorted(roles):
            raise ValueError("agent settings profiles must be sorted by role")
        if not {"agent", "judge"}.issubset(roles):
            raise ValueError("agent settings must declare agent and judge")
        names = [profile.profile_name for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("agent settings profile names must be unique")
        return self


class AcdProfileObservation(AcdModel):
    """Non-authoritative observation of one resolved profile binding."""

    role: RoutingRole
    profile_name: ProfileName
    llm_profile_ref: ProfileName
    credential_name: SecretReferenceName
    credential_registered: bool


class AcdSettingsReport(AcdModel):
    """Non-authoritative settings and profile drift report."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["agent_settings_observation"] = (
        "agent_settings_observation"
    )
    pass_evidence: Literal[False] = False
    status: AcdSettingsStatus
    manifest_hash: HashOrUnknown
    profiles: list[AcdProfileObservation] = Field(
        default_factory=list[AcdProfileObservation]
    )
    reason: NonEmptyStr | None = None
