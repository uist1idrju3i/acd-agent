"""Independent manufacturing measurements, DFM checks, and JLCPCB exports."""
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

from acd_adapter_kicad.library import SymbolLibrary
from acd_adapter_kicad.placement import rotate_point
from acd_core.board_model import BoardModel, RoutedDesign, RoutedVia
from acd_core.bom import refdes_key
from acd_core.electrical import ComponentView, ElectricalLane
from acd_core.fab import (
    FabOrderIntentView,
    FabProfile,
    ProcessAllowanceView,
    validate_allowances_against_profile,
)
from acd_core.routing_width import NetWidthRequirement
from acd_core.silkscreen import SilkscreenLane


from .common import *  # noqa: F401,F403
from .geometry import *  # noqa: F401,F403
from .sexpr_query import *  # noqa: F401,F403

PAD_SIZE_TOLERANCE_MM = 0.3
PAD_SIZE_MERGE_RATIO = 5.0


def _minimum_matching_error(
    actual: Sequence[tuple[float, float]], expected: Sequence[tuple[float, float]]
) -> float:
    distances = sorted({math.dist(left, right) for left in actual for right in expected})
    for threshold in distances:
        matched: dict[int, int] = {}

        def visit(
            index: int,
            seen: set[int],
            limit: float = threshold,
            assignments: dict[int, int] = matched,
        ) -> bool:
            for candidate, distance in enumerate(
                math.dist(actual[index], point) for point in expected
            ):
                if distance > limit or candidate in seen:
                    continue
                seen.add(candidate)
                previous = assignments.get(candidate)
                if previous is None or visit(previous, seen):
                    assignments[candidate] = index
                    return True
            return False

        if all(visit(index, set()) for index in range(len(expected))):
            return threshold
    raise FabOutputError("pin-function matching has no perfect assignment")


def _normalize_pin_function(name: str, aliases: Mapping[str, str]) -> str:
    normalized = re.sub(r"[^A-Z0-9+_-]", "", name.upper())
    normalized_aliases = {
        re.sub(r"[^A-Z0-9+_-]", "", source.upper()): re.sub(r"[^A-Z0-9+_-]", "", target.upper())
        for source, target in aliases.items()
    }
    return normalized_aliases.get(normalized, normalized)


def _minimum_matching_geometry_error(
    actual: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    expected: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    tolerance_mm: float,
) -> float:
    distances = sorted({math.dist(left[0], right[0]) for left in actual for right in expected})
    for threshold in distances:
        matched: dict[int, int] = {}

        def visit(
            expected_index: int,
            seen: set[int],
            limit: float = threshold,
            assignments: dict[int, int] = matched,
        ) -> bool:
            for candidate, point in enumerate(actual):
                if candidate in seen:
                    continue
                actual_size = point[1]
                expected_size = expected[expected_index][1]
                size_compatible = (
                    abs(actual_size[0] - expected_size[0]) <= tolerance_mm
                    and abs(actual_size[1] - expected_size[1]) <= tolerance_mm
                )
                if not size_compatible:
                    size_compatible = (
                        all(value > 0 for value in actual_size + expected_size)
                        and max(
                            expected_size[0] / actual_size[0],
                            expected_size[1] / actual_size[1],
                        )
                        <= PAD_SIZE_MERGE_RATIO
                    )
                if not size_compatible:
                    continue
                if math.dist(point[0], expected[expected_index][0]) > limit:
                    continue
                seen.add(candidate)
                previous = assignments.get(candidate)
                if previous is None or visit(previous, seen):
                    assignments[candidate] = expected_index
                    return True
            return False

        if all(visit(index, set()) for index in range(len(expected))):
            return threshold
    raise FabOutputError("geometry matching has no compatible perfect assignment")


