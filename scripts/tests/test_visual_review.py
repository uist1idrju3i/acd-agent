"""Smoke tests for the visual-review command-line contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import (
    derive_visual_review_pngs,
    record_visual_vision_observation,
    verify_visual_review,
)
from scripts.tests.cli_runner import run_main

from acd.core.visual_projection import (
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    normalized_svg_sha256,
)
from acd.schema import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

_SVG = (
    b'<svg width="10mm" height="5mm" viewBox="0 0 100 50">'
    b"<title>SVG Image created as board.svg date "
    b"2026-08-19T00:00:00Z </title><rect width=\"100\" height=\"50\"/>"
    b"</svg>"
)


def _out_root(tmp_path: Path) -> Path:
    out_root = tmp_path / "out"
    svg_path = out_root / "visual" / "board-a.svg"
    svg_path.parent.mkdir(parents=True)
    svg_path.write_bytes(_SVG)
    record = VisualProjectionRecord(
        projection_id="board-a",
        projection_type="layered_layout_view",
        domain="electrical",
        source_revision="r8",
        input_files=[
            VisualProjectionInput(
                path="board.kicad_pcb", content_hash="sha256:" + "1" * 64
            )
        ],
        renderer=VisualRendererProvenance(tool_version="10.0.5"),
        resolution=VisualResolution(
            width="10mm", height="5mm", view_box=(0.0, 0.0, 100.0, 50.0)
        ),
        normalization_rule_id=SVG_TITLE_NORMALIZATION_RULE_ID,
        normalization_rule_description=SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
        image_hash=normalized_svg_sha256(_SVG),
        generated_at=datetime(2026, 8, 19, tzinfo=UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash=normalized_svg_sha256(_SVG),
            second_image_hash=normalized_svg_sha256(_SVG),
        ),
        image_path="visual/board-a.svg",
    )
    projection_set = VisualProjectionSet(
        source_revision="r8", projections=[record]
    ).with_computed_hashes()
    (out_root / "visual-projections-electrical.json").write_text(
        projection_set.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return out_root


def test_derive_cli_writes_manifest(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out_root = _out_root(tmp_path)
    result = run_main(
        capsys,
        derive_visual_review_pngs.main,
        "--out-root",
        str(out_root),
        "--jobs",
        "1",
    )
    assert result.returncode == 0
    assert "required: 1" in result.stdout
    assert (out_root / "visual-review-manifest.json").is_file()


def test_derive_cli_fails_closed_without_sets(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    result = run_main(
        capsys,
        derive_visual_review_pngs.main,
        "--out-root",
        str(tmp_path),
    )
    assert result.returncode == 1
    assert "FAIL:" in result.stderr


def test_verify_cli_exits_one_until_all_observed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out_root = _out_root(tmp_path)
    run_main(capsys, derive_visual_review_pngs.main, "--out-root", str(out_root))

    verdict = run_main(
        capsys, verify_visual_review.main, "--out-root", str(out_root)
    )
    assert verdict.returncode == 1
    assert "incomplete" in verdict.stdout
    assert "MISSING" in verdict.stdout

    manifest = json.loads(
        (out_root / "visual-review-manifest.json").read_text(encoding="utf-8")
    )
    item = manifest["required"][0]
    response = tmp_path / "response.txt"
    response.write_text("readable projection\n", encoding="utf-8")
    recorded = run_main(
        capsys,
        record_visual_vision_observation.main,
        "--out-root",
        str(out_root),
        "--projection-id",
        item["projection_id"],
        "--image-hash",
        item["image_hash"],
        "--profile-name",
        "vision",
        "--model",
        "model-x",
        "--response-file",
        str(response),
    )
    assert recorded.returncode == 0, recorded.stderr

    verdict = run_main(
        capsys, verify_visual_review.main, "--out-root", str(out_root)
    )
    assert verdict.returncode == 0
    assert "board-a-png: OK" in verdict.stdout
    assert "visual review: complete (1/1 observed)" in verdict.stdout


def test_record_cli_rejects_unknown_projection(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out_root = _out_root(tmp_path)
    run_main(capsys, derive_visual_review_pngs.main, "--out-root", str(out_root))
    response = tmp_path / "response.txt"
    response.write_text("response\n", encoding="utf-8")
    result = run_main(
        capsys,
        record_visual_vision_observation.main,
        "--out-root",
        str(out_root),
        "--projection-id",
        "unknown-png",
        "--image-hash",
        "sha256:" + "3" * 64,
        "--profile-name",
        "vision",
        "--model",
        "model-x",
        "--response-file",
        str(response),
    )
    assert result.returncode == 1
    assert "FAIL:" in result.stderr


def test_report_progress_includes_visual_review_line(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from scripts import report_progress

    out_root = _out_root(tmp_path)
    result = run_main(capsys, report_progress.main, "--out", str(out_root))
    assert "visual review: 0/0 observed, status=no-manifest" in result.stdout

    run_main(capsys, derive_visual_review_pngs.main, "--out-root", str(out_root))
    result = run_main(capsys, report_progress.main, "--out", str(out_root))
    assert (
        "visual review: 0/1 observed, status=incomplete" in result.stdout
    )
