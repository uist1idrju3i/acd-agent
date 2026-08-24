"""Shared CPL orientation attribute projection."""

from __future__ import annotations

from typing import cast

from acd.core.naming import artifact_prefix
from acd.schema.design_fixture import FixtureCplOrientationEvidence
from acd.schema.design_graph import AttrValue
from acd.schema.parts_catalog import PartCplOrientation

CPL_ORIENTATION_ATTR_KEYS = frozenset(
    {
        "basis",
        "source_url",
        "evidence_at",
        "evidence_method",
        "evidence_revision",
        "evidence_basis",
        "evidence_note",
        "offset_deg",
        "polarized",
        "pin_functions",
        "pin_aliases",
        "unverified_pads",
        "unverified_pad_reason",
        "unverified_pad_source",
        "geometry_exception",
        "geometry_exception_reason",
        "geometry_exception_source",
    }
)


def cpl_orientation_attrs(
    orientation: PartCplOrientation | None,
    evidence: FixtureCplOrientationEvidence | None,
    graph_id: str,
    graph_revision: str,
    refdes: str,
) -> dict[str, AttrValue]:
    """Project complete CPL metadata only when design evidence is declared."""
    if orientation is None or evidence is None:
        return {}

    values = {
        **orientation.model_dump(mode="json", exclude_defaults=True),
        **evidence.model_dump(mode="json"),
        "evidence_revision": f"{graph_id}-{graph_revision}",
    }
    unexpected = set(values) - CPL_ORIENTATION_ATTR_KEYS
    if unexpected:
        raise ValueError(
            "unsupported CPL orientation attributes: " + ", ".join(sorted(unexpected))
        )
    source = values.get("geometry_exception_source")
    if isinstance(source, str):
        try:
            values["geometry_exception_source"] = source.format(
                artifact_prefix=artifact_prefix(graph_id),
                refdes=refdes,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{refdes}: malformed CPL geometry evidence source"
            ) from exc
    return cast(
        dict[str, AttrValue],
        {"cpl_rotation_" + key: value for key, value in values.items()},
    )


__all__ = ["CPL_ORIENTATION_ATTR_KEYS", "cpl_orientation_attrs"]
