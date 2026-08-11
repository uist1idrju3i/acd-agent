"""SessionStart validation (fail-closed startup gate).

Validates, before a session is allowed to run:

- ACD packages are importable,
- required external tools have known versions (via probe results),
- every installed extension in the SDK's ``.installed.json`` has a
  ``resolved_ref`` (a ``requested_ref`` without a resolved SHA is denied),
- the MCP configuration hash matches the pinned expectation.

Any unknown, missing, or mismatched item yields ``HookDecision.DENY``.
"""

from __future__ import annotations

import importlib.util

from openhands.sdk.extensions.installation.metadata import InstallationMetadata
from openhands.sdk.hooks.types import HookDecision
from pydantic import Field

from acd_schema import AcdModel
from acd_schema.common import NonEmptyStr, Sha256

ACD_PACKAGES = ("acd_schema", "acd_core", "acd_events", "acd_runtime")


class StartupExpectations(AcdModel):
    """Pinned expectations a session must satisfy before it may start."""

    required_tools: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])
    mcp_config_hash: Sha256 | None = None


class StartupCheck(AcdModel):
    name: NonEmptyStr
    passed: bool
    detail: str


class StartupReport(AcdModel):
    checks: list[StartupCheck]

    @property
    def decision(self) -> HookDecision:
        if all(check.passed for check in self.checks):
            return HookDecision.ALLOW
        return HookDecision.DENY

    def failures(self) -> list[StartupCheck]:
        return [check for check in self.checks if not check.passed]


def _check_imports() -> list[StartupCheck]:
    checks: list[StartupCheck] = []
    for package in ACD_PACKAGES:
        found = importlib.util.find_spec(package) is not None
        checks.append(
            StartupCheck(
                name=f"import:{package}",
                passed=found,
                detail="importable" if found else "package not importable",
            )
        )
    return checks


def _check_tools(
    expectations: StartupExpectations, tool_versions: dict[str, str]
) -> list[StartupCheck]:
    checks: list[StartupCheck] = []
    for tool in expectations.required_tools:
        version = tool_versions.get(tool, "unknown")
        passed = version != "unknown"
        checks.append(
            StartupCheck(
                name=f"tool:{tool}",
                passed=passed,
                detail=f"version={version}",
            )
        )
    return checks


def _check_installations(metadata: InstallationMetadata) -> list[StartupCheck]:
    checks: list[StartupCheck] = []
    for name, info in sorted(metadata.extensions.items()):
        passed = info.resolved_ref is not None
        detail = (
            f"resolved_ref={info.resolved_ref}"
            if passed
            else f"resolved_ref missing (requested_ref={info.requested_ref!r})"
        )
        checks.append(StartupCheck(name=f"extension:{name}", passed=passed, detail=detail))
    return checks


def _check_mcp_hash(
    expectations: StartupExpectations, actual_mcp_config_hash: str | None
) -> list[StartupCheck]:
    if expectations.mcp_config_hash is None:
        return []
    passed = actual_mcp_config_hash == expectations.mcp_config_hash
    return [
        StartupCheck(
            name="mcp_config_hash",
            passed=passed,
            detail=(
                "match"
                if passed
                else f"expected {expectations.mcp_config_hash}, got {actual_mcp_config_hash!r}"
            ),
        )
    ]


def validate_session_start(
    expectations: StartupExpectations,
    tool_versions: dict[str, str],
    metadata: InstallationMetadata,
    actual_mcp_config_hash: str | None,
) -> StartupReport:
    """Run all startup checks and return a report whose decision is fail-closed."""
    checks = [
        *_check_imports(),
        *_check_tools(expectations, tool_versions),
        *_check_installations(metadata),
        *_check_mcp_hash(expectations, actual_mcp_config_hash),
    ]
    return StartupReport(checks=checks)
