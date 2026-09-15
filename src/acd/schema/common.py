"""Shared value types for the canonical Pydantic ACD contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Annotated, Any, ClassVar, Final, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, model_validator

SchemaVersion = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+$")]
Revision = Annotated[str, StringConstraints(pattern=r"^r[0-9]+(\+WA-[0-9]{3,})?$")]
WorkaroundId = Annotated[str, StringConstraints(pattern=r"^WA-[0-9]{3,}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
HashOrUnknown = Sha256 | Literal["unknown"]
NodeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]*$")]
IdempotencyKey = Annotated[str, StringConstraints(min_length=8)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Timestamp = AwareDatetime

CURRENT_SCHEMA_VERSION: SchemaVersion = "0.1"
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset({CURRENT_SCHEMA_VERSION})

UNKNOWN: Literal["unknown"] = "unknown"

# A version string is either a concrete non-empty version or explicitly unknown.
VersionOrUnknown = NonEmptyStr


def base_revision(revision: str) -> str:
    """Return the base portion of a canonical or derived revision."""
    return revision.split("+", 1)[0]


class AcdModel(BaseModel):
    """Base model for all ACD contracts: strict, immutable, fail-closed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class SchemaVersionError(ValueError):
    """Raised when a document declares a schema version that cannot be read."""


SchemaMigration = Callable[[dict[str, Any]], dict[str, Any]]
"""Rewrite a document from one schema version to the next; must set `schema_version`."""

_SCHEMA_MIGRATIONS: dict[tuple[str, str], SchemaMigration] = {}


def register_schema_migration(
    from_version: str, to_version: str, migration: SchemaMigration
) -> None:
    """Register a single-step migration; re-registering a step is an error."""
    key = (from_version, to_version)
    if key in _SCHEMA_MIGRATIONS:
        raise SchemaVersionError(
            f"schema migration {from_version}->{to_version} is registered twice"
        )
    _SCHEMA_MIGRATIONS[key] = migration


def migrate_schema_document(
    document: dict[str, Any],
    *,
    supported: frozenset[str] = SUPPORTED_SCHEMA_VERSIONS,
    current: str = CURRENT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Return `document` at a supported schema version or fail closed.

    Documents already at a supported version are returned unchanged. Older versions
    are migrated one registered step at a time toward `current`; a missing or
    non-string version, an unregistered step, or a cycle raises `SchemaVersionError`.
    """
    version = document.get("schema_version")
    if not isinstance(version, str):
        raise SchemaVersionError("schema_version is missing or not a string")
    if version in supported:
        return document
    visited = {version}
    migrated = document
    while version not in supported:
        step = next(
            ((source, target) for (source, target) in _SCHEMA_MIGRATIONS if source == version),
            None,
        )
        if step is None:
            raise SchemaVersionError(
                f"schema_version {version!r} is unsupported and has no migration to {current!r}"
            )
        migrated = _SCHEMA_MIGRATIONS[step](dict(migrated))
        version = migrated.get("schema_version")
        if not isinstance(version, str) or version in visited:
            raise SchemaVersionError(
                f"schema migration {step[0]}->{step[1]} produced an invalid version"
            )
        visited.add(version)
    return migrated


class VersionedAcdModel(AcdModel):
    """Contract root that migrates and checks `schema_version` before validation.

    Subclasses override `supported_schema_versions` when they accept more than the
    repository-wide `SUPPORTED_SCHEMA_VERSIONS`.
    """

    supported_schema_versions: ClassVar[frozenset[str]] = SUPPORTED_SCHEMA_VERSIONS

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION

    @model_validator(mode="before")
    @classmethod
    def _migrate_schema_version(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        document = cast(dict[str, Any], data)
        if "schema_version" not in document:
            return document
        return migrate_schema_document(document, supported=cls.supported_schema_versions)


def is_unknown(value: str) -> bool:
    """Return True when a value is the explicit unknown sentinel."""
    return value == UNKNOWN


def contains_unknown(value: object) -> bool:
    """Return True when a nested JSON-compatible value contains unknown."""
    if isinstance(value, str):
        return is_unknown(value)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return any(contains_unknown(item) for item in mapping.values())
    if isinstance(value, list):
        items = cast(list[object], value)
        return any(contains_unknown(item) for item in items)
    return False


# A digest whose body is a single repeated character carries no content and is a
# placeholder rather than a measured hash.
_PLACEHOLDER_HASH = re.compile(r"^sha256:([0-9a-f])\1{63}$")

# Identifier substrings that mark synthesized order records. Such records must
# never stand in for a real counterparty quote.
PLACEHOLDER_ID_MARKERS: Final[tuple[str, ...]] = (
    "dummy",
    "placeholder",
    "sample",
    "example",
    "fake",
    "todo",
    "tbd",
    "test-quote",
)


def is_placeholder_hash(value: str) -> bool:
    """Return True when a digest string is a content-free placeholder."""
    return _PLACEHOLDER_HASH.match(value) is not None


def contains_placeholder_hash(value: object) -> bool:
    """Return True when a nested JSON-compatible value holds a placeholder digest."""
    if isinstance(value, str):
        return is_placeholder_hash(value)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return any(contains_placeholder_hash(item) for item in mapping.values())
    if isinstance(value, list):
        items = cast(list[object], value)
        return any(contains_placeholder_hash(item) for item in items)
    return False


def is_placeholder_identifier(value: str) -> bool:
    """Return True when an identifier is marked as synthesized or placeholder."""
    lowered = value.strip().lower()
    if not lowered:
        return True
    if any(marker in lowered for marker in PLACEHOLDER_ID_MARKERS):
        return True
    stripped = re.sub(r"[^a-z0-9]", "", lowered)
    return bool(stripped) and set(stripped) <= {"0"}


def canonical_json_sha256(value: object) -> Sha256:
    """Return the SHA-256 digest of a canonical JSON-compatible value."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def canonical_sha256(model: AcdModel) -> Sha256:
    """Return the SHA-256 digest of a model's canonical JSON representation."""
    return canonical_json_sha256(model.model_dump(mode="json"))
