"""Board projection regression tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence

from acd.adapters.kicad.board import _silk_text
from acd.core.sexpr import SExpr
from acd.core.silkscreen import SilkTextView


def _text(layer: str) -> SilkTextView:
    return SilkTextView(
        "silk.text",
        "label",
        "DEV BOARD",
        5.0,
        6.0,
        layer,
        1.0,
        0.15,
        0.0,
        "test",
        "test",
        "SW1",
        0.25,
        1.0,
    )


def _effects(node: Sequence[SExpr]) -> list[SExpr]:
    for child in node:
        if isinstance(child, list) and child and child[0] == "effects":
            return child
    raise AssertionError("effects node missing")


def test_back_silkscreen_text_is_mirrored() -> None:
    effects = _effects(_silk_text(_text("B.SilkS")))
    assert ["justify", "mirror"] in effects


def test_front_silkscreen_text_is_not_mirrored() -> None:
    effects = _effects(_silk_text(_text("F.SilkS")))
    assert ["justify", "mirror"] not in effects
