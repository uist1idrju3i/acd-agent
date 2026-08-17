"""Validation helpers for reproducibly distributed ACD plugins."""

from __future__ import annotations

import re
from pathlib import Path

from openhands.sdk.plugin import PluginSource

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_RELEASE_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def validate_pinned_ref(ref: str | None) -> str:
    """Return an immutable plugin ref or raise a fail-closed ValueError."""
    if ref is None or not (_COMMIT_SHA.fullmatch(ref) or _RELEASE_TAG.fullmatch(ref)):
        raise ValueError("plugin ref must be a 40-character SHA or v<semver> tag")
    return ref


def acd_plugin_source(ref: str) -> PluginSource:
    """Build the pinned external ACD plugin source."""
    return PluginSource(
        source="github:uist1idrju3i/acd-agent",
        repo_path="plugins/acd",
        ref=validate_pinned_ref(ref),
    )


def validate_plugin_source(source: PluginSource) -> PluginSource:
    """Validate external refs while permitting local development sources."""
    if not Path(source.source).exists():
        validate_pinned_ref(source.ref)
    return source
