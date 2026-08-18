"""Deterministic ACD role prompt sections and manifest verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from openhands.sdk.context.prompts.presets import PromptPreset, create_registry
from openhands.sdk.context.prompts.registry import PromptRegistry
from openhands.sdk.context.prompts.section import CacheTier, PromptContext
from openhands.sdk.subagent import AgentDefinition
from pydantic import ValidationError
from yaml import YAMLError

from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.prompt_manifest import (
    PromptDriftReport,
    RolePromptManifest,
    RolePromptManifestEntry,
)

ROLE_SECTION_PREFIX: Final[str] = "acd.role."
DEFAULT_MANIFEST_NAME: Final[str] = "prompt-manifest.json"


class PromptManifestError(ValueError):
    """Raised when role prompt assets cannot satisfy the manifest contract."""


class AcdRolePromptSection:
    """A static SDK prompt section backed by one ACD role definition."""

    name: str
    prompt: str
    cache_tier: CacheTier

    def __init__(self, name: str, prompt: str) -> None:
        self.name = name
        self.prompt = prompt
        self.cache_tier = CacheTier.STATIC

    def guard(self, ctx: PromptContext) -> bool:
        """Include the role prompt for every deterministic prompt context."""
        return True

    def render(self, ctx: PromptContext) -> str | None:
        """Return the immutable role prompt body."""
        return self.prompt


def _sha256_bytes(value: bytes) -> Sha256:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _manifest_hash(manifest: RolePromptManifest) -> Sha256:
    value = manifest.model_dump(mode="json")
    value["canonical_hash"] = "unknown"
    return canonical_json_sha256(value)


def _asset_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PromptManifestError(
            f"agent asset is outside manifest root: {path}"
        ) from exc
    if not relative.parts or ".." in relative.parts:
        raise PromptManifestError(f"agent asset path is not relative: {path}")
    return relative.as_posix()


def _load_entries(agent_dir: Path, root: Path) -> list[RolePromptManifestEntry]:
    if not agent_dir.is_dir():
        raise PromptManifestError(f"agent directory not found: {agent_dir}")
    paths = sorted(agent_dir.glob("acd-*.md"))
    if not paths:
        raise PromptManifestError(f"no ACD agent definitions found: {agent_dir}")

    entries: list[RolePromptManifestEntry] = []
    for path in paths:
        try:
            asset = path.read_bytes()
            asset.decode("utf-8")
            definition = AgentDefinition.load(path)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            YAMLError,
        ) as exc:
            raise PromptManifestError(f"agent prompt asset is invalid: {path}") from exc
        if definition.name != path.stem:
            raise PromptManifestError(
                f"agent role does not match filename: {path}"
            )
        if not definition.system_prompt.strip():
            raise PromptManifestError(f"agent role prompt is empty: {path}")
        entries.append(
            RolePromptManifestEntry(
                role=definition.name,
                asset_path=_asset_path(path, root),
                asset_hash=_sha256_bytes(asset),
                prompt_hash=_sha256_bytes(definition.system_prompt.encode("utf-8")),
                section_name=f"{ROLE_SECTION_PREFIX}{definition.name}",
                cache_tier="static",
            )
        )
    return entries


def generate_prompt_manifest(
    agent_dir: Path,
    *,
    root: Path,
) -> RolePromptManifest:
    """Generate the canonical manifest from ACD agent Markdown assets."""
    root = root.resolve()
    try:
        entries = _load_entries(agent_dir.resolve(), root)
        manifest = RolePromptManifest(entries=sorted(entries, key=lambda item: item.role))
    except (OSError, ValueError, ValidationError) as exc:
        if isinstance(exc, PromptManifestError):
            raise
        raise PromptManifestError("prompt manifest generation failed") from exc
    return manifest.model_copy(update={"canonical_hash": _manifest_hash(manifest)})


def load_prompt_manifest(path: Path) -> RolePromptManifest:
    """Load and validate a persisted role prompt manifest."""
    try:
        return RolePromptManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise PromptManifestError(f"prompt manifest is invalid: {path}") from exc


def check_prompt_manifest(
    agent_dir: Path,
    manifest_path: Path,
    *,
    root: Path,
) -> PromptDriftReport:
    """Compare current role prompt assets with their persisted manifest."""
    try:
        manifest = load_prompt_manifest(manifest_path)
        actual = generate_prompt_manifest(agent_dir, root=root)
        if manifest.canonical_hash != _manifest_hash(manifest):
            return PromptDriftReport(
                status="unknown", reason="prompt manifest canonical hash is invalid"
            )
    except PromptManifestError as exc:
        return PromptDriftReport(status="unknown", reason=str(exc))

    expected_by_role = {entry.role: entry for entry in manifest.entries}
    actual_by_role = {entry.role: entry for entry in actual.entries}
    unregistered_roles = sorted(set(actual_by_role) - set(expected_by_role))
    missing_roles = sorted(set(expected_by_role) - set(actual_by_role))
    drifted_roles = sorted(
        role
        for role in set(expected_by_role) & set(actual_by_role)
        if expected_by_role[role] != actual_by_role[role]
    )
    if missing_roles or unregistered_roles or drifted_roles:
        return PromptDriftReport(
            status="fail",
            drifted_roles=drifted_roles,
            unregistered_roles=unregistered_roles,
            missing_roles=missing_roles,
            reason="role prompt manifest drift detected",
        )
    return PromptDriftReport(status="pass")


def _load_sections(
    agent_dir: Path,
    manifest: RolePromptManifest,
    root: Path,
) -> list[AcdRolePromptSection]:
    sections: list[AcdRolePromptSection] = []
    by_path = {entry.asset_path: entry for entry in manifest.entries}
    for path in sorted(agent_dir.glob("acd-*.md")):
        try:
            definition = AgentDefinition.load(path)
            asset_path = _asset_path(path, root)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            YAMLError,
        ) as exc:
            raise PromptManifestError(f"agent prompt asset is invalid: {path}") from exc
        entry = by_path.get(asset_path)
        if entry is None:
            raise PromptManifestError(f"agent prompt is absent from manifest: {path}")
        sections.append(
            AcdRolePromptSection(name=entry.section_name, prompt=definition.system_prompt)
        )
    return sections


def create_acd_prompt_registry(
    agent_dir: Path,
    *,
    manifest_path: Path | None = None,
    root: Path,
    preset: PromptPreset = PromptPreset.DEFAULT,
) -> PromptRegistry:
    """Create the default SDK registry with verified ACD role sections added."""
    root = root.resolve()
    manifest_path = manifest_path or agent_dir / DEFAULT_MANIFEST_NAME
    report = check_prompt_manifest(agent_dir, manifest_path, root=root)
    if report.status != "pass":
        raise PromptManifestError(report.reason or "prompt manifest verification failed")
    manifest = load_prompt_manifest(manifest_path)
    registry = create_registry(preset)
    for section in _load_sections(agent_dir, manifest, root):
        registry.register(section)
    return registry


def write_prompt_manifest(
    agent_dir: Path,
    manifest_path: Path,
    *,
    root: Path,
) -> RolePromptManifest:
    """Generate and persist a deterministic role prompt manifest."""
    manifest = generate_prompt_manifest(agent_dir, root=root)
    value = manifest.model_dump(mode="json")
    manifest_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
