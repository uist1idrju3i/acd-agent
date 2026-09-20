"""Catalog-derived pin function projection for selected parts."""

from __future__ import annotations

from typing import cast

from acd.schema.design_graph import AttrValue
from acd.schema.parts_catalog import PartCplOrientation


def pin_function_attrs(
    orientation: PartCplOrientation | None,
    catalog_id: str,
    catalog_hash: str,
) -> dict[str, AttrValue]:
    """Project the catalog pin function map with its catalog provenance.

    A missing catalog mapping stays unknown: no attribute is produced, so the
    downstream GPIO and topology predicates fail closed instead of guessing.
    """
    if orientation is None:
        return {}
    if not orientation.pin_functions and not orientation.pin_aliases:
        return {}
    values: dict[str, object] = {
        "pin_function_source": "parts_catalog",
        "pin_function_source_ref": f"{catalog_id}:{catalog_hash}",
    }
    if orientation.pin_functions:
        values["cpl_rotation_pin_functions"] = list(orientation.pin_functions)
    if orientation.pin_aliases:
        values["cpl_rotation_pin_aliases"] = list(orientation.pin_aliases)
    return cast(dict[str, AttrValue], values)


__all__ = ["pin_function_attrs"]
