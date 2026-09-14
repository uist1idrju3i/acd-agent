"""Deterministic resolution of declared per-lane retained artifact sets.

Retention is an L3/operational observation: it declares which lane outputs
must be kept and which are regenerable. It never decides a gate; the
required-artifact judgement stays with the manufacturing submission gate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.lane_artifact_retention import (
    LaneArtifactRetention,
    LaneArtifactRetentionDocument,
)

AUTHORITY_STATEMENT = (
    "Retention declares what to keep; required-artifact judgement "
    "stays with the manufacturing submission gate."
)

DEFAULT_CONTRACT = Path("contracts/lane-artifact-retention.json")


class LaneArtifactRetentionError(ValueError):
    """Raised when the retention declaration cannot be resolved safely."""


@dataclass(frozen=True)
class LaneArtifactRetentionDeclaration:
    """The loaded retention contract and its content hash."""

    document: LaneArtifactRetentionDocument
    declaration_hash: str
    path: Path

    def lane(self, lane_id: str) -> LaneArtifactRetention | None:
        return next(
            (item for item in self.document.lanes if item.lane_id == lane_id), None
        )


@dataclass(frozen=True)
class RetainedArtifact:
    """One matched minimal artifact with its content address."""

    pattern: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class LaneRetentionReport:
    """Resolved retention observation for one lane output directory."""

    lane_id: str
    output_path: str
    status: str
    retained: tuple[RetainedArtifact, ...]
    missing_required: tuple[str, ...]
    regenerable_files: int
    regenerable_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_class": "L3",
            "pass_evidence": False,
            "authority_statement": AUTHORITY_STATEMENT,
            "lane_id": self.lane_id,
            "output_path": self.output_path,
            "status": self.status,
            "retained": [
                {
                    "pattern": item.pattern,
                    "path": item.path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in self.retained
            ],
            "missing_required": list(self.missing_required),
            "regenerable_files": self.regenerable_files,
            "regenerable_bytes": self.regenerable_bytes,
        }


def load_lane_artifact_retention(
    path: Path | None = None,
) -> LaneArtifactRetentionDeclaration:
    """Load the lane artifact retention contract (fail-closed)."""
    resolved = path if path is not None else repository_root() / DEFAULT_CONTRACT
    try:
        document = LaneArtifactRetentionDocument.model_validate_json(
            resolved.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise LaneArtifactRetentionError(
            f"lane artifact retention contract is invalid or unreadable: "
            f"{resolved}: {exc}"
        ) from exc
    return LaneArtifactRetentionDeclaration(
        document=document,
        declaration_hash=canonical_json_sha256(
            document.model_dump(mode="json")
        ),
        path=resolved,
    )


def _file_sha256(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise LaneArtifactRetentionError(
            f"cannot hash retained artifact: {path}: {exc}"
        ) from exc


def _match_files(output_dir: Path, pattern: str) -> list[Path]:
    """Match a declared glob against files below the lane output directory."""
    try:
        matches = [
            path
            for path in output_dir.glob(pattern)
            if path.is_file()
        ]
    except (OSError, ValueError) as exc:
        raise LaneArtifactRetentionError(
            f"retention pattern cannot be evaluated: {pattern!r}: {exc}"
        ) from exc
    return sorted(matches, key=lambda path: path.relative_to(output_dir).as_posix())


def resolve_lane_retention(
    lane_id: str,
    output_dir: Path,
    declaration: LaneArtifactRetentionDeclaration,
) -> LaneRetentionReport:
    """Resolve declared retention patterns against one lane output directory."""
    lane = declaration.lane(lane_id)
    if lane is None:
        raise LaneArtifactRetentionError(
            f"lane {lane_id!r} has no declared artifact retention (fail-closed)"
        )
    retained: list[RetainedArtifact] = []
    missing_required: list[str] = []
    for item in lane.minimal_artifacts:
        matches = _match_files(output_dir, item.pattern)
        if not matches:
            if item.required:
                missing_required.append(item.pattern)
            continue
        retained.extend(
            RetainedArtifact(
                pattern=item.pattern,
                path=path.relative_to(output_dir).as_posix(),
                size_bytes=path.stat().st_size,
                sha256=_file_sha256(path),
            )
            for path in matches
        )
    regenerable_files = 0
    regenerable_bytes = 0
    for item in lane.regenerable:
        for path in _match_files(output_dir, item.pattern):
            regenerable_files += 1
            regenerable_bytes += path.stat().st_size
    status = "complete" if not missing_required else "missing_required"
    return LaneRetentionReport(
        lane_id=lane_id,
        output_path=str(output_dir),
        status=status,
        retained=tuple(retained),
        missing_required=tuple(missing_required),
        regenerable_files=regenerable_files,
        regenerable_bytes=regenerable_bytes,
    )


__all__ = [
    "AUTHORITY_STATEMENT",
    "DEFAULT_CONTRACT",
    "LaneArtifactRetentionDeclaration",
    "LaneArtifactRetentionError",
    "LaneRetentionReport",
    "RetainedArtifact",
    "load_lane_artifact_retention",
    "resolve_lane_retention",
]
