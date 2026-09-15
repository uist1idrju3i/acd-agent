from __future__ import annotations

from pathlib import Path

from acd.core.visual_projection import normalized_svg_sha256
from acd.core.visual_quality import analyze_svg_readability
from acd.schema.visual_quality import ReadabilityPolicy


def _svg(body: str, *, viewbox: str = "0 0 30 25") -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">'
        f"{body}</svg>"
    ).encode()


def test_missing_font_size_is_a_stop_finding() -> None:
    report = analyze_svg_readability(
        _svg('<text id="label" x="1" y="5">sensor</text>'),
        policy=ReadabilityPolicy(),
    )
    assert report.status == "fail"
    assert "font_size_missing" in {finding.code for finding in report.findings}


def test_oversized_default_font_on_sensor_node_viewbox_fails() -> None:
    report = analyze_svg_readability(
        _svg('<text id="label" x="1" y="20" font-size="16">sensor</text>'),
        policy=ReadabilityPolicy(),
    )
    assert report.status == "fail"
    assert "text_oversized" in {finding.code for finding in report.findings}


def test_too_small_text_uses_policy_resolution() -> None:
    report = analyze_svg_readability(
        _svg('<text id="label" x="1" y="5" font-size="1">x</text>'),
        policy=ReadabilityPolicy(default_px_per_unit=4.0, min_text_px=6.0),
    )
    assert report.status == "fail"
    assert "text_too_small" in {finding.code for finding in report.findings}


def test_overlap_and_out_of_viewbox_are_stop_findings() -> None:
    report = analyze_svg_readability(
        _svg(
            '<text id="a" x="1" y="10" font-size="4">overlap</text>'
            '<text id="b" x="1" y="10" font-size="4">overlap</text>'
            '<text id="outside" x="29" y="2" font-size="4">x</text>'
        ),
        policy=ReadabilityPolicy(min_text_px=1),
    )
    codes = {finding.code for finding in report.findings}
    assert report.status == "fail"
    assert "text_overlap" in codes
    assert "text_out_of_viewbox" in codes


def test_low_contrast_and_unknown_color_are_fail_closed() -> None:
    low_contrast = analyze_svg_readability(
        _svg(
            '<rect x="0" y="0" width="30" height="25" fill="#888"/>'
            '<text x="1" y="5" font-size="2" fill="#777">label</text>'
        ),
        policy=ReadabilityPolicy(min_text_px=1),
    )
    assert low_contrast.status == "fail"
    assert "low_contrast" in {finding.code for finding in low_contrast.findings}

    unknown_color = analyze_svg_readability(
        _svg('<text x="1" y="5" font-size="2" fill="not-a-color">label</text>'),
        policy=ReadabilityPolicy(min_text_px=1),
    )
    assert unknown_color.status == "unknown"
    assert "unknown_color" in {finding.code for finding in unknown_color.findings}


def test_missing_viewbox_and_non_translate_transform_are_unknown() -> None:
    no_viewbox = analyze_svg_readability(
        b'<svg xmlns="http://www.w3.org/2000/svg"><text font-size="2">x</text></svg>',
        policy=ReadabilityPolicy(),
    )
    assert no_viewbox.status == "unknown"

    unresolved = analyze_svg_readability(
        _svg('<text transform="rotate(10)" x="1" y="5" font-size="2">x</text>'),
        policy=ReadabilityPolicy(min_text_px=1),
    )
    assert unresolved.status == "unknown"
    assert "unresolved_transform" in {
        finding.code for finding in unresolved.findings
    }


def test_inherited_font_size_and_translate_are_deterministic() -> None:
    svg = _svg(
        '<g font-size="2" transform="translate(1,2)">'
        '<text id="label" x="1" y="5">label</text></g>'
    )
    first = analyze_svg_readability(svg, policy=ReadabilityPolicy(min_text_px=1))
    second = analyze_svg_readability(svg, policy=ReadabilityPolicy(min_text_px=1))
    assert first == second
    assert first.status == "pass"


def test_scale_and_diagonal_matrix_transforms_are_supported() -> None:
    for transform in (
        "translate(2,3) scale(2,2)",
        "matrix(2,0,0,2,2,3)",
    ):
        svg = _svg(
            f'<g transform="{transform}">'
            '<text id="label" x="1" y="5" font-size="1.5">label</text></g>'
        )
        report = analyze_svg_readability(svg, policy=ReadabilityPolicy(min_text_px=1))
        assert report.status == "pass"


def test_historical_sensor_node_records_expose_missing_font_size() -> None:
    root = Path(__file__).parents[2]
    paths = (
        "examples/sensor-node-20260820/board/visual/gd1-placement.svg",
        "examples/sensor-node-20260820/board/visual/gd1-power-tree.svg",
        "examples/sensor-node-20260820/board/visual/gd1-system-block.svg",
        "examples/sensor-node-20260820/board/visual/gd1-firmware-state.svg",
        "examples/sensor-node-20260820/board/visual/gd1-firmware-sequence.svg",
        "examples/sensor-node-20260820/board/visual/reproduction/"
        "gd1-placement.reproduced.svg",
        "examples/sensor-node-20260820/board/visual/reproduction/"
        "gd1-power-tree.reproduced.svg",
        "examples/sensor-node-20260820/board/visual/reproduction/"
        "gd1-system-block.reproduced.svg",
        "examples/sensor-node-20260820/board/visual/reproduction/"
        "gd1-firmware-state.reproduced.svg",
        "examples/sensor-node-20260820/board/visual/reproduction/"
        "gd1-firmware-sequence.reproduced.svg",
    )
    for relative_path in paths:
        report = analyze_svg_readability(
            (root / relative_path).read_bytes(),
            policy=ReadabilityPolicy(),
        )
        assert "font_size_missing" in {finding.code for finding in report.findings}


def test_readability_analysis_preserves_normalized_projection_hash() -> None:
    svg = _svg(
        '<title>SVG Image created as normalized.svg date 2026-01-01T00:00:00Z '
        '</title>'
        '<text id="label" x="1" y="5" font-size="2">label</text>'
    )
    before = normalized_svg_sha256(svg)
    analyze_svg_readability(svg, policy=ReadabilityPolicy(min_text_px=1))
    assert normalized_svg_sha256(svg) == before
