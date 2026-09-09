# pyright: reportMissingTypeStubs=false
"""Tests for the mandatory visual-review manifest, recording, and verdict."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from acd.adapters.raster import CairoSvgRasterizer
from acd.core.visual_projection import (
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    normalized_svg_sha256,
)
from acd.pipeline.visual_projection import derive_png_visual_projections
from acd.pipeline.visual_review import (
    OBSERVATION_DIR,
    VISUAL_REVIEW_MANIFEST_NAME,
    VisualReviewError,
    collect_visual_projection_sets,
    derive_visual_review,
    record_observation,
    verify_visual_review,
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


def _record(
    projection_id: str,
    image_path: str,
    *,
    media_type: Literal["image/svg+xml", "image/png"] = "image/svg+xml",
    source_revision: str = "r8",
) -> VisualProjectionRecord:
    return VisualProjectionRecord(
        projection_id=projection_id,
        projection_type="layered_layout_view",
        domain="electrical",
        source_revision=source_revision,
        input_files=[
            VisualProjectionInput(path="board.kicad_pcb", content_hash="sha256:" + "1" * 64)
        ],
        renderer=VisualRendererProvenance(tool_version="10.0.5"),
        resolution=VisualResolution(
            width="10mm", height="5mm", view_box=(0.0, 0.0, 100.0, 50.0)
        ),
        normalization_rule_id=SVG_TITLE_NORMALIZATION_RULE_ID,
        normalization_rule_description=SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
        media_type=media_type,
        image_hash=(
            normalized_svg_sha256(_SVG)
            if media_type == "image/svg+xml"
            else "sha256:" + "2" * 64
        ),
        generated_at=datetime(2026, 8, 19, tzinfo=UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash=normalized_svg_sha256(_SVG),
            second_image_hash=normalized_svg_sha256(_SVG),
        ),
        image_path=image_path,
    )


def _write_set(
    out_root: Path,
    set_dir: Path,
    set_name: str,
    projections: list[VisualProjectionRecord],
    *,
    source_revision: str = "r8",
    materialize_sources: bool = True,
) -> Path:
    """Materialize the referenced SVG files and write the projection set JSON.

    ``image_path`` values are relative to the set's own directory — the
    directory passed to the rasterizer as its base — while the set JSON
    lives under ``set_dir`` too. ``out_root`` only anchors the overall
    output tree.
    """
    for record in projections:
        if record.media_type == "image/svg+xml" and materialize_sources:
            svg_path = set_dir / record.image_path
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_path.write_bytes(_SVG)
    projection_set = VisualProjectionSet(
        source_revision=source_revision, projections=projections
    ).with_computed_hashes()
    set_dir.mkdir(parents=True, exist_ok=True)
    set_path = set_dir / set_name
    set_path.write_text(
        projection_set.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return set_path


def _out_root(tmp_path: Path, *, sets: int = 1) -> Path:
    out_root = tmp_path / "out"
    out_root.mkdir(parents=True)
    _write_set(
        out_root,
        out_root,
        "visual-projections-electrical.json",
        [
            _record("board-a", "visual/board-a.svg"),
            _record("board-b", "visual/board-b.svg"),
        ],
    )
    if sets > 1:
        _write_set(
            out_root,
            out_root / "firmware",
            "visual-projections-firmware.json",
            [_record("fw-state", "visual/fw-state.svg")],
        )
    return out_root


def _manifest_ids(out_root: Path) -> list[str]:
    document = json.loads(
        (out_root / VISUAL_REVIEW_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    return [item["projection_id"] for item in document["required"]]


def _record_all(out_root: Path) -> None:
    manifest = json.loads(
        (out_root / VISUAL_REVIEW_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    for item in manifest["required"]:
        record_observation(
            out_root,
            projection_id=item["projection_id"],
            image_hash=item["image_hash"],
            profile_name="vision",
            model="model-x",
            response="readable projection",
        )


def test_derive_visual_review_writes_manifest_and_pngs(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path, sets=2)

    manifest = derive_visual_review(out_root, jobs=1)

    assert manifest.artifact_kind == "visual_review_manifest"
    assert manifest.pass_evidence is False
    assert manifest.generated_by == "acd.pipeline.visual_review"
    assert manifest.source_revision == "r8"
    assert _manifest_ids(out_root) == [
        "board-a-png",
        "board-b-png",
        "fw-state-png",
    ]
    for item in manifest.required:
        assert (out_root / item.png_path).is_file()
    # The per-set raster documents sit next to their sources and are excluded
    # from later collections.
    assert (out_root / "visual-projections-electrical-raster.json").is_file()
    raster_doc = json.loads(
        (out_root / "visual-projections-electrical-raster.json").read_text(
            encoding="utf-8"
        )
    )
    assert [r["projection_id"] for r in raster_doc["projections"]] == [
        "board-a",
        "board-a-png",
        "board-b",
        "board-b-png",
    ]


def test_collect_excludes_raster_sets_and_stage_cache(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    raster = out_root / "visual-projections-electrical-raster.json"
    raster.write_text("{}\n", encoding="utf-8")
    cache = out_root / ".stage-cache"
    cache.mkdir()
    (cache / "visual-projections-ignored.json").write_text("{}\n", encoding="utf-8")

    assert collect_visual_projection_sets(out_root) == [
        out_root / "visual-projections-electrical.json"
    ]


def test_collect_without_sets_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(VisualReviewError, match="no visual projection sets"):
        collect_visual_projection_sets(tmp_path)


def test_derive_is_identical_for_jobs_1_and_3(tmp_path: Path) -> None:
    out_seq = _out_root(tmp_path / "seq", sets=2)
    out_par = _out_root(tmp_path / "par", sets=2)
    derive_visual_review(out_seq, jobs=1)
    derive_visual_review(out_par, jobs=3)

    seq_manifest = (out_seq / VISUAL_REVIEW_MANIFEST_NAME).read_bytes()
    par_manifest = (out_par / VISUAL_REVIEW_MANIFEST_NAME).read_bytes()
    assert seq_manifest == par_manifest
    manifest = json.loads(seq_manifest)
    for item in manifest["required"]:
        assert (out_seq / item["png_path"]).read_bytes() == (
            out_par / item["png_path"]
        ).read_bytes()


def test_derive_rejects_non_svg_sources(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    out_root.mkdir()
    _write_set(
        out_root,
        out_root,
        "visual-projections-electrical.json",
        [
            _record("board-a", "visual/board-a.svg"),
            _record("board-c", "visual/board-c.png", media_type="image/png"),
        ],
    )
    with pytest.raises((VisualReviewError, ValueError), match="SVG"):
        derive_visual_review(out_root, jobs=1)


def test_derive_rejects_mismatched_revisions(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path, sets=2)
    _write_set(
        out_root,
        out_root / "mechanical",
        "visual-projections-mechanical.json",
        [
            _record(
                "mech-a",
                "visual/mech-a.svg",
                source_revision="r9",
            )
        ],
        source_revision="r9",
    )

    with pytest.raises(VisualReviewError, match="source_revision"):
        derive_visual_review(out_root, jobs=1)


def test_record_observation_writes_l3_observation(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    manifest = derive_visual_review(out_root, jobs=1)
    requirement = manifest.required[0]

    path = record_observation(
        out_root,
        projection_id=requirement.projection_id,
        image_hash=requirement.image_hash,
        profile_name="vision",
        model="model-x",
        response="  readable projection  ",
    )

    assert path == out_root / OBSERVATION_DIR / f"{requirement.projection_id}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["artifact_kind"] == "visual_vision_observation"
    assert document["pass_evidence"] is False
    assert document["projection_id"] == requirement.projection_id
    assert document["response"] == "  readable projection  "


def test_record_observation_refuses_unknown_projection(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    derive_visual_review(out_root, jobs=1)

    with pytest.raises(VisualReviewError, match="not in the visual review manifest"):
        record_observation(
            out_root,
            projection_id="unknown-png",
            image_hash="sha256:" + "3" * 64,
            profile_name="vision",
            model="model-x",
            response="response",
        )


def test_record_observation_refuses_manifest_hash_mismatch(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    manifest = derive_visual_review(out_root, jobs=1)
    requirement = manifest.required[0]

    with pytest.raises(VisualReviewError, match="does not match the manifest"):
        record_observation(
            out_root,
            projection_id=requirement.projection_id,
            image_hash="sha256:" + "4" * 64,
            profile_name="vision",
            model="model-x",
            response="response",
        )


def test_record_observation_refuses_png_hash_mismatch(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    manifest = derive_visual_review(out_root, jobs=1)
    requirement = manifest.required[0]
    png_path = out_root / requirement.png_path
    png_path.write_bytes(png_path.read_bytes() + b"x")

    with pytest.raises(VisualReviewError, match="PNG on disk"):
        record_observation(
            out_root,
            projection_id=requirement.projection_id,
            image_hash=requirement.image_hash,
            profile_name="vision",
            model="model-x",
            response="response",
        )


def test_record_observation_refuses_empty_response(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    manifest = derive_visual_review(out_root, jobs=1)
    requirement = manifest.required[0]

    with pytest.raises(VisualReviewError, match="empty"):
        record_observation(
            out_root,
            projection_id=requirement.projection_id,
            image_hash=requirement.image_hash,
            profile_name="vision",
            model="model-x",
            response="   \n",
        )


def test_derive_resolves_image_paths_relative_to_the_set_directory(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "out"
    out_root.mkdir()
    _write_set(
        out_root,
        out_root / "dual-beacon-tag",
        "visual-projections-electrical.json",
        [_record("board-a", "visual/a.svg")],
    )
    _write_set(
        out_root,
        out_root / "dual-beacon-tag-enclosure",
        "visual-projections-mechanical.json",
        [_record("mech-a", "visual/m.svg")],
    )

    manifest = derive_visual_review(out_root, jobs=3)

    assert _manifest_ids(out_root) == ["board-a-png", "mech-a-png"]
    for item in manifest.required:
        assert item.png_path.startswith(
            ("dual-beacon-tag/visual/png/", "dual-beacon-tag-enclosure/visual/png/")
        )
        assert (out_root / item.png_path).is_file()
    # Raster set JSONs are written next to their source sets.
    assert (
        out_root / "dual-beacon-tag" / "visual-projections-electrical-raster.json"
    ).is_file()
    assert (
        out_root
        / "dual-beacon-tag-enclosure"
        / "visual-projections-mechanical-raster.json"
    ).is_file()

    _record_all(out_root)
    verdict = verify_visual_review(out_root)
    assert verdict.status == "complete"
    assert verdict.observed == verdict.required == 2


def test_derive_rejects_source_paths_escaping_the_set_directory(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "out"
    out_root.mkdir()
    set_dir = out_root / "nested"
    set_dir.mkdir(parents=True)
    # Craft the record JSON by hand because ``..`` image paths are rejected
    # by record validation before the rasterizer can see them.
    payload = _record("board-a", "visual/board-a.svg").model_dump(mode="json")
    payload["image_path"] = "../../../escape.svg"
    doc = {
        "artifact_kind": "visual_projection_set",
        "source_revision": "r8",
        "projections": [payload],
    }
    (set_dir / "visual-projections-electrical.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(VisualReviewError, match="visual projection set is invalid"):
        derive_visual_review(out_root, jobs=1)


def test_verify_complete_after_recording_all(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path, sets=2)
    derive_visual_review(out_root, jobs=1)
    _record_all(out_root)

    verdict = verify_visual_review(out_root)

    assert verdict.status == "complete"
    assert verdict.observed == verdict.required == 3
    assert verdict.problems == []
    assert all(item.status == "ok" for item in verdict.items)


def test_verify_incomplete_without_observation(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    derive_visual_review(out_root, jobs=1)

    verdict = verify_visual_review(out_root)

    assert verdict.status == "incomplete"
    assert verdict.observed == 0
    assert {item.status for item in verdict.items} == {"missing"}


def test_verify_incomplete_without_manifest(tmp_path: Path) -> None:
    verdict = verify_visual_review(tmp_path)

    assert verdict.status == "incomplete"
    assert verdict.required == 0
    assert verdict.problems


def test_verify_incomplete_on_png_mutation(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    manifest = derive_visual_review(out_root, jobs=1)
    _record_all(out_root)
    requirement = manifest.required[0]
    png_path = out_root / requirement.png_path
    png_path.write_bytes(png_path.read_bytes() + b"x")

    verdict = verify_visual_review(out_root)

    assert verdict.status == "incomplete"
    assert any("PNG hash" in problem for problem in verdict.problems)


def test_verify_incomplete_on_stray_observation(tmp_path: Path) -> None:
    out_root = _out_root(tmp_path)
    derive_visual_review(out_root, jobs=1)
    _record_all(out_root)
    stray = out_root / OBSERVATION_DIR / "not-in-manifest.json"
    stray.write_text("{}\n", encoding="utf-8")

    verdict = verify_visual_review(out_root)

    assert verdict.status == "incomplete"
    assert any("not-in-manifest" in problem for problem in verdict.problems)


def test_existing_derive_default_output_unchanged(tmp_path: Path) -> None:
    """`derive_png_visual_projections` keeps its default raster-set name."""
    out_root = _out_root(tmp_path)
    projection_set = VisualProjectionSet.model_validate(
        json.loads(
            (out_root / "visual-projections-electrical.json").read_text(
                encoding="utf-8"
            )
        )
    )
    derive_png_visual_projections(
        projection_set,
        out_dir=out_root,
        rasterizer=CairoSvgRasterizer(),
    )
    assert (out_root / "visual-projections-electrical-raster.json").is_file()
