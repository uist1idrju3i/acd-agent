"""Tests for the ACD ToolDefinition registration diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.openhands.tools.registration import (
    DEFAULT_MANIFEST_NAME,
    REGISTRATION_ENTRY_POINT,
    ToolRegistrationError,
    _manifest_hash,  # pyright: ignore[reportPrivateUsage]
    check_tool_registration,
    declared_agent_tools,
    generate_tool_registration_manifest,
    load_tool_registration_manifest,
    write_tool_registration_manifest,
)
from acd.schema.tool_registration import AcdToolContract

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = REPO_ROOT / "plugins" / "acd" / "agents"
MANIFEST_PATH = REPO_ROOT / "plugins" / "acd" / ".plugin" / DEFAULT_MANIFEST_NAME


def test_persisted_manifest_matches_code_contract() -> None:
    persisted = load_tool_registration_manifest(MANIFEST_PATH)
    assert persisted == generate_tool_registration_manifest()
    assert persisted.entry_point == REGISTRATION_ENTRY_POINT


def test_check_passes_for_repository_assets() -> None:
    report = check_tool_registration(agent_dir=AGENT_DIR, manifest_path=MANIFEST_PATH)
    assert report.status == "pass"
    assert report.pass_evidence is False
    assert report.missing_tools == []
    assert report.undeclared_agent_tools == []
    assert report.registered_tools == [
        tool.tool_name for tool in generate_tool_registration_manifest().tools
    ]


def test_manifest_drift_fails(tmp_path: Path) -> None:
    manifest = write_tool_registration_manifest(tmp_path / DEFAULT_MANIFEST_NAME)
    document = json.loads((tmp_path / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8"))
    document["tools"] = document["tools"][:-1]
    (tmp_path / DEFAULT_MANIFEST_NAME).write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    assert manifest.canonical_hash.startswith("sha256:")
    report = check_tool_registration(
        agent_dir=AGENT_DIR,
        manifest_path=tmp_path / DEFAULT_MANIFEST_NAME,
    )
    assert report.status == "unknown"
    assert report.reason is not None
    assert "hash" in report.reason


def test_manifest_with_unknown_tool_reports_drift(tmp_path: Path) -> None:
    """A self-consistent manifest that disagrees with the code contract fails."""
    manifest = generate_tool_registration_manifest()
    drifted = manifest.model_copy(
        update={
            "tools": [
                AcdToolContract(
                    tool_name="acd_unregistered_tool",
                    definition_class="AcdUnregistered",
                )
            ],
            "canonical_hash": "unknown",
        }
    )
    drifted = drifted.model_copy(update={"canonical_hash": _manifest_hash(drifted)})
    path = tmp_path / DEFAULT_MANIFEST_NAME
    path.write_text(drifted.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = check_tool_registration(agent_dir=AGENT_DIR, manifest_path=path)
    assert report.status == "fail"
    assert report.reason is not None
    assert "code contract" in report.reason


def test_malformed_manifest_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / DEFAULT_MANIFEST_NAME
    path.write_text("{", encoding="utf-8")
    report = check_tool_registration(agent_dir=AGENT_DIR, manifest_path=path)
    assert report.status == "unknown"
    assert report.pass_evidence is False


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    report = check_tool_registration(
        agent_dir=AGENT_DIR,
        manifest_path=tmp_path / DEFAULT_MANIFEST_NAME,
    )
    assert report.status == "unknown"


def test_missing_agent_directory_fails_closed(tmp_path: Path) -> None:
    report = check_tool_registration(
        agent_dir=tmp_path / "agents",
        manifest_path=MANIFEST_PATH,
    )
    assert report.status == "unknown"


def test_agent_directory_without_definitions_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    with pytest.raises(ToolRegistrationError):
        declared_agent_tools(tmp_path / "agents")


def test_undeclared_agent_tool_fails(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    source = (AGENT_DIR / "acd-electrical.md").read_text(encoding="utf-8")
    (agent_dir / "acd-electrical.md").write_text(
        source.replace("  - acd_probe_tools", "  - acd_probe_tools\n  - acd_unknown_tool"),
        encoding="utf-8",
    )
    report = check_tool_registration(agent_dir=agent_dir, manifest_path=MANIFEST_PATH)
    assert report.status == "fail"
    assert report.undeclared_agent_tools == ["acd_unknown_tool"]
    assert report.pass_evidence is False


def test_agent_declarations_are_limited_to_registered_tools() -> None:
    declared = declared_agent_tools(AGENT_DIR)
    registered = {tool.tool_name for tool in generate_tool_registration_manifest().tools}
    assert declared
    assert any(names for names in declared.values())
    for names in declared.values():
        assert set(names) <= registered