def _parse_lcsc_pad_shape(shape: str) -> tuple[str, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 9 or fields[0] != "PAD":
        return None
    try:
        return fields[8], float(fields[2]), float(fields[3])
    except ValueError:
        return None


def _parse_lcsc_pad_geometry(
    shape: str,
) -> tuple[str, float, float, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 9 or fields[0] != "PAD":
        return None
    try:
        return fields[8], float(fields[2]), float(fields[3]), float(fields[4]), float(fields[5])
    except ValueError:
        return None


def _parse_lcsc_pin_shape(shape: str) -> tuple[str, str, float, float] | None:
    fields = shape.split("~")
    if len(fields) < 6 or fields[0] != "P":
        return None
    pin_name_match = re.search(r"~([^~]+)~(?:start|end)~", shape)
    if pin_name_match is None:
        return None
    try:
        return fields[3], pin_name_match.group(1), float(fields[4]), float(fields[5])
    except ValueError:
        return None


def load_lcsc_pin_centers(path: Path) -> tuple[tuple[str, str, float, float], ...]:
    """Read pin-function pad centers from an archived EasyEDA package response."""
    document = json.loads(path.read_text(encoding="utf-8"))
    package_shapes = document["response"]["result"]["packageDetail"]["dataStr"]["shape"]
    pad_shapes = [_parse_lcsc_pad_shape(str(shape)) for shape in package_shapes]
    pad_centers = {
        number: (x, y) for item in pad_shapes if item is not None for number, x, y in [item]
    }
    pin_shapes = package_shapes
    if not any(str(shape).startswith("P~") for shape in pin_shapes):
        pin_shapes = document["response"]["result"]["dataStr"]["shape"]
    pins = [_parse_lcsc_pin_shape(str(shape)) for shape in pin_shapes]
    parsed = tuple(
        (number, function, pad_centers[number][0], pad_centers[number][1])
        for item in pins
        if item is not None
        for number, function, _, _ in [item]
        if number in pad_centers
    )
    if not parsed:
        raise FabOutputError(f"{path}: archived LCSC response has no pin-function pads")
    return parsed


def load_lcsc_pin_geometries(
    path: Path,
) -> tuple[tuple[str, str, float, float, float, float], ...]:
    """Read pin functions and pad geometry from an archived EasyEDA response."""
    document = json.loads(path.read_text(encoding="utf-8"))
    package_shapes = document["response"]["result"]["packageDetail"]["dataStr"]["shape"]
    pad_geometries = [_parse_lcsc_pad_geometry(str(shape)) for shape in package_shapes]
    pads = {
        number: (x, y, width, height)
        for item in pad_geometries
        if item is not None
        for number, x, y, width, height in [item]
    }
    pin_shapes = package_shapes
    if not any(str(shape).startswith("P~") for shape in pin_shapes):
        pin_shapes = document["response"]["result"]["dataStr"]["shape"]
    parsed = tuple(
        (number, function, *pads[number])
        for item in [_parse_lcsc_pin_shape(str(shape)) for shape in pin_shapes]
        if item is not None
        for number, function, _, _ in [item]
        if number in pads
    )
    if not parsed:
        raise FabOutputError(f"{path}: archived LCSC response has no pin-function geometry")
    return parsed


def derive_lcsc_rotation_offset(
    footprint: FootprintMeasurement,
    lcsc_pin_centers: Sequence[tuple[str, str, float, float]],
    kicad_pin_functions: Mapping[str, str] | None = None,
    pin_name_aliases: Mapping[str, str] | None = None,
    tolerance_mm: float = 0.3,
    scale: float = 0.254,
    polarized: bool = True,
    lcsc_pin_geometries: Sequence[tuple[str, str, float, float, float, float]] | None = None,
    geometry_exception: bool = False,
) -> tuple[float, str]:
    """Derive a unique quarter-turn offset from pin-function geometry."""
    aliases = pin_name_aliases or {}
    if polarized and not kicad_pin_functions and not geometry_exception:
        raise FabOutputError(f"{footprint.refdes}: KiCad pin functions are required")
    all_kicad = [
        _inverse_rotate(
            pad.x_mm - footprint.x_mm,
            pad.y_mm - footprint.y_mm,
            footprint.rotation_deg,
        )
        for pad in footprint.pads
        if pad.number is not None
    ]
    if geometry_exception:
        if lcsc_pin_geometries is None:
            raise FabOutputError(f"{footprint.refdes}: geometry exception requires LCSC pad sizes")
        if len(all_kicad) < len(lcsc_pin_geometries):
            raise FabOutputError(
                f"{footprint.refdes}: geometry pad count mismatch: "
                f"KiCad={len(all_kicad)} LCSC={len(lcsc_pin_geometries)}"
            )
        kicad_center = (
            sum(x for x, _ in all_kicad) / len(all_kicad),
            sum(y for _, y in all_kicad) / len(all_kicad),
        )
        lcsc_values = [(x * scale, y * scale) for _, _, x, y, _, _ in lcsc_pin_geometries]
        lcsc_center = (
            sum(x for x, _ in lcsc_values) / len(lcsc_values),
            sum(y for _, y in lcsc_values) / len(lcsc_values),
        )
        candidates: list[tuple[float, float]] = []
        for angle in (0.0, 90.0, 180.0, 270.0):
            quarter_turn = int(angle) % 180 == 90
            actual = [
                (
                    rotate(x - kicad_center[0], y - kicad_center[1], angle),
                    (pad.size_y_mm, pad.size_x_mm)
                    if quarter_turn
                    else (pad.size_x_mm, pad.size_y_mm),
                )
                for pad, (x, y) in zip(footprint.pads, all_kicad, strict=True)
            ]
            expected = [
                (
                    (x * scale - lcsc_center[0], y * scale - lcsc_center[1]),
                    (width * scale, height * scale),
                )
                for _, _, x, y, width, height in lcsc_pin_geometries
            ]
            try:
                error = _minimum_matching_geometry_error(actual, expected, PAD_SIZE_TOLERANCE_MM)
            except FabOutputError:
                continue
            if error <= tolerance_mm:
                candidates.append((angle, error))
        if len(candidates) == 1:
            return candidates[0][0], (
                "unique; basis=declared-geometry-exception; "
                f"max_error_mm={candidates[0][1]:.6f}; "
                f"pad_size_tolerance_mm={PAD_SIZE_TOLERANCE_MM:.3f}"
            )
        if not candidates:
            raise FabOutputError(
                f"{footprint.refdes}: no geometry rotation candidate within tolerance"
            )
        raise FabOutputError(
            f"{footprint.refdes}: ambiguous geometry rotation candidates: {candidates}"
        )
    kicad: dict[str, list[tuple[float, float]]] = defaultdict(list)
    lcsc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if kicad_pin_functions:
        for pad in footprint.pads:
            if pad.number is not None and pad.number in kicad_pin_functions:
                function = _normalize_pin_function(kicad_pin_functions[pad.number], aliases)
                kicad[function].append(
                    _inverse_rotate(
                        pad.x_mm - footprint.x_mm,
                        pad.y_mm - footprint.y_mm,
                        footprint.rotation_deg,
                    )
                )
        raw_lcsc: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for number, function, x, y in lcsc_pin_centers:
            raw_lcsc[_normalize_pin_function(function, aliases)].append(
                (number, x * scale, y * scale)
            )
        for function, target in kicad.items():
            selected = [
                (point[0], point[1])
                for number, *point in raw_lcsc[function]
                if number in kicad_pin_functions
            ]
            if len(selected) < len(target):
                selected.extend(
                    (point[0], point[1])
                    for number, *point in raw_lcsc[function]
                    if number not in kicad_pin_functions
                )
            lcsc[function] = selected[: len(target)]
        if {key: len(value) for key, value in kicad.items()} != {
            key: len(value) for key, value in lcsc.items()
        }:
            raise FabOutputError(
                f"{footprint.refdes}: pin-function mismatch: "
                f"KiCad={sorted(kicad)} LCSC={sorted(lcsc)}"
            )
    else:
        kicad["__geometry__"] = all_kicad
        lcsc["__geometry__"] = [(x * scale, y * scale) for _, _, x, y in lcsc_pin_centers]
    kicad_values = [point for points in kicad.values() for point in points]
    kicad_center = (
        sum(x for x, _ in kicad_values) / len(kicad_values),
        sum(y for _, y in kicad_values) / len(kicad_values),
    )
    lcsc_values = [point for points in lcsc.values() for point in points]
    lcsc_center = (
        sum(x for x, _ in lcsc_values) / len(lcsc_values),
        sum(y for _, y in lcsc_values) / len(lcsc_values),
    )
    candidates: list[tuple[float, float]] = []
    for angle in (0.0, 90.0, 180.0, 270.0):
        error = 0.0
        for function, kicad_points in kicad.items():
            transformed = [
                rotate(x - kicad_center[0], y - kicad_center[1], angle) for x, y in kicad_points
            ]
            remaining = [(x - lcsc_center[0], y - lcsc_center[1]) for x, y in lcsc[function]]
            error = max(error, _minimum_matching_error(transformed, remaining))
        if error <= tolerance_mm:
            candidates.append((angle, error))
    if len(candidates) == 1:
        basis = "pin-function" if kicad_pin_functions else "geometry-only"
        return candidates[0][0], f"unique; basis={basis}; max_error_mm={candidates[0][1]:.6f}"
    if len(candidates) > 1 and not polarized:
        return 0.0, (
            "ambiguous but non-polarized and symmetric; "
            f"polarity unaffected; candidates={candidates}"
        )
    if not candidates:
        raise FabOutputError(f"{footprint.refdes}: no LCSC rotation candidate within tolerance")
    raise FabOutputError(f"{footprint.refdes}: ambiguous LCSC rotation candidates: {candidates}")


def verify_lcsc_rotation_evidence(
    evidence_dir: Path,
    fixture_dir: Path,
    board: BoardMeasurement,
    lane: ElectricalLane,
    fitted: set[str],
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    """Recompute archived LCSC rotation Evidence without network access."""
    footprints = {footprint.refdes: footprint for footprint in board.footprints}
    offsets: dict[str, float] = {}
    notes: dict[str, str] = {}
    unknowns: list[str] = []
    for component in lane.components:
        if component.refdes not in fitted:
            continue
        path = evidence_dir / f"{component.refdes}.json"
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        response = document["response"]
        canonical = json.dumps(
            response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if document.get("response_canonical_sha256") != expected_hash:
            raise FabOutputError(f"{component.refdes}: LCSC Evidence response hash mismatch")
        footprint = footprints.get(component.refdes)
        if footprint is None:
            raise FabOutputError(f"{component.refdes}: board footprint missing for LCSC Evidence")
        try:
            symbol_note = verify_cpl_pin_function_declaration(component, fixture_dir)
            geometry_exception = component.cpl_rotation_geometry_exception
            if geometry_exception and (
                not component.cpl_rotation_geometry_exception_reason
                or not component.cpl_rotation_geometry_exception_source
            ):
                raise FabOutputError(
                    f"{component.refdes}: geometry exception provenance is required"
                )
            offset, note = derive_lcsc_rotation_offset(
                footprint,
                load_lcsc_pin_centers(path),
                component.cpl_rotation_pin_functions,
                component.cpl_rotation_pin_aliases,
                polarized=component.cpl_rotation_polarized,
                lcsc_pin_geometries=(
                    load_lcsc_pin_geometries(path) if geometry_exception else None
                ),
                geometry_exception=geometry_exception,
            )
        except FabOutputError as exc:
            unknowns.append(component.refdes)
            notes[component.refdes] = f"unknown; {exc}"
            continue
        offsets[component.refdes] = offset
        notes[component.refdes] = f"{symbol_note}; {note}"
    return offsets, notes, unknowns


def verify_cpl_pin_function_declaration(
    component: ComponentView,
    fixture_dir: Path,
) -> str:
    """Verify graph CPL pin functions against the pinned KiCad symbol."""
    if not component.cpl_rotation_pin_functions:
        return "no pin-function declaration"
    symbol_path = Path(component.library.symbol_file)
    if not symbol_path.is_absolute():
        symbol_path = fixture_dir / symbol_path
    parsed = SymbolLibrary().load(
        component.library.symbol,
        symbol_path,
        component.library.symbol_sha256,
    )
    symbol_pins = {
        pin.number: _normalize_pin_function(pin.name, component.cpl_rotation_pin_aliases)
        for pin in parsed.pins
    }
    unverified = set(component.cpl_rotation_unverified_pads)
    for number, declared in component.cpl_rotation_pin_functions.items():
        if number not in symbol_pins:
            if (
                number not in unverified
                or not component.cpl_rotation_unverified_pad_reason
                or not component.cpl_rotation_unverified_pad_source
            ):
                raise FabOutputError(
                    f"{component.refdes}: CPL pin {number} is absent from symbol "
                    "without sourced unverified-pad declaration"
                )
            continue
        expected = _normalize_pin_function(declared, component.cpl_rotation_pin_aliases)
        if expected != symbol_pins[number]:
            raise FabOutputError(
                f"{component.refdes}: CPL pin function mismatch for {number}: "
                f"declared={declared!r} symbol={symbol_pins[number]!r}"
            )
    if unverified:
        return (
            f"symbol-verified; unverified_pads={sorted(unverified)}; "
            f"reason={component.cpl_rotation_unverified_pad_reason}"
        )
    return "symbol-verified; all declared CPL pins matched"
