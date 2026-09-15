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
from typing import Literal, cast

from pydantic import Field

from acd.adapters.raster import CairoSvgRasterizer
from acd.core.fileio import read_json
from acd.core.process import sha256_bytes
from acd.core.vision_tool_events import response_sha256
from acd.core.visual_quality import analyze_svg_readability
from acd.openhands.session.visual_projection import write_visual_vision_observation
from acd.pipeline.visual_projection import derive_png_visual_projections
from acd.schema.common import AcdModel, NonEmptyStr
from acd.schema.visual_projection import (
    VisualProjectionSet,
    VisualReviewManifest,
    VisualReviewRequirement,
    VisualVisionObservation,
    VisualVisionToolEvent,
)
from acd.schema.visual_quality import (
    ReadabilityFinding,
    ReadabilityPolicy,
    ReadabilityReport,
    VisualReadabilityDocument,
    VisualReadabilityObservation,
)

VISUAL_REVIEW_MANIFEST_NAME = "visual-review-manifest.json"
OBSERVATION_DIR = "visual/vision-observations"
READABILITY_DOCUMENT_NAME = "visual-readability.json"
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
    unverified: list[str] = Field(default_factory=list[str])
    readability_status: Literal["pass", "fail", "unknown"] | None = None


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
        document = read_json(path)
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
        document = read_json(path)
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
    readability_policy: ReadabilityPolicy | None = None,
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
    readability_observations: list[VisualReadabilityObservation] = []
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
            if readability_policy is not None:
                source_path = set_path.parent / record.image_path
                try:
                    readability = analyze_svg_readability(
                        source_path.read_bytes(),
                        policy=readability_policy,
                    )
                except OSError as exc:
                    readability = ReadabilityReport(
                        status="unknown",
                        findings=[
                            ReadabilityFinding(
                                code="malformed_svg",
                                detail=f"SVG source is unavailable: {exc}",
                            )
                        ],
                        text_count=0,
                        policy_hash=readability_policy.policy_hash(),
                    )
                readability_observations.append(
                    VisualReadabilityObservation(
                        projection_id=record.projection_id,
                        source_revision=record.source_revision,
                        image_hash=record.image_hash,
                        readability=readability,
                    )
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
    if readability_policy is not None:
        readability_observations.sort(key=lambda item: item.projection_id)
        readability_status: Literal["pass", "fail", "unknown"] = (
            "fail"
            if any(item.readability.status == "fail" for item in readability_observations)
            else "unknown"
            if any(
                item.readability.status == "unknown"
                for item in readability_observations
            )
            else "pass"
        )
        document = VisualReadabilityDocument(
            source_revision=source_revision,
            policy=readability_policy,
            observations=readability_observations,
            status=readability_status,
        )
        (out_root / READABILITY_DOCUMENT_NAME).write_text(
            document.model_dump_json(indent=2) + "\n",
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
    tool_events_path: Path,
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
    try:
        event_lines = tool_events_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise VisualReviewError(
            f"vision tool events could not be read: {tool_events_path}"
        ) from exc
    events: list[dict[str, object]] = []
    for line_number, line in enumerate(event_lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VisualReviewError(
                f"vision tool events contain invalid JSON at line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise VisualReviewError(
                f"vision tool events contain a non-object at line {line_number}"
            )
        events.append(cast(dict[str, object], value))
    response_hash = response_sha256(response)
    matching = [
        event
        for event in events
        if event.get("tool_name") == "inspect_image_with_vision"
        and event.get("response_sha256") == response_hash
        and event.get("profile_name") == profile_name
        and event.get("model") == model
    ]
    if not matching:
        raise VisualReviewError(
            f"no inspect_image_with_vision event matches the response for "
            f"{projection_id}"
        )
    try:
        def event_sequence(event: dict[str, object]) -> int:
            sequence = event.get("sequence")
            return sequence if isinstance(sequence, int) else -1

        selected: dict[str, object] = max(matching, key=event_sequence)
        tool_event = VisualVisionToolEvent.model_validate(
            {
                "event_id": selected["event_id"],
                "sequence": selected["sequence"],
                "response_sha256": selected["response_sha256"],
                "recorded_at": selected["recorded_at"],
                "events_path": str(tool_events_path),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VisualReviewError(
            f"vision tool event matching {projection_id} is invalid"
        ) from exc
    path = out_root / OBSERVATION_DIR / f"{projection_id}.json"
    observation_dir = path.parent
    if observation_dir.is_dir():
        for existing_path in observation_dir.glob("*.json"):
            if existing_path == path:
                continue
            existing = _observation_for(existing_path)
            if (
                existing is not None
                and existing.tool_event is not None
                and existing.tool_event.event_id == tool_event.event_id
            ):
                raise VisualReviewError(
                    f"vision tool event {tool_event.event_id} is already bound "
                    "to another observation"
                )
    write_visual_vision_observation(
        profile_name=profile_name,
        model=model,
        projection_id=projection_id,
        image_hash=image_hash,
        response=response,
        path=path,
        tool_event=tool_event,
        readability_hint=_readability_hint(out_root, projection_id),
    )
    return path


def _readability_hint(out_root: Path, projection_id: str) -> list[str] | None:
    path = out_root / READABILITY_DOCUMENT_NAME
    if not path.is_file():
        return None
    try:
        document = VisualReadabilityDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    observation = next(
        (
            item
            for item in document.observations
            if item.projection_id == projection_id
        ),
        None,
    )
    if observation is None:
        return None
    return sorted({finding.code for finding in observation.readability.findings})


def _observation_for(path: Path) -> VisualVisionObservation | None:
    try:
        document = read_json(path)
        return VisualVisionObservation.model_validate(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _load_event_log(path: Path) -> tuple[list[dict[str, object]], str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"vision tool events could not be read: {path}: {exc}"
    events: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return [], f"vision tool events contain invalid JSON at line {line_number}"
        if not isinstance(value, dict):
            return [], f"vision tool events contain a non-object at line {line_number}"
        events.append(cast(dict[str, object], value))
    return events, None


def verify_visual_review(
    out_root: Path,
    *,
    tool_events_path: Path | None = None,
) -> VisualReviewVerdict:
    """Verify that every manifest requirement has a matching observation.

    This function never raises on bad input: any missing, unreadable, or
    mismatched record is reported as a problem and the status stays
    ``incomplete``.
    """
    problems: list[str] = []
    readability_status: Literal["pass", "fail", "unknown"] | None = None
    readability_path = out_root / READABILITY_DOCUMENT_NAME
    if readability_path.is_file():
        try:
            readability_status = VisualReadabilityDocument.model_validate_json(
                readability_path.read_text(encoding="utf-8")
            ).status
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            readability_status = "unknown"
            problems.append(f"readability observations are invalid: {exc}")
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
            readability_status=readability_status,
        )
    if tool_events_path is None:
        tool_events_path = Path.cwd() / ".openhands/acd/vision-tool-events.jsonl"
    event_records, event_error = _load_event_log(tool_events_path)
    events_by_id = {
        str(event.get("event_id")): event
        for event in event_records
        if isinstance(event.get("event_id"), str)
    }
    unverified: list[str] = []
    bound_event_ids: dict[str, str] = {}
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
            elif observation.tool_event is None:
                status = "mismatch"
                reason = (
                    f"{requirement.projection_id}: observation has no bound "
                    "vision tool event"
                )
                problems.append(reason)
                unverified.append(reason)
            elif event_error is not None:
                status = "mismatch"
                reason = f"{requirement.projection_id}: {event_error}"
                problems.append(reason)
                unverified.append(reason)
            else:
                event_id = observation.tool_event.event_id
                event = events_by_id.get(event_id)
                reason: str | None = None
                if event is None:
                    reason = f"{requirement.projection_id}: tool event is not in the event log"
                elif (
                    event.get("tool_name") != "inspect_image_with_vision"
                    or event.get("response_sha256")
                    != observation.tool_event.response_sha256
                    or event.get("profile_name") != observation.profile_name
                    or event.get("model") != observation.model
                ):
                    reason = (
                        f"{requirement.projection_id}: tool event does not match "
                        "the observation"
                    )
                elif (
                    response_sha256(observation.response)
                    != observation.tool_event.response_sha256
                ):
                    reason = (
                        f"{requirement.projection_id}: observation response does "
                        "not match the bound tool event"
                    )
                elif event_id in bound_event_ids:
                    reason = (
                        f"{requirement.projection_id}: tool event is already "
                        f"bound to {bound_event_ids[event_id]}"
                    )
                else:
                    bound_event_ids[event_id] = requirement.projection_id
                if reason is not None:
                    status = "mismatch"
                    problems.append(reason)
                    unverified.append(reason)
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
        unverified=unverified,
        readability_status=readability_status,
    )


__all__ = [
    "GENERATED_BY",
    "OBSERVATION_DIR",
    "READABILITY_DOCUMENT_NAME",
    "VISUAL_REVIEW_MANIFEST_NAME",
    "VisualReviewError",
    "VisualReviewItemVerdict",
    "VisualReviewVerdict",
    "collect_visual_projection_sets",
    "derive_visual_review",
    "record_observation",
    "verify_visual_review",
]
