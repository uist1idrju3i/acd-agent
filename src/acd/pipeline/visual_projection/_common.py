"""Shared SVG parsing and crosscheck item helpers for visual projection lanes."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from acd.core.process import sha256_bytes
from acd.schema.visual_crosscheck import (
    CrosscheckStatus,
    VisualCrosscheckItem,
)
from acd.schema.visual_projection import (
    VisualProjectionInput,
)


def node_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not fragment:
        raise ValueError("visual projection identifier declaration is invalid")
    return fragment


def crosscheck_item(
    *,
    check_id: str,
    description: str,
    expected: str,
    actual: str,
    machine_field: str,
    status: CrosscheckStatus,
) -> VisualCrosscheckItem:
    return VisualCrosscheckItem(
        check_id=check_id,
        description=description,
        expected=expected,
        actual=actual,
        machine_field=machine_field,
        status=status,
    )


def status_for_items(items: list[VisualCrosscheckItem]) -> CrosscheckStatus:
    if not items:
        raise ValueError("visual crosscheck cannot aggregate an empty item list")
    statuses = {item.status for item in items}
    if "mismatch" in statuses:
        return "mismatch"
    if "unknown" in statuses:
        return "unknown"
    return "match"


def svg_root_geometry(svg: bytes) -> tuple[str, str, tuple[str, str, str, str]]:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    attributes = root.attrib
    width = attributes.get("width")
    height = attributes.get("height")
    view_box = attributes.get("viewBox")
    if width is None or height is None or view_box is None:
        raise ValueError("visual crosscheck SVG root geometry is incomplete")
    values = tuple(view_box.split())
    if len(values) != 4:
        raise ValueError("visual crosscheck SVG viewBox is malformed")
    return width, height, values


def decimal_value(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"visual crosscheck {field_name} is not numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"visual crosscheck {field_name} is not finite")
    return parsed


def svg_dimension(value: str, field_name: str) -> tuple[str, str]:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)", value)
    if match is None:
        raise ValueError(f"visual crosscheck SVG {field_name} is malformed")
    return match.group(1), match.group(2)


def svg_text(svg: bytes) -> str:
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("visual crosscheck SVG could not be parsed") from exc
    return "\n".join(text.strip() for text in root.itertext() if text.strip())


def machine_input(
    path: Path,
    *,
    base_dir: Path,
) -> VisualProjectionInput:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("visual crosscheck machine input is outside the workspace") from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise ValueError("visual crosscheck machine input is missing or unreadable") from exc
    return VisualProjectionInput(path=relative, content_hash=sha256_bytes(content))
