"""Tests for pinned plugin distribution sources."""

from __future__ import annotations

import pytest
from openhands.sdk.plugin import PluginSource

from acd.openhands.distribution.plugin import (
    acd_plugin_source,
    validate_pinned_ref,
    validate_plugin_source,
)


@pytest.mark.parametrize("ref", [None, "", "main", "abc123", "v1", "v1.2.3/evil"])
def test_variable_or_malformed_refs_fail_closed(ref: str | None) -> None:
    with pytest.raises(ValueError):
        validate_pinned_ref(ref)


def test_sha_and_release_tag_are_accepted() -> None:
    assert validate_pinned_ref("a" * 40) == "a" * 40
    assert validate_pinned_ref("v1.2.3") == "v1.2.3"


def test_external_plugin_source_requires_pinned_ref() -> None:
    with pytest.raises(ValueError):
        validate_plugin_source(PluginSource(source="github:owner/repo"))


def test_ssh_plugin_source_requires_pinned_ref() -> None:
    with pytest.raises(ValueError):
        validate_plugin_source(PluginSource(source="ssh://git@example.invalid/repo"))


def test_acd_plugin_source_is_pinned() -> None:
    source = acd_plugin_source("v1.2.3")
    assert source.source == "github:uist1idrju3i/acd-agent"
    assert source.repo_path == "plugins/acd"
    assert source.ref == "v1.2.3"
