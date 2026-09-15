"""Fail-closed schema_version handling and load-time migration hooks."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from acd.schema import common
from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    SchemaVersionError,
    VersionedAcdModel,
    migrate_schema_document,
    register_schema_migration,
)
from acd.schema.design_graph import DesignGraph


@pytest.fixture
def isolated_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common, "_SCHEMA_MIGRATIONS", {})


def _graph(version: str) -> dict[str, Any]:
    return {"schema_version": version, "graph_id": "g", "revision": "r1", "nodes": []}


def test_current_version_is_supported() -> None:
    assert CURRENT_SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS


def test_supported_document_is_returned_unchanged() -> None:
    document = _graph(CURRENT_SCHEMA_VERSION)
    assert migrate_schema_document(document) is document


def test_missing_or_non_string_version_fails_closed() -> None:
    with pytest.raises(SchemaVersionError):
        migrate_schema_document({"graph_id": "g"})
    with pytest.raises(SchemaVersionError):
        migrate_schema_document({"schema_version": 1})


def test_unsupported_version_without_migration_fails_closed(
    isolated_migrations: None,
) -> None:
    with pytest.raises(SchemaVersionError, match=r"9\.9"):
        migrate_schema_document(_graph("9.9"))


def test_design_graph_rejects_unknown_future_version(isolated_migrations: None) -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        DesignGraph.model_validate(_graph("9.9"))


def test_registered_migration_chain_is_applied_in_order(isolated_migrations: None) -> None:
    def to_0_0b(document: dict[str, Any]) -> dict[str, Any]:
        return {**document, "schema_version": "0.0", "graph_id": document["id"]}

    def to_current(document: dict[str, Any]) -> dict[str, Any]:
        migrated = {k: v for k, v in document.items() if k != "id"}
        migrated["schema_version"] = CURRENT_SCHEMA_VERSION
        return migrated

    register_schema_migration("0.a", "0.0", to_0_0b)
    register_schema_migration("0.0", CURRENT_SCHEMA_VERSION, to_current)
    legacy = {"schema_version": "0.a", "id": "legacy", "revision": "r1", "nodes": []}
    graph = DesignGraph.model_validate(legacy)
    assert graph.schema_version == CURRENT_SCHEMA_VERSION
    assert graph.graph_id == "legacy"
    assert legacy["schema_version"] == "0.a", "input document must not be mutated"


def test_duplicate_migration_registration_fails_closed(isolated_migrations: None) -> None:
    register_schema_migration("0.0", CURRENT_SCHEMA_VERSION, lambda d: d)
    with pytest.raises(SchemaVersionError):
        register_schema_migration("0.0", CURRENT_SCHEMA_VERSION, lambda d: d)


def test_migration_that_does_not_advance_version_fails_closed(
    isolated_migrations: None,
) -> None:
    register_schema_migration("0.0", CURRENT_SCHEMA_VERSION, lambda d: d)
    with pytest.raises(SchemaVersionError, match="invalid version"):
        migrate_schema_document(_graph("0.0"))


def test_subclass_may_widen_supported_versions() -> None:
    class Wide(VersionedAcdModel):
        supported_schema_versions = frozenset({CURRENT_SCHEMA_VERSION, "1.0"})

    assert Wide.model_validate({"schema_version": "1.0"}).schema_version == "1.0"
    with pytest.raises(ValidationError):
        VersionedAcdModel.model_validate({"schema_version": "1.0"})
