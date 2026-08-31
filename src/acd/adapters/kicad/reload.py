"""Independent reload of generated outputs (fail-closed verification).

Deliberately uses parsers that share no code with the generators: ``sexpdata``
for KiCad boards/schematics and ``gerbonara`` for Gerber/Excellon files. A
normalized hash strips only generator comments/timestamps so identical designs
hash identically across reruns.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import sexpdata  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.excellon import ExcellonFile  # pyright: ignore[reportMissingTypeStubs]
from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]


class ReloadError(ValueError):
    """Raised when an output cannot be independently re-read (fail-closed)."""


def _symbol_name(node: object) -> str | None:
    if isinstance(node, list) and node and isinstance(node[0], sexpdata.Symbol):
        return str(cast(object, node[0]))
    return None


def _children(node: object) -> list[object]:
    if isinstance(node, list):
        return cast("list[object]", node)
    return []


def _load_sexpr(path: Path) -> list[object]:
    try:
        parsed = cast(
            object,
            sexpdata.loads(path.read_text(encoding="utf-8")),  # pyright: ignore[reportUnknownMemberType]
        )
    except Exception as exc:  # sexpdata raises assorted exception types
        raise ReloadError(f"{path.name}: unparsable s-expression: {exc}") from exc
    if not isinstance(parsed, list):
        raise ReloadError(f"{path.name}: root is not a list (fail-closed)")
    return cast("list[object]", parsed)


def verify_board(path: Path, expected_nets: set[str], expected_refdes: set[str]) -> None:
    """Re-read a routed board with sexpdata and check structural expectations."""
    root = _load_sexpr(path)
    if _symbol_name(root) != "kicad_pcb":
        raise ReloadError(f"{path.name}: not a kicad_pcb document")
    nets: set[str] = set()
    refdes: set[str] = set()
    segments = 0
    def collect_pad_nets(node: object) -> None:
        name = _symbol_name(node)
        items = _children(node)
        if name == "net" and len(items) >= 2:
            nets.add(str(items[2] if len(items) >= 3 else items[1]))
        for child in items[1:]:
            if isinstance(child, list):
                collect_pad_nets(cast(object, child))

    for node in root[1:]:
        name = _symbol_name(node)
        items = _children(node)
        if name == "net" and len(items) >= 3:
            nets.add(str(items[2]))
        elif name == "segment":
            segments += 1
        elif name == "footprint":
            collect_pad_nets(node)
            for child in items[1:]:
                fields = _children(child)
                if (
                    _symbol_name(child) == "property"
                    and len(fields) >= 3
                    and str(fields[1]) == "Reference"
                ) or (
                    # Legacy footprints carry (fp_text reference "REF" ...).
                    _symbol_name(child) == "fp_text"
                    and len(fields) >= 3
                    and str(fields[1]) == "reference"
                ):
                    refdes.add(str(fields[2]))
    missing_nets = expected_nets - nets
    if missing_nets:
        raise ReloadError(f"{path.name}: nets missing after reload: {sorted(missing_nets)}")
    missing_refs = expected_refdes - refdes
    if missing_refs:
        raise ReloadError(f"{path.name}: components missing: {sorted(missing_refs)}")
    if segments == 0:
        raise ReloadError(f"{path.name}: no routed segments (fail-closed)")


def verify_schematic(path: Path, expected_refdes: set[str]) -> None:
    root = _load_sexpr(path)
    if _symbol_name(root) != "kicad_sch":
        raise ReloadError(f"{path.name}: not a kicad_sch document")
    refdes: set[str] = set()
    for node in root[1:]:
        if _symbol_name(node) != "symbol":
            continue
        for child in _children(node)[1:]:
            fields = _children(child)
            if (
                _symbol_name(child) == "property"
                and len(fields) >= 3
                and str(fields[1]) == "Reference"
            ):
                refdes.add(str(fields[2]))
    missing = expected_refdes - refdes
    if missing:
        raise ReloadError(f"{path.name}: symbols missing: {sorted(missing)}")


def verify_gerber(path: Path, min_objects: int = 1) -> None:
    try:
        layer = GerberFile.open(path)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:
        raise ReloadError(f"{path.name}: gerbonara cannot parse: {exc}") from exc
    objects = cast("list[object]", layer.objects)  # pyright: ignore[reportUnknownMemberType]
    if len(objects) < min_objects:
        raise ReloadError(f"{path.name}: only {len(objects)} objects, expected >= {min_objects}")


def verify_drill(path: Path, min_holes: int = 1) -> None:
    try:
        drill = ExcellonFile.open(path)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:
        raise ReloadError(f"{path.name}: gerbonara cannot parse: {exc}") from exc
    holes = cast("list[object]", drill.objects)  # pyright: ignore[reportUnknownMemberType]
    if len(holes) < min_holes:
        raise ReloadError(f"{path.name}: only {len(holes)} holes, expected >= {min_holes}")


def normalized_hash(path: Path) -> str:
    """Hash file content with generator comment/timestamp lines removed.

    Gerber ``G04`` comments and Excellon ``;`` comments carry creation
    timestamps; everything else must be byte-identical across reruns.
    """
    digest = hashlib.sha256()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("G04") or stripped.startswith(";"):
            continue
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()
