"""Pure helpers for identifying and validating archived LCSC records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast


@dataclass(frozen=True)
class LcscRecordIdentity:
    manufacturer_part: str | None
    package: str | None
    manufacturer: str | None
    supplier_part: str | None
    description: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "manufacturer_part": self.manufacturer_part,
            "package": self.package,
            "manufacturer": self.manufacturer,
            "supplier_part": self.supplier_part,
            "description": self.description,
        }


def _mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _string(mapping: Mapping[str, object] | None, key: str) -> str | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    return value if isinstance(value, str) else None


def extract_lcsc_identity(response: Mapping[str, object]) -> LcscRecordIdentity:
    """Extract stable identity fields from an EasyEDA product response."""
    result = _mapping(response.get("result"))
    data_string = _mapping(result.get("dataStr")) if result is not None else None
    head = _mapping(data_string.get("head")) if data_string is not None else None
    parameters = _mapping(head.get("c_para")) if head is not None else None
    description = _string(result, "description")
    if description is None:
        description = _string(result, "title")
    return LcscRecordIdentity(
        manufacturer_part=_string(parameters, "Manufacturer Part"),
        package=_string(parameters, "package"),
        manufacturer=_string(parameters, "Manufacturer"),
        supplier_part=_string(parameters, "Supplier Part"),
        description=description,
    )


def normalize_part_number(value: str) -> str:
    """Normalize a declared or observed part number for comparison."""
    return " ".join(value.strip().upper().split())


@dataclass(frozen=True)
class LcscMpnCheck:
    state: Literal["match", "mismatch", "unknown"]
    declared_mpn: str | None
    observed_manufacturer_part: str | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "declared_mpn": self.declared_mpn,
            "observed_manufacturer_part": self.observed_manufacturer_part,
            "reason": self.reason,
        }


def check_declared_mpn(
    identity: LcscRecordIdentity, *, declared_mpn: str | None
) -> LcscMpnCheck:
    """Compare a declared MPN with the record's Manufacturer Part."""
    return _check_declared_value(
        declared=declared_mpn,
        observed=identity.manufacturer_part,
        declared_label="MPN",
        observed_label="Manufacturer Part",
    )


def check_declared_package(
    identity: LcscRecordIdentity, *, declared_package: str | None
) -> LcscMpnCheck:
    """Compare a declared package with the record's package."""
    return _check_declared_value(
        declared=declared_package,
        observed=identity.package,
        declared_label="package",
        observed_label="package",
    )


def _check_declared_value(
    *,
    declared: str | None,
    observed: str | None,
    declared_label: str,
    observed_label: str,
) -> LcscMpnCheck:
    if not declared or not normalize_part_number(declared) or not observed:
        return LcscMpnCheck(
            state="unknown",
            declared_mpn=declared,
            observed_manufacturer_part=observed,
            reason=(
                f"declared {declared_label} or observed {observed_label} is missing"
                if declared
                else f"declared {declared_label} is missing"
            ),
        )
    if normalize_part_number(declared) == normalize_part_number(observed):
        return LcscMpnCheck(
            state="match",
            declared_mpn=declared,
            observed_manufacturer_part=observed,
            reason="",
        )
    return LcscMpnCheck(
        state="mismatch",
        declared_mpn=declared,
        observed_manufacturer_part=observed,
        reason=(
            f"declared {declared_label} {declared!r} does not match observed "
            f"{observed_label} {observed!r}"
        ),
    )


def check_declared_lcsc(
    identity: LcscRecordIdentity, *, declared_lcsc: str | None
) -> LcscMpnCheck:
    """Compare a declared LCSC number with the record's Supplier Part."""
    return _check_declared_value(
        declared=declared_lcsc,
        observed=identity.supplier_part,
        declared_label="LCSC",
        observed_label="Supplier Part",
    )


__all__ = [
    "LcscMpnCheck",
    "LcscRecordIdentity",
    "check_declared_lcsc",
    "check_declared_mpn",
    "check_declared_package",
    "extract_lcsc_identity",
    "normalize_part_number",
]
