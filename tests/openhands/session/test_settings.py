"""Tests for fail-closed ACD settings, profile, and credential handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.llm import LLM

from acd.openhands.session.bootstrap import build_acd_conversation
from acd.openhands.session.gate_critic import AcdEvidenceRequirement
from acd.openhands.session.routing import load_model_routing_policy
from acd.openhands.session.settings import (
    AcdSettingsError,
    acd_settings_manifest_hash,
    acd_settings_report,
    load_acd_settings_manifest,
    validate_acd_settings,
    write_acd_settings_manifest,
    write_acd_settings_report,
)
from acd.schema.agent_settings import AcdSettingsManifest
from acd.schema.model_routing import ModelRoutingPolicy

SETTINGS_FIXTURES = Path("fixtures/settings")
POLICY_PATH = Path("plugins/acd/model-policy.json")
TRACKED_SETTINGS = Path("plugins/acd/agent-settings.json")


def _policy() -> ModelRoutingPolicy:
    return load_model_routing_policy(POLICY_PATH)


def _manifest(kind: str, name: str) -> AcdSettingsManifest:
    return load_acd_settings_manifest(SETTINGS_FIXTURES / kind / name)


def test_tracked_settings_match_routing_policy() -> None:
    report = acd_settings_report(
        load_acd_settings_manifest(TRACKED_SETTINGS),
        _policy(),
    )
    assert report.status == "pass"
    assert report.pass_evidence is False
    assert [item.role for item in report.profiles] == ["agent", "condenser", "judge"]


def test_manifest_hash_is_reproducible() -> None:
    manifest = _manifest("valid", "agent-settings.json")
    assert manifest.canonical_hash == acd_settings_manifest_hash(manifest)
    assert acd_settings_manifest_hash(manifest) == acd_settings_manifest_hash(
        _manifest("valid", "agent-settings.json")
    )


def test_report_carries_credential_names_only() -> None:
    report = acd_settings_report(_manifest("valid", "agent-settings.json"), _policy())
    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert "LLM_API_KEY" in serialized
    assert "secret_name" not in serialized
    assert all(item.credential_name == "LLM_API_KEY" for item in report.profiles)


def test_credential_registration_is_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    unregistered = acd_settings_report(
        _manifest("valid", "agent-settings.json"), _policy()
    )
    monkeypatch.setenv("LLM_API_KEY", "llm-secret-value")
    registered = acd_settings_report(
        _manifest("valid", "agent-settings.json"), _policy()
    )
    assert all(not item.credential_registered for item in unregistered.profiles)
    assert all(item.credential_registered for item in registered.profiles)
    assert "llm-secret-value" not in json.dumps(registered.model_dump(mode="json"))


@pytest.mark.parametrize(
    "name",
    [
        "hash-mismatch.json",
        "hash-unknown.json",
        "profile-drift.json",
        "credential-outside-allowlist.json",
    ],
)
def test_invalid_settings_report_unknown(name: str) -> None:
    report = acd_settings_report(_manifest("invalid", name), _policy())
    assert report.status == "unknown"
    assert report.manifest_hash == "unknown"
    assert report.profiles == []
    assert report.reason is not None


@pytest.mark.parametrize(
    "name",
    [
        "hash-mismatch.json",
        "profile-drift.json",
        "credential-outside-allowlist.json",
    ],
)
def test_invalid_settings_raise_for_callers(name: str) -> None:
    with pytest.raises(AcdSettingsError):
        validate_acd_settings(_manifest("invalid", name), _policy())


def test_unknown_configuration_fails_closed() -> None:
    with pytest.raises(AcdSettingsError):
        _manifest("invalid", "unknown-role.json")


def test_missing_settings_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(AcdSettingsError):
        load_acd_settings_manifest(tmp_path / "absent.json")


def test_write_manifest_fixes_canonical_hash(tmp_path: Path) -> None:
    manifest = _manifest("valid", "agent-settings.json")
    unfixed = manifest.model_copy(update={"canonical_hash": "unknown"})
    written = write_acd_settings_manifest(unfixed, tmp_path / "agent-settings.json")
    assert written.canonical_hash == manifest.canonical_hash
    assert load_acd_settings_manifest(
        tmp_path / "agent-settings.json"
    ).canonical_hash == manifest.canonical_hash


def test_bootstrap_derives_routing_profiles_from_settings(tmp_path: Path) -> None:
    manifest = load_acd_settings_manifest(TRACKED_SETTINGS)
    conversation = build_acd_conversation(
        repo_root=Path.cwd(),
        llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
        requirements=[
            AcdEvidenceRequirement(
                path=Path("fixtures/contracts/valid/evidence.json"),
                evidence_id="ev-erc-r3-0001",
            )
        ],
        persistence_dir=tmp_path / "sessions",
        model_routing_policy=_policy(),
        agent_settings=manifest,
        condenser_llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-condenser"),
    )
    assert conversation.agent.condenser is not None


def test_bootstrap_rejects_drifted_settings(tmp_path: Path) -> None:
    with pytest.raises(AcdSettingsError, match="drifted"):
        build_acd_conversation(
            repo_root=Path.cwd(),
            llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
            requirements=[],
            persistence_dir=tmp_path / "sessions",
            model_routing_policy=_policy(),
            agent_settings=_manifest("invalid", "profile-drift.json"),
        )


def test_bootstrap_requires_policy_for_settings(tmp_path: Path) -> None:
    with pytest.raises(AcdSettingsError, match="model routing policy"):
        build_acd_conversation(
            repo_root=Path.cwd(),
            llm=LLM(model="openai/gpt-4o-mini", usage_id="acd-agent"),
            requirements=[],
            persistence_dir=tmp_path / "sessions",
            agent_settings=load_acd_settings_manifest(TRACKED_SETTINGS),
        )


def test_settings_report_is_written_as_observation(tmp_path: Path) -> None:
    report = write_acd_settings_report(
        _manifest("valid", "agent-settings.json"),
        _policy(),
        tmp_path / "agent-settings-observation.json",
    )
    stored = json.loads(
        (tmp_path / "agent-settings-observation.json").read_text(encoding="utf-8")
    )
    assert report.status == "pass"
    assert stored["artifact_kind"] == "agent_settings_observation"
    assert stored["pass_evidence"] is False
