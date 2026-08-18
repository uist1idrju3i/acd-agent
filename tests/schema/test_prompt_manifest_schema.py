"""Tests for the role prompt manifest contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.prompt_manifest import PromptDriftReport, RolePromptManifest


def _entry(role: str, section_name: str | None = None) -> dict[str, str]:
    return {
        "role": role,
        "asset_path": f"plugins/acd/agents/{role}.md",
        "asset_hash": "sha256:" + "a" * 64,
        "prompt_hash": "sha256:" + "b" * 64,
        "section_name": section_name or f"acd.role.{role}",
        "cache_tier": "static",
    }


def test_prompt_manifest_parses_sorted_entries() -> None:
    manifest = RolePromptManifest.model_validate(
        {"entries": [_entry("acd-a"), _entry("acd-b")]}
    )
    assert [entry.role for entry in manifest.entries] == ["acd-a", "acd-b"]
    assert manifest.canonical_hash == "unknown"


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([_entry("acd-a"), _entry("acd-a")], "roles"),
        (
            [
                _entry("acd-a"),
                {**_entry("acd-b"), "asset_path": "plugins/acd/agents/acd-a.md"},
            ],
            "asset paths",
        ),
        (
            [_entry("acd-a", "acd.role.same"), _entry("acd-b", "acd.role.same")],
            "section names",
        ),
        ([_entry("acd-b"), _entry("acd-a")], "sorted"),
    ],
)
def test_prompt_manifest_rejects_invalid_entries(
    entries: list[dict[str, str]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        RolePromptManifest.model_validate({"entries": entries})


def test_prompt_drift_report_supports_unknown_fallback() -> None:
    report = PromptDriftReport(status="unknown", reason="manifest parse failed")
    assert report.model_dump(mode="json") == {
        "drifted_roles": [],
        "missing_roles": [],
        "reason": "manifest parse failed",
        "status": "unknown",
        "unregistered_roles": [],
    }


def test_prompt_manifest_rejects_non_static_cache_tier() -> None:
    value = _entry("acd-test")
    value["cache_tier"] = "dynamic"
    with pytest.raises(ValidationError):
        RolePromptManifest.model_validate({"entries": [value]})
