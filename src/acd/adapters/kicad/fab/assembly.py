"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""
# pyright: reportUnusedImport=false
# pyright: reportUnusedImport=false
# ruff: noqa

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.apertures import (  # pyright: ignore[reportMissingTypeStubs]
    CircleAperture,
    ObroundAperture,
    RectangleAperture,
)
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.graphic_objects import (  # pyright: ignore[reportMissingTypeStubs]
    Arc,
    Flash,
    Line,
    Region,
)
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd.adapters.kicad.library import SymbolLibrary
from acd.adapters.kicad.placement import rotate_point
from acd.core.board_model import BoardModel, RoutedDesign, RoutedVia
from acd.core.bom import refdes_key
from acd.core.electrical import ComponentView, ElectricalLane
from acd.core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd.core.routing_width import NetWidthRequirement
from acd.core.silkscreen import SilkscreenLane


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403


def parse_pos_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Ref", "PosX", "PosY", "Rot", "Side"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{path.name}: KiCad position CSV missing required columns")
    return rows


def jlcpcb_cpl_csv(rows: Iterable[dict[str, str]], fitted: set[str]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Designator", "Mid X", "Mid Y", "Rotation", "Layer"))
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: item["Ref"]):
        ref = row["Ref"]
        if ref not in fitted:
            continue
        seen.add(ref)
        side = row["Side"].strip().lower()
        if side not in {"top", "bottom"}:
            raise FabOutputError(f"{ref}: unknown placement side {row['Side']!r}")
        writer.writerow((ref, row["PosX"], row["PosY"], row["Rot"], side.title()))
    if seen != fitted:
        raise FabOutputError(f"CPL fitted designator mismatch: missing={sorted(fitted - seen)}")
    return output.getvalue()


def _bbox_center(
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float] | None:
    if bbox is None:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _pad_bbox_center(fp: FootprintMeasurement) -> tuple[float, float] | None:
    if not fp.pads:
        return None
    xs = [pad.x_mm for pad in fp.pads]
    ys = [pad.y_mm for pad in fp.pads]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _cpl_position(fp: FootprintMeasurement, basis: str) -> tuple[float, float] | None:
    if basis == "footprint_origin":
        return (fp.x_mm, fp.y_mm)
    if basis == "body_bbox_center":
        return _bbox_center(fp.body_bbox_mm)
    if basis == "pad_bbox_center":
        return _pad_bbox_center(fp)
    raise FabOutputError(f"{fp.refdes}: unsupported CPL position basis {basis!r}")


def _geometry_centers(fp: FootprintMeasurement) -> dict[str, tuple[float, float] | None]:
    return {
        "footprint_origin": (fp.x_mm, fp.y_mm),
        "body_bbox_center": _bbox_center(fp.body_bbox_mm),
        "pad_bbox_center": _pad_bbox_center(fp),
    }


def _centers_disagree(
    centers: Mapping[str, tuple[float, float] | None], tolerance_mm: float
) -> bool:
    present = [center for center in centers.values() if center is not None]
    return any(
        math.dist(first, second) > tolerance_mm
        for index, first in enumerate(present)
        for second in present[index + 1 :]
    )


