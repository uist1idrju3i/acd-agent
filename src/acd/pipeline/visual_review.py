"""Deterministic visual-review manifest, observation recording, and verdict.

The vision inspection itself is performed by the agent through the SDK
``inspect_image_with_vision`` tool; this module only derives the PNGs that must
be inspected, records the agent's responses as L3 observations, and verifies
fail-closed that every manifest entry was observed. Nothing here grants pass
authority: the manifest, observations, and verdict all carry
``pass_evidence = False``.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import Field

from acd.adapters.raster import CairoSvgRasterizer
from acd.core.process import sha256_bytes
from acd.openhands.session.visual_projection import write_visual_vision_observation
from acd.pipeline.visual_projection import derive_png_visual_projections
from acd.schema.common import AcdModel, NonEmptyStr
from acd.schema.visual_projection import (
    VisualProjectionSet,
    VisualReviewManifest,
    VisualReviewRequirement,
    VisualVisionObservation,
)

VISUAL_REVIEW_MANIFEST_NAME = "visual-review-manifest.json"
OBSERVATION_DIR = "visual/vision-observations"
GENERATED_BY = "acd.pipeline.visual_review"


class VisualReviewError(ValueError):
    """Raised when the visual-review manifest cannot be derived or recorded."""


class VisualReviewItemVerdict(AcdModel):
    """Per-requirement verification result."""

    projection_id: NonEmptyStr
    status: Literal["ok", "missing", "mismatch"]


class VisualReviewVerdict(AcdModel):
    """Fail-closed verdict of the visual review; never raises on bad input."""

    artifact_kind: Literal["visual_review_verdict"] = "visual_review_verdict"
    pass_evidence: Literal[False] = False
    status: Literal["complete", "incomplete"]
    required: int = Field(ge=0)
    observed: int = Field(ge=0)
    items: list[VisualReviewItemVerdict] = Field(
        default_factory=list[VisualReviewItemVerdict]
    )
    problems: list[str] = Field(default_factory=list[str])


def collect_visual_projection_sets(out_root: Path) -> list[Path]:
    """Collect projection-set JSON files under ``out_root``, excluding rasters."""
    paths = sorted(
        path
        for path in out_root.rglob("visual-projections-*.json")
        if not path.name.endswith("-raster.json")
        and ".stage-cache" not in path.parts
    )
    if not paths:
        raise VisualReviewError(
            f"no visual projection sets found under {out_root}"
        )
    return paths


def _load_projection_set(path: Path) -> VisualProjectionSet:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualReviewError(
            f"visual projection set could not be read: {path}"
        ) from exc
    try:
        return VisualProjectionSet.model_validate(document)
    except ValueError as exc:
        raise VisualReviewError(
            f"visual projection set is invalid: {path}"
        ) from exc


def _load_manifest(out_root: Path) -> VisualReviewManifest:
    path = out_root / VISUAL_REVIEW_MANIFEST_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualReviewError(
            f"visual review manifest could not be read: {path}"
        ) from exc
    try:
        return VisualReviewManifest.model_validate(document)
    except ValueError as exc:
        raise VisualReviewError(
            f"visual review manifest is invalid: {path}"
        ) from exc


def derive_visual_review(
    out_root: Path,
    *,
    jobs: int = min(os.cpu_count() or 1, 4),
    rasterizer: CairoSvgRasterizer | None = None,
) -> VisualReviewManifest:
    """Derive PNG projections for every projection set and write the manifest."""
    if jobs < 1:
        raise VisualReviewError("jobs must be a positive integer")
    set_paths = collect_visual_projection_sets(out_root)
    projection_sets = [_load_projection_set(path) for path in set_paths]
    revisions = {item.source_revision for item in projection_sets}
    if len(revisions) != 1:
        raise VisualReviewError(
            "visual projection sets disagree on source_revision"
        )
    source_revision = revisions.pop()

    def _derive(
        path: Path, projection_set: VisualProjectionSet
    ) -> tuple[Path, VisualProjectionSet]:
        # image_path entries are relative to the set's own directory, so
        # rasters land in <set_dir>/visual/png and the raster set JSON next
        # to the source set.
        raster_set_path = path.with_name(f"{path.stem}-raster{path.suffix}")
        derived = derive_png_visual_projections(
            projection_set,
            out_dir=path.parent,
            rasterizer=rasterizer,
            raster_set_path=raster_set_path,
        )
        return path, derived

    if jobs == 1 or len(set_paths) == 1:
        derived_sets = [
            _derive(path, projection_set)
            for path, projection_set in zip(
                set_paths, projection_sets, strict=True
            )
        ]
    else:
        with ThreadPoolExecutor(
            max_workers=min(jobs, len(set_paths))
        ) as executor:
            futures = [
                executor.submit(_derive, path, projection_set)
                for path, projection_set in zip(
                    set_paths, projection_sets, strict=True
                )
            ]
            # Reduce in the sorted set order so the manifest does not depend
            # on the worker count.
            derived_sets = [future.result() for future in futures]

    requirements: list[VisualReviewRequirement] = []
    resolved_root = out_root.resolve()
    for source_set, (set_path, derived_set) in zip(
        projection_sets, derived_sets, strict=True
    ):
        png_records = {
            record.projection_id: record
            for record in derived_set.projections
            if record.media_type == "image/png"
        }
        for record in source_set.projections:
            if record.media_type != "image/svg+xml":
                raise VisualReviewError(
                    f"projection {record.projection_id} is not an SVG source"
                )
            png_record = png_records.get(f"{record.projection_id}-png")
            if png_record is None:
                raise VisualReviewError(
                    f"projection {record.projection_id} has no PNG derivation"
                )
            # The manifest stores png_path relative to out_root because
            # record_observation and verify_visual_review resolve it there.
            png_absolute = (set_path.parent / png_record.image_path).resolve()
            try:
                png_relative = png_absolute.relative_to(resolved_root)
            except ValueError as exc:
                raise VisualReviewError(
                    f"derived PNG escaped the out root: {png_absolute}"
                ) from exc
            requirements.append(
                VisualReviewRequirement(
                    projection_id=png_record.projection_id,
                    source_projection_id=record.projection_id,
                    domain=record.domain,
                    projection_type=png_record.projection_type,
                    png_path=png_relative.as_posix(),
                    image_hash=png_record.image_hash,
                )
            )
    requirements.sort(key=lambda item: item.projection_id)
    renderer_versions = sorted(
        {
            record.renderer.tool_version
            for _path, derived_set in derived_sets
            for record in derived_set.projections
            if record.media_type == "image/png"
        }
    )
    if not renderer_versions:
        raise VisualReviewError("no PNG projections were derived")
    manifest = VisualReviewManifest(
        source_revision=source_revision,
        generated_by=GENERATED_BY,
        renderer_version="+".join(renderer_versions),
        required=requirements,
    )
    manifest_path = out_root / VISUAL_REVIEW_MANIFEST_NAME
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def record_observation(
    out_root: Path,
    *,
    projection_id: str,
    image_hash: str,
    profile_name: str,
    model: str,
    response: str,
) -> Path:
    """Record one vision response as an L3 observation bound to the manifest."""
    manifest = _load_manifest(out_root)
    requirement = next(
        (item for item in manifest.required if item.projection_id == projection_id),
        None,
    )
    if requirement is None:
        raise VisualReviewError(
            f"projection {projection_id} is not in the visual review manifest"
        )
    if requirement.image_hash != image_hash:
        raise VisualReviewError(
            f"image hash for {projection_id} does not match the manifest"
        )
    png_path = out_root / requirement.png_path
    try:
        on_disk = sha256_bytes(png_path.read_bytes())
    except OSError as exc:
        raise VisualReviewError(
            f"reviewed PNG is unavailable: {png_path}"
        ) from exc
    if on_disk != image_hash:
        raise VisualReviewError(
            f"PNG on disk for {projection_id} does not match the manifest hash"
        )
    if not response.strip():
        raise VisualReviewError("empty vision responses are not acceptable")
    path = out_root / OBSERVATION_DIR / f"{projection_id}.json"
    write_visual_vision_observation(
        profile_name=profile_name,
        model=model,
        projection_id=projection_id,
        image_hash=image_hash,
        response=response,
        path=path,
    )
    return path


def _observation_for(path: Path) -> VisualVisionObservation | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return VisualVisionObservation.model_validate(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def verify_visual_review(out_root: Path) -> VisualReviewVerdict:
    """Verify that every manifest requirement has a matching observation.

    This function never raises on bad input: any missing, unreadable, or
    mismatched record is reported as a problem and the status stays
    ``incomplete``.
    """
    problems: list[str] = []
    items: list[VisualReviewItemVerdict] = []
    observed = 0
    try:
        manifest = _load_manifest(out_root)
    except VisualReviewError as exc:
        return VisualReviewVerdict(
            status="incomplete",
            required=0,
            observed=0,
            items=[],
            problems=[str(exc)],
        )
    expected_ids = {item.projection_id for item in manifest.required}
    for requirement in manifest.required:
        status: Literal["ok", "missing", "mismatch"] = "ok"
        observation_path = (
            out_root
            / OBSERVATION_DIR
            / f"{requirement.projection_id}.json"
        )
        if not observation_path.is_file():
            status = "missing"
            problems.append(
                f"{requirement.projection_id}: observation is missing"
            )
        else:
            observation = _observation_for(observation_path)
            if observation is None:
                status = "mismatch"
                problems.append(
                    f"{requirement.projection_id}: observation is unreadable"
                )
            elif (
                observation.projection_id != requirement.projection_id
                or observation.image_hash != requirement.image_hash
            ):
                status = "mismatch"
                problems.append(
                    f"{requirement.projection_id}: observation does not match "
                    "the manifest"
                )
        png_path = out_root / requirement.png_path
        try:
            on_disk = sha256_bytes(png_path.read_bytes())
        except OSError:
            status = "mismatch"
            problems.append(
                f"{requirement.projection_id}: PNG is unavailable"
            )
        else:
            if on_disk != requirement.image_hash:
                status = "mismatch"
                problems.append(
                    f"{requirement.projection_id}: PNG hash does not match "
                    "the manifest"
                )
        if status == "ok":
            observed += 1
        items.append(
            VisualReviewItemVerdict(
                projection_id=requirement.projection_id,
                status=status,
            )
        )
    observation_dir = out_root / OBSERVATION_DIR
    if observation_dir.is_dir():
        for path in sorted(observation_dir.glob("*.json"), key=str):
            if path.stem not in expected_ids:
                problems.append(
                    f"{path.stem}: observation has no manifest requirement"
                )
                items.append(
                    VisualReviewItemVerdict(
                        projection_id=path.stem,
                        status="mismatch",
                    )
                )
    return VisualReviewVerdict(
        status="complete" if not problems else "incomplete",
        required=len(manifest.required),
        observed=observed,
        items=items,
        problems=problems,
    )


__all__ = [
    "GENERATED_BY",
    "OBSERVATION_DIR",
    "VISUAL_REVIEW_MANIFEST_NAME",
    "VisualReviewError",
    "VisualReviewItemVerdict",
    "VisualReviewVerdict",
    "collect_visual_projection_sets",
    "derive_visual_review",
    "record_observation",
    "verify_visual_review",
]
