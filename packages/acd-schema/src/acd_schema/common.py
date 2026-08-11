"""Shared value types for ACD contracts.

Mirrors ``schemas/common.schema.json``. Unknown values are explicit
(``"unknown"``) and are treated fail-closed by consumers.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

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
