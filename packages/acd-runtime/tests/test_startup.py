"""SessionStart validation tests (fail-closed)."""

from __future__ import annotations

from pathlib import Path

from openhands.sdk.extensions.installation.info import InstallationInfo
from openhands.sdk.extensions.installation.metadata import InstallationMetadata
from openhands.sdk.hooks.types import HookDecision

from acd_runtime import StartupExpectations, validate_session_start

GOOD_HASH = "sha256:" + "ab" * 32


def info(resolved_ref: str | None) -> InstallationInfo:
    return InstallationInfo(
        name="acd",
        source="github:uist1idrju3i/acd-agent",
        requested_ref="main",
        resolved_ref=resolved_ref,
        install_path=Path("/tmp/ext/acd"),
    )


def test_allow_when_everything_known() -> None:
    report = validate_session_start(
        StartupExpectations(required_tools=["kicad-cli"], mcp_config_hash=GOOD_HASH),
        tool_versions={"kicad-cli": "9.0.4"},
        metadata=InstallationMetadata(extensions={"acd": info("deadbeef")}),
        actual_mcp_config_hash=GOOD_HASH,
    )
    assert report.decision is HookDecision.ALLOW
    assert report.failures() == []


def test_deny_on_unknown_tool_version() -> None:
    report = validate_session_start(
        StartupExpectations(required_tools=["kicad-cli"]),
        tool_versions={},
        metadata=InstallationMetadata(),
        actual_mcp_config_hash=None,
    )
    assert report.decision is HookDecision.DENY
    assert [c.name for c in report.failures()] == ["tool:kicad-cli"]


def test_deny_on_missing_resolved_ref() -> None:
    report = validate_session_start(
        StartupExpectations(),
        tool_versions={},
        metadata=InstallationMetadata(extensions={"acd": info(None)}),
        actual_mcp_config_hash=None,
    )
    assert report.decision is HookDecision.DENY
    assert [c.name for c in report.failures()] == ["extension:acd"]


def test_deny_on_mcp_hash_mismatch_or_missing() -> None:
    for actual in (None, "sha256:" + "cd" * 32):
        report = validate_session_start(
            StartupExpectations(mcp_config_hash=GOOD_HASH),
            tool_versions={},
            metadata=InstallationMetadata(),
            actual_mcp_config_hash=actual,
        )
        assert report.decision is HookDecision.DENY
        assert [c.name for c in report.failures()] == ["mcp_config_hash"]
