"""Shared KiCad sexpr query helpers."""

from __future__ import annotations

# ruff: noqa
# pyright: reportUnusedImport=false

from typing import cast

from .common import FabOutputError

def _direct(node: object, tag: str) -> list[list[object]]:
    return [_items(child) for child in _items(node)[1:] if _tag(child) == tag]


def _at(node: object) -> tuple[float, float, float]:
    values = _one(node, "at")
    if values is None or len(values) < 3:
        raise FabOutputError("missing KiCad position")
    return _number(values[1]), _number(values[2]), _number(values[3]) if len(values) > 3 else 0.0


def _property(node: object, name: str) -> str | None:
    for prop in _direct(node, "property"):
        if len(prop) >= 3 and str(prop[1]) == name:
            return str(prop[2])
    for text in _direct(node, "fp_text"):
        if len(text) >= 3 and str(text[1]) == name.lower():
            return str(text[2])
    return None


def _tag(node: object) -> str | None:
    items = _items(node)
    return str(items[0]) if items and not isinstance(items[0], list) else None


def _items(node: object) -> list[object]:
    return cast("list[object]", node) if isinstance(node, list) else []


def _number(value: object) -> float:
    try:
        return float(cast(str, value))
    except (TypeError, ValueError) as exc:
        raise FabOutputError(f"expected numeric s-expression atom, got {value!r}") from exc


def _one(node: object, tag: str) -> list[object] | None:
    matches = _direct(node, tag)
    return matches[0] if matches else None


__all__ = ["_at", "_direct", "_items", "_number", "_one", "_property", "_tag"]