def apply_cpl_contract(
    position_rows: tuple[dict[str, str], ...],
    board: BoardMeasurement,
    lane: ElectricalLane,
    profile: FabProfile,
    fitted: set[str],
    tolerance_mm: float = 0.001,
) -> tuple[tuple[dict[str, str], ...], dict[str, object]]:
    """Resolve and independently validate the declared CPL basis."""
    contract = cast(dict[str, object], profile.data["cpl_contract"])
    default_position_basis = str(contract["position_basis"])
    default_rotation_basis = str(contract["rotation_basis"])
    components = {component.refdes: component for component in lane.components}
    footprints = {fp.refdes: fp for fp in board.footprints}
    unknown_position: list[str] = []
    unknown_rotation: list[str] = []
    errors: list[str] = []
    resolved: list[dict[str, str]] = []
    resolved_bases: dict[str, str] = {}
    rotation_offsets: dict[str, float] = {}

    for source in sorted(position_rows, key=lambda row: refdes_key(row["Ref"])):
        ref = source["Ref"]
        if ref not in fitted:
            continue
        component = components.get(ref)
        fp = footprints.get(ref)
        if component is None or fp is None:
            errors.append(f"{ref}: CPL basis source is absent from independent sources")
            continue
        centers = _geometry_centers(fp)
        position_basis = default_position_basis
        if _centers_disagree(centers, tolerance_mm):
            position_basis = component.cpl_position_basis or ""
            if not position_basis:
                unknown_position.append(ref)
                errors.append(
                    f"{ref}: CPL position basis is unknown; "
                    "component declaration and provenance are required"
                )
            elif (
                component.cpl_position_source_url is None
                or component.cpl_position_evidence_at is None
            ):
                unknown_position.append(ref)
                errors.append(
                    f"{ref}: CPL position basis {position_basis!r} has no source URL "
                    "and confirmation date"
                )
            elif component.cpl_position_evidence_basis not in {"estimated", "confirmed"}:
                errors.append(
                    f"{ref}: CPL position evidence basis must be 'estimated' or 'confirmed'"
                )
            elif component.cpl_position_evidence_basis == "confirmed" and (
                component.cpl_position_evidence_method is None
                or component.cpl_position_evidence_revision is None
                or component.cpl_position_evidence_note is None
            ):
                errors.append(
                    f"{ref}: confirmed CPL position evidence requires method, date, "
                    "revision, and note"
                )
            elif component.cpl_position_evidence_basis == "estimated":
                unknown_position.append(ref)
        if position_basis:
            resolved_bases[ref] = position_basis
            try:
                position = _cpl_position(fp, position_basis)
            except FabOutputError as exc:
                errors.append(str(exc))
                position = None
            if position is None:
                errors.append(f"{ref}: CPL position basis {position_basis!r} is unmeasurable")
            else:
                output = dict(source)
                output["PosX"] = f"{position[0]:.6f}"
                output["PosY"] = f"{-position[1]:.6f}"
                rotation = float(source["Rot"])
                if default_rotation_basis == "component_part_number":
                    if (
                        component.cpl_rotation_basis != "component_part_number"
                        or component.cpl_rotation_source_url is None
                        or component.cpl_rotation_offset_deg is None
                        or component.cpl_rotation_evidence_at is None
                        or component.cpl_rotation_evidence_basis != "confirmed"
                        or component.cpl_rotation_evidence_method is None
                        or component.cpl_rotation_evidence_revision is None
                        or component.cpl_rotation_evidence_note is None
                    ):
                        unknown_rotation.append(ref)
                        rotation_offsets[ref] = 0.0
                    else:
                        rotation += component.cpl_rotation_offset_deg
                        rotation_offsets[ref] = component.cpl_rotation_offset_deg
                elif default_rotation_basis != "kicad_footprint":
                    errors.append(
                        f"{ref}: unsupported CPL rotation basis {default_rotation_basis!r}"
                    )
                output["Rot"] = f"{rotation % 360.0:.6f}"
                resolved.append(output)

    report: dict[str, object] = {
        "schema_version": "0.1",
        "status": "fail" if errors or unknown_position or unknown_rotation else "pass",
        "position_basis": default_position_basis,
        "rotation_basis": default_rotation_basis,
        "unknowns": {
            "cpl_position_basis": sorted(set(unknown_position), key=refdes_key),
            "cpl_rotation_basis_fab_lcsc": sorted(set(unknown_rotation), key=refdes_key),
        },
        "position_bases": resolved_bases,
        "rotation_offsets": rotation_offsets,
        "errors": errors,
    }
    if errors:
        raise CplBasisError(
            "CPL basis gate failed: " + "; ".join(errors),
            report,
        )
    return tuple(resolved), report


def jlcpcb_bom_csv(lane: ElectricalLane) -> str:
    fitted = tuple(comp for comp in lane.components if comp.assembly == "fitted")
    if any(not comp.lcsc for comp in fitted):
        raise FabOutputError("fitted component without LCSC part number (fail-closed)")
    grouped: dict[tuple[str, str, str], list[ComponentView]] = {}
    for comp in fitted:
        key = (comp.lcsc, comp.mpn, comp.library.footprint)
        grouped.setdefault(key, []).append(comp)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Comment", "Designator", "Footprint", "LCSC Part #"))
    for (lcsc, mpn, footprint), components in sorted(
        grouped.items(),
        key=lambda item: min(refdes_key(c.refdes) for c in item[1]),
    ):
        values = {comp.value for comp in components}
        comment = next(iter(values)) if len(values) == 1 else mpn
        refs = sorted((comp.refdes for comp in components), key=refdes_key)
        writer.writerow((comment, ",".join(refs), footprint, lcsc))
    return output.getvalue()


