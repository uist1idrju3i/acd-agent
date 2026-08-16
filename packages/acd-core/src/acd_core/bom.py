"""Deterministic graph-derived BOM projection.

Rows are grouped by (value, mpn, lcsc, footprint) and ordered by the smallest
refdes in each group; refdes lists inside a group are sorted naturally.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from acd_core.electrical import ComponentView, ElectricalLane

_HEADER = ("refdes", "qty", "value", "mpn", "lcsc", "footprint", "jlcpcb_class")


@dataclass(frozen=True)
class BomRow:
    refdes: tuple[str, ...]
    value: str
    mpn: str
    lcsc: str
    footprint: str
    jlcpcb_class: str


def refdes_key(refdes: str) -> tuple[str, int, str]:
    prefix = refdes.rstrip("0123456789")
    digits = refdes[len(prefix) :]
    return prefix, int(digits) if digits.isdigit() else 0, refdes


def build_bom(lane: ElectricalLane) -> tuple[BomRow, ...]:
    groups: dict[tuple[str, str, str, str, str], list[ComponentView]] = {}
    for comp in lane.components:
        key = (
            comp.value,
            comp.mpn,
            comp.lcsc,
            comp.library.footprint,
            comp.jlcpcb_class,
        )
        groups.setdefault(key, []).append(comp)
    rows = [
        BomRow(
            refdes=tuple(sorted((c.refdes for c in comps), key=refdes_key)),
            value=key[0],
            mpn=key[1],
            lcsc=key[2],
            footprint=key[3],
            jlcpcb_class=key[4],
        )
        for key, comps in groups.items()
    ]
    rows.sort(key=lambda r: refdes_key(r.refdes[0]))
    return tuple(rows)


def bom_csv(lane: ElectricalLane) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_HEADER)
    for row in build_bom(lane):
        writer.writerow(
            (
                " ".join(row.refdes),
                str(len(row.refdes)),
                row.value,
                row.mpn,
                row.lcsc,
                row.footprint,
                row.jlcpcb_class,
            )
        )
    return buffer.getvalue()
