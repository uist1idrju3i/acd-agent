"""Deterministic verification of the ACD ToolDefinition registration surface.

Conversations only see ACD tools when ``register_acd_tools()`` has run and the
agent definitions declare the registered names. This module derives the
registration manifest from the code contract, persists it as a plugin asset for
the install doctor, and reports drift. The report is an L3 observation and never
supports a pass verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from openhands.sdk.subagent import AgentDefinition
from openhands.sdk.tool import list_registered_tools
from pydantic import ValidationError
from yaml import YAMLError

from acd.openhands.tools.definitions import ACD_TOOL_DEFINITIONS, register_acd_tools
from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.tool_registration import (
    AcdToolContract,
    AcdToolRegistrationManifest,
    ToolRegistrationReport,
)

REGISTRATION_ENTRY_POINT: Final[str] = (
    "acd.openhands.tools.definitions.register_acd_tools"
)
DEFAULT_MANIFEST_NAME: Final[str] = "acd-tool-definitions.json"
ACD_TOOL_PREFIX: Final[str] = "acd_"


class ToolRegistrationError(ValueError):
    """Raised when the ACD tool registration surface cannot be verified."""


def _manifest_hash(manifest: AcdToolRegistrationManifest) -> Sha256:
    value = manifest.model_dump(mode="json")
    value["canonical_hash"] = "unknown"
    return canonical_json_sha256(value)


def generate_tool_registration_manifest() -> AcdToolRegistrationManifest:
    """Return the manifest derived from the in-code registration contract."""
    tools = [
        AcdToolContract(tool_name=name, definition_class=definition.__name__)
        for name, definition in ACD_TOOL_DEFINITIONS
    ]
    manifest = AcdToolRegistrationManifest(
        entry_point=REGISTRATION_ENTRY_POINT,
        tools=sorted(tools, key=lambda item: item.tool_name),
    )
    return manifest.model_copy(update={"canonical_hash": _manifest_hash(manifest)})


def load_tool_registration_manifest(path: Path) -> AcdToolRegistrationManifest:
    """Load and validate a persisted registration manifest."""
    try:
        manifest = AcdToolRegistrationManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise ToolRegistrationError(
            f"tool registration manifest is invalid: {path}"
        ) from exc
    if manifest.canonical_hash != _manifest_hash(manifest):
        raise ToolRegistrationError(
            f"tool registration manifest hash does not match its contents: {path}"
        )
    return manifest


def write_tool_registration_manifest(path: Path) -> AcdToolRegistrationManifest:
    """Persist the manifest asset read by the install doctor."""
    manifest = generate_tool_registration_manifest()
    payload = manifest.model_dump_json(indent=2) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise ToolRegistrationError(
            f"tool registration manifest cannot be written: {path}"
        ) from exc
    return manifest


def declared_agent_tools(agent_dir: Path) -> dict[str, tuple[str, ...]]:
    """Return the ACD tool names declared per agent definition."""
    if not agent_dir.is_dir():
        raise ToolRegistrationError(f"agent directory not found: {agent_dir}")
    paths = sorted(agent_dir.glob("acd-*.md"))
    if not paths:
        raise ToolRegistrationError(f"no ACD agent definitions found: {agent_dir}")
    declared: dict[str, tuple[str, ...]] = {}
    for path in paths:
        try:
            definition = AgentDefinition.load(path)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            YAMLError,
        ) as exc:
            raise ToolRegistrationError(f"agent definition is invalid: {path}") from exc
        declared[definition.name] = tuple(
            name for name in definition.tools if name.startswith(ACD_TOOL_PREFIX)
        )
    return declared


def check_tool_registration(
    *,
    agent_dir: Path,
    manifest_path: Path,
) -> ToolRegistrationReport:
    """Verify the persisted manifest, the registry, and the agent declarations."""
    try:
        expected = generate_tool_registration_manifest()
        persisted = load_tool_registration_manifest(manifest_path)
        declared = declared_agent_tools(agent_dir)
    except ToolRegistrationError as exc:
        return ToolRegistrationReport(status="unknown", reason=str(exc))
    if persisted != expected:
        return ToolRegistrationReport(
            status="fail",
            manifest_hash=persisted.canonical_hash,
            reason=(
                "persisted tool registration manifest differs from the code contract; "
                "regenerate it with --write"
            ),
        )
    expected_names = [tool.tool_name for tool in expected.tools]
    register_acd_tools()
    registered = set(list_registered_tools())
    missing = sorted(name for name in expected_names if name not in registered)
    undeclared = sorted(
        {
            name
            for names in declared.values()
            for name in names
            if name not in set(expected_names)
        }
    )
    if missing or undeclared:
        return ToolRegistrationReport(
            status="fail",
            manifest_hash=expected.canonical_hash,
            registered_tools=sorted(
                name for name in expected_names if name in registered
            ),
            missing_tools=missing,
            undeclared_agent_tools=undeclared,
            reason=(
                "ACD tools are missing from the SDK registry"
                if missing
                else "agent definitions declare ACD tools that are never registered"
            ),
        )
    from acd.openhands.tools.ambient import (
        AmbientToolError,
        check_ambient_registration_drift,
    )

    try:
        ambient_drift = check_ambient_registration_drift()
    except AmbientToolError as exc:
        return ToolRegistrationReport(
            status="unknown",
            manifest_hash=expected.canonical_hash,
            registered_tools=sorted(expected_names),
            reason=str(exc),
        )
    if ambient_drift:
        return ToolRegistrationReport(
            status="fail",
            manifest_hash=expected.canonical_hash,
            registered_tools=sorted(expected_names),
            reason="ambient tool registration drift: " + "; ".join(ambient_drift),
        )
    return ToolRegistrationReport(
        status="pass",
        manifest_hash=expected.canonical_hash,
        registered_tools=sorted(expected_names),
    )