def cross_validate_bom(
    bom_path: Path,
    lane: ElectricalLane,
    fitted: set[str],
) -> None:
    with bom_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    required = {"Comment", "Designator", "Footprint", "LCSC Part #"}
    if not rows or not required <= set(rows[0]):
        raise FabOutputError(f"{bom_path.name}: BOM missing required columns")
    components = {comp.refdes: comp for comp in lane.components if comp.assembly == "fitted"}
    seen: set[str] = set()
    for row in rows:
        refs = tuple(ref.strip() for ref in row["Designator"].split(",") if ref.strip())
        if not refs:
            raise FabOutputError(f"{bom_path.name}: BOM row has no designator")
        overlap = seen.intersection(refs)
        if overlap:
            raise FabOutputError(
                f"{bom_path.name}: duplicate designators {sorted(overlap, key=refdes_key)}"
            )
        seen.update(refs)
        lcsc = row["LCSC Part #"].strip()
        footprint = row["Footprint"].strip()
        if not lcsc:
            raise FabOutputError(f"{bom_path.name}: BOM row has empty LCSC part number")
        for ref in refs:
            comp = components.get(ref)
            if comp is None:
                raise FabOutputError(f"{bom_path.name}: unknown fitted designator {ref!r}")
            if comp.lcsc != lcsc:
                raise FabOutputError(f"{ref}: BOM LCSC differs from graph")
            if comp.library.footprint != footprint:
                raise FabOutputError(f"{ref}: BOM footprint differs from graph")
    if seen != fitted:
        raise FabOutputError(
            f"BOM fitted designator mismatch: missing={sorted(fitted - seen, key=refdes_key)}, "
            f"extra={sorted(seen - fitted, key=refdes_key)}"
        )


def cross_validate_cpl(
    cpl_path: Path,
    position_rows: tuple[dict[str, str], ...],
    board: BoardMeasurement,
    fitted: set[str],
    position_bases: Mapping[str, str] | None = None,
    rotation_offsets: Mapping[str, float] | None = None,
    tolerance_mm: float = 0.001,
    tolerance_deg: float = 0.01,
) -> None:
    with cpl_path.open(newline="", encoding="utf-8-sig") as stream:
        cpl_rows = tuple(csv.DictReader(stream))
    if {row["Designator"] for row in cpl_rows} != fitted:
        raise FabOutputError("CPL designator set differs from fitted graph components")
    source = {row["Ref"]: row for row in position_rows}
    footprints = {fp.refdes: fp for fp in board.footprints}
    for row in cpl_rows:
        ref = row["Designator"]
        if ref not in source or ref not in footprints:
            raise FabOutputError(f"CPL refdes {ref!r} is absent from independent sources")
        expected = source[ref]
        actual = footprints[ref]
        if abs(float(expected["PosX"]) - actual.x_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: position source X differs from routed board origin")
        if abs(-float(expected["PosY"]) - actual.y_mm) > tolerance_mm:
            raise FabOutputError(f"{ref}: position source Y differs from routed board origin")
        basis = (position_bases or {}).get(ref, "footprint_origin")
        selected = _cpl_position(actual, basis)
        if selected is None:
            raise FabOutputError(f"{ref}: selected CPL basis {basis!r} is unmeasurable")
        if abs(float(row["Mid X"]) - selected[0]) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL X differs from selected independent basis")
        if abs(-float(row["Mid Y"]) - selected[1]) > tolerance_mm:
            raise FabOutputError(f"{ref}: CPL Y differs from selected independent basis")
        expected_rotation = (actual.rotation_deg + (rotation_offsets or {}).get(ref, 0.0)) % 360.0
        if abs(float(row["Rotation"]) - expected_rotation) > tolerance_deg:
            raise FabOutputError(f"{ref}: CPL rotation differs from declared basis")
        if row["Layer"].lower() != expected["Side"].lower():
            raise FabOutputError(f"{ref}: CPL layer differs from position CSV")
