"""Tests for ACD role prompt sections and manifest drift checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.context.prompts.section import Platform, PromptContext

from acd.openhands.session.prompts import (
    AcdRolePromptSection,
    PromptManifestError,
    check_prompt_manifest,
    create_acd_prompt_registry,
    generate_prompt_manifest,
    write_prompt_manifest,
)
from acd.schema.common import canonical_json_sha256


def _write_agent(
    agent_dir: Path,
    filename: str = "acd-test.md",
    *,
    name: str = "acd-test",
    body: str = "Test role prompt.",
) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / filename
    path.write_text(f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> tuple[Path, Path]:
    agent_dir = tmp_path / "agents"
    _write_agent(agent_dir)
    manifest_path = agent_dir / "prompt-manifest.json"
    write_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    return agent_dir, manifest_path


def test_registry_adds_acd_sections_without_removing_sdk_sections(tmp_path: Path) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    registry = create_acd_prompt_registry(
        agent_dir, manifest_path=manifest_path, root=tmp_path
    )
    blocks = registry.build(PromptContext(platform=Platform.LINUX))
    assert "Test role prompt." in blocks.static
    assert "<SOUL>" in blocks.static


def test_role_prompt_section_is_static_and_always_renders() -> None:
    section = AcdRolePromptSection(name="acd.role.test", prompt="body")
    context = PromptContext(platform=Platform.LINUX)
    assert section.cache_tier.value == "static"
    assert section.guard(context)
    assert section.render(context) == "body"


def test_manifest_generation_is_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    first_manifest = manifest_path.read_bytes()
    first_generated = generate_prompt_manifest(agent_dir, root=tmp_path)
    monkeypatch.chdir("/")
    second_generated = generate_prompt_manifest(agent_dir, root=tmp_path)
    assert second_generated == first_generated
    write_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    assert manifest_path.read_bytes() == first_manifest
    assert json.loads(first_manifest)["canonical_hash"] == first_generated.canonical_hash
    assert check_prompt_manifest(agent_dir, manifest_path, root=tmp_path).status == "pass"


def test_prompt_asset_drift_is_fail_closed(tmp_path: Path) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    (agent_dir / "acd-test.md").write_text(
        "---\nname: acd-test\n---\n\nChanged role prompt.\n", encoding="utf-8"
    )
    report = check_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    assert report.status == "fail"
    assert report.drifted_roles == ["acd-test"]


@pytest.mark.parametrize(
    "case",
    [
        "missing-dir",
        "empty-dir",
        "empty-body",
        "name-mismatch",
        "invalid-utf8",
        "malformed-frontmatter",
    ],
)
def test_prompt_asset_contract_fail_closed(tmp_path: Path, case: str) -> None:
    agent_dir = tmp_path / "agents"
    manifest_path = agent_dir / "prompt-manifest.json"
    if case == "missing-dir":
        pass
    else:
        agent_dir.mkdir()
        if case == "empty-dir":
            pass
        elif case == "empty-body":
            _write_agent(agent_dir, body="   ")
        elif case == "name-mismatch":
            _write_agent(agent_dir, name="other")
        elif case == "invalid-utf8":
            (agent_dir / "acd-test.md").write_bytes(b"\xff\xfe")
        else:
            (agent_dir / "acd-test.md").write_text(
                "---\nname: [\n---\n\nbody\n", encoding="utf-8"
            )
    report = check_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    assert report.status == "unknown"


def test_prompt_manifest_parse_failure_is_unknown(tmp_path: Path) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    manifest_path.write_text("{not-json", encoding="utf-8")
    report = check_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    assert report.status == "unknown"


def test_prompt_manifest_entry_missing_and_extra_are_drift(tmp_path: Path) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["entries"][0]["role"] = "acd-other"
    value["entries"][0]["asset_path"] = "agents/acd-other.md"
    value["canonical_hash"] = "unknown"
    value["canonical_hash"] = canonical_json_sha256(value)
    manifest_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = check_prompt_manifest(agent_dir, manifest_path, root=tmp_path)
    assert report.status == "fail"
    assert report.unregistered_roles == ["acd-test"]
    assert report.missing_roles == ["acd-other"]


def test_create_registry_rejects_manifest_drift(tmp_path: Path) -> None:
    agent_dir, manifest_path = _manifest(tmp_path)
    manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(PromptManifestError):
        create_acd_prompt_registry(agent_dir, manifest_path=manifest_path, root=tmp_path)
