"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.cern_catalog``.
"""

from acd.core.manufacturing.cern_catalog import (
    CERN_CATALOG_ID,
    CERN_SOURCE_URL,
    CERN_SUBMODULE,
    CernCatalogError,
    ResolvedCernPart,
    cern_catalog_hash,
    cern_checkout_commit,
    pinned_cern_commit,
    resolve_cern_part,
)

__all__ = [
    "CERN_CATALOG_ID",
    "CERN_SOURCE_URL",
    "CERN_SUBMODULE",
    "CernCatalogError",
    "ResolvedCernPart",
    "cern_catalog_hash",
    "cern_checkout_commit",
    "pinned_cern_commit",
    "resolve_cern_part",
]
