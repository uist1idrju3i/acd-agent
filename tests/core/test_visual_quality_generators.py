"""Readability regression coverage for current SVG projection generators."""

# pyright: reportMissingTypeStubs=false, reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

from acd.adapters.svg import generate_harness_visual_projection
from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.electrical.visual_quality import analyze_svg_readability
from acd.schema.visual_quality import ReadabilityPolicy
from tests.adapters.svg.test_firmware_svg import _generate as generate_firmware
from tests.adapters.svg.test_graph_diff_svg import _render as generate_graph_diff
from tests.adapters.svg.test_harness_projection import _inputs as harness_inputs
from tests.adapters.svg.test_layout import _generate as generate_layout
from tests.adapters.svg.test_system import _generate as generate_system
from tests.pipeline.test_visual_crosscheck import _mechanical_fixture


def _assert_generated_svg_passes(root: Path, relative_path: str) -> None:
    report = analyze_svg_readability(
        (root / relative_path).read_bytes(),
        policy=ReadabilityPolicy(),
    )
    assert report.status == "pass", (relative_path, report.findings)


def test_current_generators_produce_readable_svg(tmp_path: Path) -> None:
    layout = generate_layout(tmp_path / "layout")
    for record in layout.projections:
        _assert_generated_svg_passes(tmp_path / "layout" / "out", record.image_path)

    system = generate_system(tmp_path / "system")
    for record in system.projections:
        _assert_generated_svg_passes(tmp_path / "system" / "out", record.image_path)

    firmware = generate_firmware(tmp_path / "firmware")
    for record in firmware.projections:
        _assert_generated_svg_passes(tmp_path / "firmware", record.image_path)

    graph_diff = generate_graph_diff(tmp_path, "graph-diff")
    for record in graph_diff.projections:
        _assert_generated_svg_passes(
            tmp_path / "graph-diff",
            record.image_path,
        )

    graph, contract = harness_inputs()
    generate_harness_visual_projection(
        out_dir=tmp_path / "harness",
        source_revision=graph.revision,
        graph=graph,
        lane=extract_electrical_lane(graph),
        contract=contract,
        authoritative_inputs=(
            Path("fixtures/harness/gd1-external-sensor/graph.json"),
            Path("fixtures/harness/gd1-external-sensor/harness.json"),
        ),
        input_base_dir=Path("."),
    )
    _assert_generated_svg_passes(tmp_path / "harness", "harness.svg")

    mechanical = _mechanical_fixture(tmp_path / "mechanical")
    for record in mechanical[-1].projections:
        _assert_generated_svg_passes(tmp_path / "mechanical", record.image_path)
