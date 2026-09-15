"""Versioned profile holding the expected values used by design predicates.

The profile is a tracked JSON document under ``profiles/``; its canonical hash is
recorded next to predicate observations so evidence identifies which expectations
were applied. Loading fails closed on a missing, malformed, or unsupported document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator

from acd.core.fileio import read_json
from acd.pipeline.repository import repository_root
from acd.schema.common import (
    AcdModel,
    NonEmptyStr,
    VersionedAcdModel,
    canonical_json_sha256,
)

DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH = Path("profiles") / "design-predicates-default.json"

PositiveFloat = Annotated[float, Field(gt=0)]


class DesignPredicateProfileError(ValueError):
    """Raised when the design predicate profile cannot be loaded safely."""


class ImpedanceFormulaConstants(AcdModel):
    z0_factor: PositiveFloat
    denominator_factor: PositiveFloat
    log_factor: PositiveFloat
    pi_factor: PositiveFloat | None = None


class DesignPredicateProfileDocument(VersionedAcdModel):
    profile_id: NonEmptyStr
    usb_cc_expected_kohm: NonEmptyStr
    i2c_pullup_expected_kohm: NonEmptyStr
    strapping_gpios: tuple[Annotated[int, Field(ge=0)], ...]
    ldo_input_v: PositiveFloat
    ldo_output_v: PositiveFloat
    large_decoupling_uf: PositiveFloat
    small_decoupling_uf: PositiveFloat
    small_decoupling_tolerance_uf: PositiveFloat
    small_cap_distance_mm: PositiveFloat
    large_cap_distance_mm: PositiveFloat
    impedance_formula_constants: dict[NonEmptyStr, ImpedanceFormulaConstants]

    @field_validator("strapping_gpios")
    @classmethod
    def _sorted_unique_gpios(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value):
            raise ValueError("strapping_gpios must be unique")
        return tuple(sorted(value))


@dataclass(frozen=True)
class DesignPredicateProfile:
    document: DesignPredicateProfileDocument
    profile_hash: str
    path: Path

    @property
    def profile_id(self) -> str:
        return self.document.profile_id

    def provenance(self) -> dict[str, str]:
        """Identify the applied expectations inside predicate observations."""
        return {
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "schema_version": self.document.schema_version,
        }


def load_design_predicate_profile(path: Path | None = None) -> DesignPredicateProfile:
    profile_path = path or repository_root() / DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH
    try:
        value = read_json(profile_path)
        document = DesignPredicateProfileDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DesignPredicateProfileError(
            f"design predicate profile is invalid: {profile_path}: {exc}"
        ) from exc
    return DesignPredicateProfile(
        document=document,
        profile_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=profile_path,
    )


@lru_cache(maxsize=1)
def default_design_predicate_profile() -> DesignPredicateProfile:
    """The tracked repository profile; cached because it is immutable per checkout."""
    return load_design_predicate_profile()


__all__ = [
    "DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH",
    "DesignPredicateProfile",
    "DesignPredicateProfileDocument",
    "DesignPredicateProfileError",
    "ImpedanceFormulaConstants",
    "default_design_predicate_profile",
    "load_design_predicate_profile",
]
