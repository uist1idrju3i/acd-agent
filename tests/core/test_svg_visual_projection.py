"""Tests for strict SVG normalization and resolution measurement."""

from __future__ import annotations

import pytest

from acd.core.visual_projection import (
    SvgNormalizationError,
    SvgResolutionError,
    measure_svg_resolution,
    normalize_svg,
    normalized_svg_sha256,
)


def _svg(title: str = "SVG Image created as first.svg date 2026-08-19T03:45:00Z ") -> bytes:
    return (
        f'<svg width="29.9974mm" height="24.9936mm" '
        f'viewBox="0.0000 0.0000 29.9974 24.9936"><title>{title}</title><path/></svg>'
    ).encode()


def test_normalization_replaces_only_the_kicad_title() -> None:
    first = normalize_svg(_svg())
    second = normalize_svg(
        _svg("SVG Image created as second.svg date 2026-08-19T03:46:01 ")
    )
    assert first == second
    assert normalized_svg_sha256(first) == normalized_svg_sha256(second)


@pytest.mark.parametrize(
    "title",
    [
        "not KiCad",
        "SVG Image created as file.svg date 2026-08-19T03:45:00.123Z ",
        "SVG Image created as file.svg date unknown ",
    ],
)
def test_normalization_rejects_unexpected_title(title: str) -> None:
    with pytest.raises(SvgNormalizationError):
        normalize_svg(_svg(title))


def test_normalization_rejects_multiple_titles_and_missing_title() -> None:
    with pytest.raises(SvgNormalizationError):
        normalize_svg(_svg() + b"<title>another</title>")
    with pytest.raises(SvgNormalizationError):
        normalize_svg(
            _svg()
            .replace(b"<title>", b"<not-title>")
            .replace(b"</title>", b"</not-title>")
        )


def test_resolution_is_measured_from_svg_root() -> None:
    resolution = measure_svg_resolution(_svg())
    assert resolution.width == "29.9974mm"
    assert resolution.height == "24.9936mm"
    assert resolution.view_box == (0.0, 0.0, 29.9974, 24.9936)


@pytest.mark.parametrize(
    "svg",
    [
        _svg().replace(b'viewBox="0.0000 0.0000 29.9974 24.9936"', b'viewBox="1 2 3"'),
        _svg().replace(b'width="29.9974mm"', b'width="29.9974"'),
        _svg().replace(b'width="29.9974mm"', b'width="29.9974px"'),
        _svg().replace(b'height="24.9936mm"', b'height="unknown"'),
    ],
)
def test_resolution_rejects_unmeasurable_values(svg: bytes) -> None:
    with pytest.raises(SvgResolutionError):
        measure_svg_resolution(svg)
