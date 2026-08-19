"""Shared value types for the canonical Pydantic ACD contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, ClassVar, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

SchemaVersion = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+$")]
Revision = Annotated[str, StringConstraints(pattern=r"^r[0-9]+$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
HashOrUnknown = Sha256 | Literal["unknown"]
NodeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]*$")]
IdempotencyKey = Annotated[str, StringConstraints(min_length=8)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Timestamp = AwareDatetime

CURRENT_SCHEMA_VERSION: SchemaVersion = "0.1"

UNKNOWN: Literal["unknown"] = "unknown"

# A version string is either a concrete non-empty version or explicitly unknown.
VersionOrUnknown = NonEmptyStr


class AcdModel(BaseModel):
    """Base model for all ACD contracts: strict, immutable, fail-closed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


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
