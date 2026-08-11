"""Deterministic project-local footprint overlays."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from acd_adapter_kicad.library import LibraryPinError, verify_pinned_file
from acd_core.sexpr import SExpr, dumps, find_all


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _number(value: SExpr) -> float:
    try:
        return float(str(value))
    except ValueError as exc:
        raise LibraryPinError(f"overlay requires numeric pad geometry, got {value!r}") from exc


def apply_overlay(
    raw: list[SExpr],
    source_path: Path,
    overlay_path: Path,
    expected_overlay_hash: str,
) -> tuple[list[SExpr], dict[str, str]]:
    if _hash_bytes(overlay_path.read_bytes()) != expected_overlay_hash:
        raise LibraryPinError(f"overlay hash mismatch: {overlay_path}")
    data = cast(dict[str, object], json.loads(overlay_path.read_text(encoding="utf-8")))
    if data.get("source_footprint_file") != str(source_path):
        raise LibraryPinError("overlay source footprint path mismatch")
    source_hash = data.get("source_footprint_sha256")
    if not isinstance(source_hash, str):
        raise LibraryPinError("overlay source footprint hash is missing")
    verify_pinned_file(source_path, source_hash)
    target = cast(dict[str, object], data.get("target", {}))
    if not target.get("footprint"):
        raise LibraryPinError("overlay target footprint is missing")
    evidence = cast(dict[str, object], data.get("evidence", {}))
    if (
        not isinstance(data.get("overlay_id"), str)
        or not isinstance(data.get("reason"), str)
        or evidence.get("rule_id") != "pth-annular-ring-prefer-025"
        or not all(
            isinstance(evidence.get(key), str) for key in ("fab_profile", "url", "fetched_at")
        )
    ):
        raise LibraryPinError("overlay evidence is incomplete")
    result = cast(list[SExpr], json.loads(json.dumps(raw)))
    pads = find_all(result, "pad")
    changed = 0
    operations = cast(list[dict[str, object]], data.get("ops", []))
    for operation in operations:
        if operation.get("op") != "grow_pad_annular_ring":
            raise LibraryPinError("unsupported library overlay operation")
        number = str(operation.get("pad_number"))
        matches = [pad for pad in pads if str(pad[1]) == number]
        if not matches:
            raise LibraryPinError(f"overlay pad target not found: {number}")
        ring = float(cast(float | str, operation["target_annular_ring_mm"]))
        for pad in matches:
            if str(pad[2]) != "thru_hole":
                raise LibraryPinError(f"overlay pad is not thru_hole: {number}")
            drill = next(
                (item for item in pad[4:] if isinstance(item, list) and item[0] == "drill"), None
            )
            size = next(
                (item for item in pad[4:] if isinstance(item, list) and item[0] == "size"), None
            )
            if drill is None or size is None:
                raise LibraryPinError(f"overlay pad lacks drill or size: {number}")
            drill_values = drill[2:] if len(drill) > 1 and str(drill[1]) == "oval" else drill[1:2]
            if len(drill_values) not in (1, 2):
                raise LibraryPinError(f"invalid drill geometry for overlay pad: {number}")
            axes = [_number(value) for value in drill_values]
            if len(axes) == 1:
                axes *= 2
            size[1] = f"{axes[0] + 2 * ring:g}"
            size[2] = f"{axes[1] + 2 * ring:g}"
            changed += 1
    if changed == 0:
        raise LibraryPinError("overlay did not modify any pads")
    before_hash = _hash_bytes(dumps(raw).encode())
    after_hash = _hash_bytes(dumps(result).encode())
    return result, {
        "source_hash": source_hash,
        "before_hash": before_hash,
        "after_hash": after_hash,
    }
