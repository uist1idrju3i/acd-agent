"""Tests for shared deterministic SVG projection helpers."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import pytest

from acd.adapters.svg.common import (
    BOARD_FONT_SIZE_RATIO,
    DIAGRAM_FONT_SIZE_RATIO,
    SvgVisualProjectionError,
    assert_text_font_size,
    view_box_font_size,
)


def test_font_size_is_view_box_relative() -> None:
    assert view_box_font_size(20.0, ratio=BOARD_FONT_SIZE_RATIO) == pytest.approx(1.0)
    assert view_box_font_size(240.0, ratio=DIAGRAM_FONT_SIZE_RATIO) == pytest.approx(3.0)


@pytest.mark.parametrize("extent", [0.0, -1.0, float("nan"), float("inf")])
def test_undeclared_font_size_reference_fails_closed(extent: float) -> None:
    with pytest.raises(SvgVisualProjectionError, match="reference extent"):
        view_box_font_size(extent, ratio=BOARD_FONT_SIZE_RATIO)


@pytest.mark.parametrize("ratio", [0.0, -0.1, float("nan")])
def test_invalid_font_size_ratio_fails_closed(ratio: float) -> None:
    with pytest.raises(SvgVisualProjectionError, match="ratio is invalid"):
        view_box_font_size(20.0, ratio=ratio)


def test_text_without_font_size_fails_closed() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="2">R1</text></svg>'
    with pytest.raises(SvgVisualProjectionError, match="font-size"):
        assert_text_font_size(svg)


def test_text_with_font_size_is_accepted() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<text x="1" y="2" font-size="1">R1</text></svg>'
    )
    assert_text_font_size(svg)


def test_non_utf8_svg_fails_closed() -> None:
    with pytest.raises(SvgVisualProjectionError, match="UTF-8"):
        assert_text_font_size(b"\xff\xfe<svg/>")
