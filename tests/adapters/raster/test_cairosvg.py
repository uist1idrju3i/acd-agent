# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.adapters.raster import CairoSvgRasterizer
from acd.adapters.raster.cairosvg import RasterizerError
from acd.core.process import sha256_bytes
from acd.core.visual_projection import (
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    normalized_svg_sha256,
)
from acd.pipeline.visual_projection import derive_png_visual_projections
from acd.schema import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)


def _svg() -> bytes:
    return (
        b'<svg width="10mm" height="5mm" viewBox="0 0 100 50">'
        b"<title>SVG Image created as board.svg date "
        b"2026-08-19T00:00:00Z </title><rect width=\"100\" height=\"50\"/>"
        b"</svg>"
    )


def _source_record() -> VisualProjectionRecord:
    svg = _svg()
    return VisualProjectionRecord(
        projection_id="board-f-cu",
        projection_type="layered_layout_view",
        domain="electrical",
        source_revision="r8",
        input_files=[
            VisualProjectionInput(path="board.kicad_pcb", content_hash="sha256:" + "1" * 64)
        ],
        renderer=VisualRendererProvenance(tool_version="10.0.5"),
        resolution=VisualResolution(
            width="10mm", height="5mm", view_box=(0.0, 0.0, 100.0, 50.0)
        ),
        normalization_rule_id=SVG_TITLE_NORMALIZATION_RULE_ID,
        normalization_rule_description=SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
        image_hash=normalized_svg_sha256(svg),
        generated_at=datetime(2026, 8, 19, tzinfo=UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash=normalized_svg_sha256(svg),
            second_image_hash=normalized_svg_sha256(svg),
        ),
        image_path="visual/board-f-cu.svg",
    )


def test_rasterizer_records_png_resolution_and_reproduction(tmp_path: Path) -> None:
    source = tmp_path / "visual/board-f-cu.svg"
    source.parent.mkdir()
    source.write_bytes(_svg())

    record = CairoSvgRasterizer(output_width=320).rasterize(
        source_record=_source_record(),
        output_path=tmp_path / "visual/png/board-f-cu.png",
        base_dir=tmp_path,
    )

    assert record.media_type == "image/png"
    assert record.renderer.renderer_type == "cairosvg"
    assert record.renderer.output_width == 320
    assert record.resolution.width == "320px"
    assert record.resolution.height.endswith("px")
    assert record.image_hash == sha256_bytes((tmp_path / record.image_path).read_bytes())
    assert record.regeneration_check.status == "reproduced"


def test_rasterizer_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "visual/board-f-cu.svg"
    source.parent.mkdir()
    source.write_bytes(_svg().replace(b'width="100"', b'width="99"'))

    with pytest.raises(RasterizerError, match="hash"):
        CairoSvgRasterizer().rasterize(
            source_record=_source_record(),
            output_path=tmp_path / "visual/png/board-f-cu.png",
            base_dir=tmp_path,
        )


def test_derive_png_projection_writes_augmented_projection_set(tmp_path: Path) -> None:
    source = tmp_path / "visual/board-f-cu.svg"
    source.parent.mkdir()
    source.write_bytes(_svg())

    result = derive_png_visual_projections(
        VisualProjectionSet(
            source_revision="r8",
            projections=[_source_record()],
        ).with_computed_hashes(),
        out_dir=tmp_path,
        rasterizer=CairoSvgRasterizer(output_width=320),
    )

    assert [record.projection_id for record in result.projections] == [
        "board-f-cu",
        "board-f-cu-png",
    ]
    assert (tmp_path / "visual-projections-electrical.json").is_file()
    assert (tmp_path / "visual/png/board-f-cu.png").is_file()


def test_rasterizer_rejects_unknown_cairosvg_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "visual/board-f-cu.svg"
    source.parent.mkdir()
    source.write_bytes(_svg())
    monkeypatch.setitem(sys.modules, "cairosvg", type("CairoSvg", (), {"__version__": "unknown"})())

    with pytest.raises(RasterizerError, match="version is unknown"):
        CairoSvgRasterizer().rasterize(
            source_record=_source_record(),
            output_path=tmp_path / "visual/png/board-f-cu.png",
            base_dir=tmp_path,
        )


def test_rasterizer_rejects_cairosvg_import_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "visual/board-f-cu.svg"
    source.parent.mkdir()
    source.write_bytes(_svg())
    monkeypatch.setitem(sys.modules, "cairosvg", None)

    with pytest.raises(RasterizerError, match="unavailable"):
        CairoSvgRasterizer().rasterize(
            source_record=_source_record(),
            output_path=tmp_path / "visual/png/board-f-cu.png",
            base_dir=tmp_path,
        )
