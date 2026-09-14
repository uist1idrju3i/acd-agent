"""Schema contract tests for the lane artifact retention declaration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.lane_artifact_retention import (
    LaneArtifactRetentionDocument,
    MinimalArtifactPattern,
)


def _lane(**overrides: object) -> dict[str, object]:
    lane: dict[str, object] = {
        "lane_id": "board-pipeline",
        "title": "board outputs",
        "minimal_artifacts": [
            {"pattern": "summary.json", "required": True, "reason": "summary"}
        ],
        "regenerable": [],
    }
    lane.update(overrides)
    return lane


def _document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "0.1",
        "declaration_id": "acd-lane-artifact-retention-v1",
        "lanes": [_lane()],
    }
    document.update(overrides)
    return document


def test_valid_document_loads() -> None:
    document = LaneArtifactRetentionDocument.model_validate(_document())
    assert document.lanes[0].lane_id == "board-pipeline"


def test_absolute_pattern_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MinimalArtifactPattern.model_validate(
            {"pattern": "/abs/path.json", "required": True, "reason": "x"}
        )


def test_parent_traversal_pattern_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MinimalArtifactPattern.model_validate(
            {"pattern": "../escape.json", "required": True, "reason": "x"}
        )


def test_duplicate_lane_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LaneArtifactRetentionDocument.model_validate(
            _document(lanes=[_lane(), _lane()])
        )


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LaneArtifactRetentionDocument.model_validate(
            _document(lanes=[_lane(extra="nope")])
        )
