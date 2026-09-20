"""Projection figure and theme-song artifact loading for generated documents."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from acd.schema.design_graph import DesignGraph
from acd.schema.theme_song import ThemeSongProjection
from acd.schema.visual_projection import VisualProjectionRecord, VisualProjectionSet
from product_doc_inputs.common import (
    DocumentGenerationError,
    DocumentInput,
    sha256_file,
)


@dataclass(frozen=True)
class ProjectionFigure:
    projection_id: str
    projection_type: str
    domain: str
    image_path: Path
    image_hash: str
    renderer_type: str
    renderer_tool_version: str
    media_type: str


def load_projection_figures(
    set_paths: Sequence[Path], target_revision: str
) -> tuple[tuple[ProjectionFigure, ...], tuple[DocumentInput, ...]]:
    """Load visual projection sets and resolve every referenced image file."""
    if not set_paths:
        raise DocumentGenerationError("no visual projection set was declared (fail-closed)")
    figures: list[ProjectionFigure] = []
    inputs: list[DocumentInput] = []
    for set_path in set_paths:
        content_hash = sha256_file(set_path)
        try:
            projection_set = VisualProjectionSet.model_validate(
                json.loads(set_path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise DocumentGenerationError(
                f"visual projection set {set_path} is not valid: {exc}"
            ) from exc
        if projection_set.source_revision != target_revision:
            raise DocumentGenerationError(
                f"visual projection set {set_path} targets revision "
                f"{projection_set.source_revision!r}, not {target_revision!r}"
            )
        inputs.append(DocumentInput(path=set_path, content_hash=content_hash))
        for projection in projection_set.projections:
            figures.append(_figure(projection, set_path.parent))
    if not figures:
        raise DocumentGenerationError("visual projection sets contain no projection")
    return tuple(sorted(figures, key=lambda item: item.projection_id)), tuple(inputs)


def _figure(projection: VisualProjectionRecord, base_dir: Path) -> ProjectionFigure:
    image_path = base_dir / projection.image_path
    if not image_path.is_file():
        raise DocumentGenerationError(
            f"projection {projection.projection_id!r} image {image_path} is missing"
        )
    if projection.regeneration_check.status != "reproduced":
        raise DocumentGenerationError(
            f"projection {projection.projection_id!r} was not reproduced "
            f"(status={projection.regeneration_check.status!r})"
        )
    return ProjectionFigure(
        projection_id=projection.projection_id,
        projection_type=projection.projection_type,
        domain=projection.domain,
        image_path=image_path,
        image_hash=projection.image_hash,
        renderer_type=projection.renderer.renderer_type,
        renderer_tool_version=projection.renderer.tool_version,
        media_type=projection.media_type,
    )


@dataclass(frozen=True)
class ThemeSongFigure:
    title: str
    key: str
    bpm: int
    bars: int
    composer_id: str
    source: str
    midi_path: Path
    midi_hash: str
    mml_path: Path | None
    mml_hash: str | None
    mml_reason: str | None
    regeneration_status: str
    pass_evidence: bool


def load_theme_song(path: Path, graph: DesignGraph) -> tuple[ThemeSongFigure, DocumentInput]:
    """Load a recorded theme-song projection and its MIDI artifact, fail-closed."""
    content_hash = sha256_file(path)
    try:
        projection = ThemeSongProjection.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise DocumentGenerationError(f"theme-song projection {path} is not valid: {exc}") from exc
    if projection.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"theme-song projection {path} targets graph "
            f"{projection.graph_id!r}, not {graph.graph_id!r}"
        )
    if projection.source_revision != graph.revision:
        raise DocumentGenerationError(
            f"theme-song projection {path} targets revision "
            f"{projection.source_revision!r}, not {graph.revision!r}"
        )
    if projection.regeneration_check.status != "reproduced":
        raise DocumentGenerationError(
            f"theme-song projection {path} was not reproduced "
            f"(status={projection.regeneration_check.status!r})"
        )
    midi_artifacts = [
        artifact for artifact in projection.artifacts if artifact.media_type == "audio/midi"
    ]
    mml_artifacts = [
        artifact for artifact in projection.artifacts if artifact.media_type == "text/x-mml"
    ]
    if len(midi_artifacts) != 1 or len(mml_artifacts) > 1:
        raise DocumentGenerationError(
            "theme-song projection must declare one MIDI and at most one MML"
        )
    artifact = midi_artifacts[0]
    midi_path = (path.parent / artifact.path).resolve()
    if not midi_path.is_file():
        raise DocumentGenerationError(f"theme-song artifact {midi_path} is missing")
    midi_hash = sha256_file(midi_path)
    if midi_hash != artifact.content_hash:
        raise DocumentGenerationError(
            f"theme-song artifact {midi_path} hash mismatch "
            f"(declared={artifact.content_hash!r}, actual={midi_hash!r})"
        )
    mml_path: Path | None = None
    mml_hash: str | None = None
    if mml_artifacts:
        mml_artifact = mml_artifacts[0]
        mml_path = (path.parent / mml_artifact.path).resolve()
        if not mml_path.is_file():
            raise DocumentGenerationError(f"theme-song artifact {mml_path} is missing")
        mml_hash = sha256_file(mml_path)
        if mml_hash != mml_artifact.content_hash:
            raise DocumentGenerationError(
                f"theme-song artifact {mml_path} hash mismatch "
                f"(declared={mml_artifact.content_hash!r}, actual={mml_hash!r})"
            )
    figure = ThemeSongFigure(
        title=projection.title,
        key=projection.key,
        bpm=projection.bpm,
        bars=projection.bars,
        composer_id=projection.composer_id,
        source=projection.source,
        midi_path=midi_path,
        midi_hash=artifact.content_hash,
        mml_path=mml_path,
        mml_hash=mml_hash,
        mml_reason=projection.mml_check.reason,
        regeneration_status=projection.regeneration_check.status,
        pass_evidence=projection.pass_evidence,
    )
    return figure, DocumentInput(path=path, content_hash=content_hash)
