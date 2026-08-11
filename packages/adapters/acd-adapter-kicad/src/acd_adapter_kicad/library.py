"""Pinned KiCad library resolution.

Resolves symbols and footprints referenced by ``electrical.component`` nodes,
verifies the pinned file hash (fail-closed on mismatch, ADR-0004), parses pin
and pad geometry, and flattens derived (``extends``) symbols so they can be
embedded into generated schematics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from acd_core.board_model import FootprintShape, PadShape
from acd_core.sexpr import SExpr, SExprError, find_all, find_one, parse_one


class LibraryPinError(ValueError):
    """Raised when a pinned library reference cannot be resolved (fail-closed)."""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pinned_file(path: Path, expected_sha256: str) -> None:
    if not path.is_file():
        raise LibraryPinError(f"pinned library file missing: {path}")
    actual = _sha256(path)
    if actual != expected_sha256:
        raise LibraryPinError(
            f"pinned library hash mismatch for {path}: expected {expected_sha256}, got {actual}"
        )


@dataclass(frozen=True)
class SymbolPin:
    number: str
    name: str
    electrical_type: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    length_mm: float


@dataclass(frozen=True)
class ParsedSymbol:
    lib_id: str  # e.g. "Device:R"
    pins: tuple[SymbolPin, ...]
    embedded: list[SExpr]  # flattened lib_symbols entry


def _as_float(value: SExpr) -> float:
    if not isinstance(value, str):
        raise SExprError(f"expected atom, got list: {value!r}")
    return float(value)


def _as_str(value: SExpr) -> str:
    if not isinstance(value, str):
        raise SExprError(f"expected atom, got list: {value!r}")
    return value


def _symbol_block(lib_root: SExpr, name: str) -> list[SExpr]:
    for block in find_all(lib_root, "symbol"):
        if len(block) >= 2 and block[1] == name:
            return block
    raise LibraryPinError(f"symbol {name!r} not found in library")


def _extract_pins(block: list[SExpr]) -> list[SymbolPin]:
    pins: list[SymbolPin] = []
    for sub in find_all(block, "symbol"):
        for pin in find_all(sub, "pin"):
            at = find_one(pin, "at")
            name_node = find_one(pin, "name")
            number_node = find_one(pin, "number")
            length_node = find_one(pin, "length")
            if at is None or name_node is None or number_node is None or length_node is None:
                raise LibraryPinError("pin missing at/name/number/length")
            rotation = _as_float(at[3]) if len(at) > 3 else 0.0
            pins.append(
                SymbolPin(
                    number=_as_str(number_node[1]),
                    name=_as_str(name_node[1]),
                    electrical_type=_as_str(pin[1]),
                    x_mm=_as_float(at[1]),
                    y_mm=_as_float(at[2]),
                    rotation_deg=rotation,
                    length_mm=_as_float(length_node[1]),
                )
            )
    return pins


def _rename_subsymbols(block: list[SExpr], old: str, new: str) -> list[SExpr]:
    renamed: list[SExpr] = []
    for item in block:
        if (
            isinstance(item, list)
            and item
            and item[0] == "symbol"
            and len(item) >= 2
            and isinstance(item[1], str)
        ):
            sub = list(item)
            sub[1] = str(item[1]).replace(old, new, 1)
            renamed.append(sub)
        else:
            renamed.append(item)
    return renamed


_BODY_TAGS = ("pin_numbers", "pin_names", "symbol")


def _flatten(lib_root: SExpr, name: str) -> list[SExpr]:
    block = _symbol_block(lib_root, name)
    extends = find_one(block, "extends")
    if extends is None:
        return list(block)
    base_name = _as_str(extends[1])
    base = _flatten(lib_root, base_name)
    merged: list[SExpr] = ["symbol", name]
    for item in block:
        if isinstance(item, list) and item and item[0] == "extends":
            continue
        if isinstance(item, list):
            merged.append(item)
    present = {
        item[0] for item in merged if isinstance(item, list) and item and isinstance(item[0], str)
    }
    for item in base[2:]:
        if not isinstance(item, list) or not item:
            continue
        tag = item[0]
        if tag == "property":
            prop_names = {
                _as_str(p[1])
                for p in find_all(merged, "property")
                if len(p) >= 2 and isinstance(p[1], str)
            }
            if len(item) >= 2 and isinstance(item[1], str) and item[1] in prop_names:
                continue
            merged.append(item)
        elif tag in _BODY_TAGS or tag not in present:
            merged.append(item)
    return _rename_subsymbols(merged, base_name, name)


class SymbolLibrary:
    """Loads and caches pinned symbol library files."""

    def __init__(self) -> None:
        self._roots: dict[Path, SExpr] = {}

    def _root(self, path: Path) -> SExpr:
        if path not in self._roots:
            self._roots[path] = parse_one(path.read_text())
        return self._roots[path]

    def load(self, lib_id: str, path: Path, expected_sha256: str) -> ParsedSymbol:
        verify_pinned_file(path, expected_sha256)
        root = self._root(path)
        symbol_name = lib_id.split(":", 1)[1]
        flattened = _flatten(root, symbol_name)
        pins = _extract_pins(flattened)
        if not pins and symbol_name != "MountingHole":
            raise LibraryPinError(f"symbol {lib_id!r} has no pins")
        embedded = list(flattened)
        embedded[1] = lib_id
        return ParsedSymbol(lib_id=lib_id, pins=tuple(pins), embedded=embedded)


def _custom_pad_size(pad: list[SExpr], size_x: float, size_y: float) -> tuple[float, float]:
    """Bounding size of a custom pad: anchor size expanded by its primitives."""
    half_x = size_x / 2.0
    half_y = size_y / 2.0
    primitives = find_one(pad, "primitives")
    if primitives is None:
        raise LibraryPinError("custom pad without primitives (fail-closed)")
    for tag in ("gr_line", "gr_rect", "gr_circle", "gr_arc", "gr_poly"):
        for item in find_all(primitives, tag):
            for x, y in _graphic_points(item):
                half_x = max(half_x, abs(x))
                half_y = max(half_y, abs(y))
    return half_x * 2.0, half_y * 2.0


def _pad_layers(pad: list[SExpr]) -> tuple[bool, bool]:
    layers = find_one(pad, "layers")
    if layers is None:
        return True, False
    names = [_as_str(item) for item in layers[1:]]
    on_front = any(name in ("F.Cu", "*.Cu") for name in names)
    on_back = any(name in ("B.Cu", "*.Cu") for name in names)
    return on_front, on_back


_COURTYARD_LAYERS = frozenset({"F.CrtYd", "B.CrtYd"})


def _graphic_points(item: list[SExpr]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for tag in ("start", "mid", "end", "center"):
        node = find_one(item, tag)
        if node is not None:
            points.append((_as_float(node[1]), _as_float(node[2])))
    pts = find_one(item, "pts")
    if pts is not None:
        for xy in pts[1:]:
            if isinstance(xy, list) and xy and xy[0] == "xy":
                points.append((_as_float(xy[1]), _as_float(xy[2])))
    return points


def _courtyard_bbox(root: list[SExpr]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for tag in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for item in find_all(root, tag):
            layer = find_one(item, "layer")
            if layer is None or _as_str(layer[1]) not in _COURTYARD_LAYERS:
                continue
            if tag == "fp_circle":
                center = find_one(item, "center")
                end = find_one(item, "end")
                if center is None or end is None:
                    continue
                cx, cy = _as_float(center[1]), _as_float(center[2])
                ex, ey = _as_float(end[1]), _as_float(end[2])
                radius = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
                points = [(cx - radius, cy - radius), (cx + radius, cy + radius)]
            else:
                points = _graphic_points(item)
            for x, y in points:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


class FootprintLibrary:
    """Loads and caches pinned footprint files."""

    def __init__(self) -> None:
        self._cache: dict[Path, list[SExpr]] = {}

    def raw(self, path: Path) -> list[SExpr]:
        if path not in self._cache:
            node = parse_one(path.read_text())
            if not isinstance(node, list):
                raise LibraryPinError(f"invalid footprint file: {path}")
            self._cache[path] = node
        return self._cache[path]

    def load(self, library_ref: str, path: Path, expected_sha256: str) -> FootprintShape:
        verify_pinned_file(path, expected_sha256)
        return self.shape_from_raw(library_ref, self.raw(path))

    def shape_from_raw(self, library_ref: str, root: list[SExpr]) -> FootprintShape:
        pads: list[PadShape] = []
        for pad in find_all(root, "pad"):
            number = _as_str(pad[1])
            pad_type = _as_str(pad[2])
            shape = _as_str(pad[3])
            at = find_one(pad, "at")
            size = find_one(pad, "size")
            if at is None or size is None:
                raise LibraryPinError("pad missing at/size")
            drill_node = find_one(pad, "drill")
            drill: float | None = None
            if drill_node is not None:
                is_oval = len(drill_node) > 2 and drill_node[1] == "oval"
                drill = _as_float(drill_node[2] if is_oval else drill_node[1])
            on_front, on_back = _pad_layers(pad)
            size_x = _as_float(size[1])
            size_y = _as_float(size[2])
            if shape == "custom":
                size_x, size_y = _custom_pad_size(pad, size_x, size_y)
            pads.append(
                PadShape(
                    number=number,
                    x_mm=_as_float(at[1]),
                    y_mm=_as_float(at[2]),
                    rotation_deg=_as_float(at[3]) if len(at) > 3 else 0.0,
                    shape=shape,
                    size_x_mm=size_x,
                    size_y_mm=size_y,
                    through_hole=pad_type in ("thru_hole", "np_thru_hole"),
                    drill_mm=drill,
                    on_front=on_front,
                    on_back=on_back,
                )
            )
        return FootprintShape(
            library_ref=library_ref,
            pads=tuple(pads),
            courtyard_bbox_mm=_courtyard_bbox(root),
        )
