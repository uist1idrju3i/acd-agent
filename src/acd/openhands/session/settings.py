"""Fail-closed ACD settings, profile, and credential handling on SDK paths."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from openhands.sdk.profiles import OpenHandsAgentProfile, validate_agent_profile
from pydantic import ValidationError

from acd.openhands.safety.secrets import ACD_SECRET_ENV_VARS, build_acd_secret_mapping
from acd.openhands.session.observation_store import (
    ObservationPayload,
    write_observation_payload,
)
from acd.schema.agent_settings import (
    AcdProfileObservation,
    AcdProfileSetting,
    AcdSettingsManifest,
    AcdSettingsReport,
)
from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.model_routing import ModelRoutingPolicy


class AcdSettingsError(ValueError):
    """Raised when settings, profile, or credential material is unusable."""


def acd_settings_manifest_hash(manifest: AcdSettingsManifest) -> Sha256:
    """Return the canonical hash of settings and profile material."""
    value = manifest.model_dump(mode="json")
    value["canonical_hash"] = "unknown"
    return canonical_json_sha256(value)


def load_acd_settings_manifest(path: Path) -> AcdSettingsManifest:
    """Load settings and profile material from deterministic JSON."""
    try:
        return AcdSettingsManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise AcdSettingsError(f"agent settings manifest is invalid: {path}") from exc


def write_acd_settings_manifest(
    manifest: AcdSettingsManifest,
    path: Path,
) -> AcdSettingsManifest:
    """Write settings material with its canonical hash fixed."""
    fixed = manifest.model_copy(
        update={"canonical_hash": acd_settings_manifest_hash(manifest)}
    )
    contents = (
        json.dumps(
            fixed.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        path.write_text(contents, encoding="utf-8")
    except OSError as exc:
        raise AcdSettingsError(f"agent settings manifest is unwritable: {path}") from exc
    return fixed


def _validate_manifest_hash(manifest: AcdSettingsManifest) -> None:
    if manifest.canonical_hash != acd_settings_manifest_hash(manifest):
        raise AcdSettingsError("agent settings canonical hash is invalid")


def _sdk_profile(setting: AcdProfileSetting) -> OpenHandsAgentProfile:
    """Build the secret-free SDK profile described by one ACD setting."""
    try:
        profile = validate_agent_profile(
            {
                "agent_kind": "openhands",
                "id": str(uuid5(NAMESPACE_URL, f"acd:profile:{setting.profile_name}")),
                "llm_profile_ref": setting.llm_profile_ref,
                "name": setting.profile_name,
            }
        )
    except (ValidationError, ValueError) as exc:
        raise AcdSettingsError(
            f"{setting.role} profile is not a valid SDK profile"
        ) from exc
    if not isinstance(profile, OpenHandsAgentProfile):
        raise AcdSettingsError(f"{setting.role} profile is not an OpenHands profile")
    serialized = json.dumps(profile.model_dump(mode="json"), sort_keys=True)
    if setting.credential.secret_name in serialized:
        raise AcdSettingsError(f"{setting.role} profile must stay credential-free")
    return profile


def _validate_credential(setting: AcdProfileSetting) -> bool:
    """Return whether the referenced credential is currently registered."""
    if setting.credential.secret_name not in ACD_SECRET_ENV_VARS:
        raise AcdSettingsError(
            f"{setting.role} credential is outside the secret allowlist"
        )
    return setting.credential.secret_name in build_acd_secret_mapping()


def _validate_profile_drift(
    manifest: AcdSettingsManifest,
    policy: ModelRoutingPolicy,
) -> None:
    policy_profiles = {binding.role: binding.profile for binding in policy.bindings}
    for setting in manifest.profiles:
        expected = policy_profiles.get(setting.role)
        if expected is None:
            raise AcdSettingsError(
                f"{setting.role} is missing from the model routing policy"
            )
        if expected != setting.profile_name:
            raise AcdSettingsError(f"{setting.role} profile drifted from the policy")


def validate_acd_settings(
    manifest: AcdSettingsManifest,
    policy: ModelRoutingPolicy,
) -> list[AcdProfileObservation]:
    """Validate settings material and return non-authoritative observations."""
    _validate_manifest_hash(manifest)
    _validate_profile_drift(manifest, policy)
    observations: list[AcdProfileObservation] = []
    for setting in manifest.profiles:
        profile = _sdk_profile(setting)
        observations.append(
            AcdProfileObservation(
                role=setting.role,
                profile_name=profile.name,
                llm_profile_ref=profile.llm_profile_ref,
                credential_name=setting.credential.secret_name,
                credential_registered=_validate_credential(setting),
            )
        )
    return observations


def acd_settings_report(
    manifest: AcdSettingsManifest,
    policy: ModelRoutingPolicy,
) -> AcdSettingsReport:
    """Return a fail-closed settings report; drift and unknowns are unknown."""
    try:
        observations = validate_acd_settings(manifest, policy)
    except AcdSettingsError as exc:
        return AcdSettingsReport(
            status="unknown",
            manifest_hash="unknown",
            reason=str(exc),
        )
    return AcdSettingsReport(
        status="pass",
        manifest_hash=manifest.canonical_hash,
        profiles=observations,
    )


def write_acd_settings_report(
    manifest: AcdSettingsManifest,
    policy: ModelRoutingPolicy,
    path: Path,
) -> AcdSettingsReport:
    """Write the settings report as a non-authoritative observation."""
    report = acd_settings_report(manifest, policy)
    payload = ObservationPayload.model_validate(report.model_dump(mode="json"))
    write_observation_payload(payload, path)
    return report
