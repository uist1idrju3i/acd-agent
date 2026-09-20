"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.lcsc_record``.
"""

from acd.core.manufacturing.lcsc_record import (
    LcscMpnCheck,
    LcscRecordIdentity,
    check_declared_lcsc,
    check_declared_mpn,
    check_declared_package,
    extract_lcsc_identity,
    normalize_part_number,
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
