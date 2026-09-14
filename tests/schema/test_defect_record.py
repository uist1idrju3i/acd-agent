from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.defect_record import (
    AffectedUnits,
    DefectDocument,
    DefectRecord,
    HorizontalScope,
    ReproductionCondition,
    RootCauseCandidate,
)


def _record(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "defect_id": "defect-1",
        "severity": "functional",
        "symptom": "A function fails.",
        "affected_functions": ["function-1"],
        "affected_units": {
            "lots": ["lot-1"],
            "serials": [],
            "scope_status": "declared",
        },
        "reproduction": {
            "description": "Run the function.",
            "environment": {},
            "occurrence_rate": 0.5,
            "sample_size": 2,
        },
        "root_cause_candidates": [
            {
                "candidate_id": "cause-1",
                "status": "identified",
                "description": "The anchor is known.",
                "node_ids": ["comp.u1"],
                "rule_ids": [],
                "confidence": "suspected",
            }
        ],
        "horizontal_scopes": [
            {
                "criterion": criterion,
                "search_status": "searched",
                "matched_node_ids": [],
                "excluded": [],
            }
            for criterion in (
                "same_component_mpn",
                "same_node_kind",
                "same_rule",
                "same_fixture",
                "same_profile",
            )
        ],
        "fixture_refs": [],
        "profile_refs": [],
    }
    value.update(overrides)
    return value


def test_unknown_units_with_lots_fail() -> None:
    with pytest.raises(ValidationError):
        AffectedUnits(lots=["lot-1"], serials=[], scope_status="unknown")


def test_unsearched_scope_with_matches_fails() -> None:
    with pytest.raises(ValidationError):
        HorizontalScope(
            criterion="same_rule",
            search_status="unsearched",
            matched_node_ids=["comp.u1"],
            excluded=[],
        )


def test_missing_horizontal_criterion_fails() -> None:
    record = _record()
    record["horizontal_scopes"] = [
        scope
        for scope in record["horizontal_scopes"]  # type: ignore[index]
        if scope["criterion"] != "same_profile"  # type: ignore[index]
    ]
    with pytest.raises(ValidationError):
        DefectRecord.model_validate(record)


def test_duplicate_ids_fail() -> None:
    record = _record(
        affected_functions=["function-1", "function-1"],
    )
    with pytest.raises(ValidationError):
        DefectRecord.model_validate(record)

    document = {
        "schema_version": "0.1",
        "artifact_kind": "defect_record",
        "graph_id": "golden-design-1",
        "revision": "r1",
        "records": [_record(), _record()],
    }
    with pytest.raises(ValidationError):
        DefectDocument.model_validate(document)


def test_measurement_bounds_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ReproductionCondition(
            description="Run the function.",
            occurrence_rate=0.0,
            sample_size=1,
        )
    with pytest.raises(ValidationError):
        ReproductionCondition(
            description="Run the function.",
            occurrence_rate=1.0,
            sample_size=0,
        )

    with pytest.raises(ValidationError):
        RootCauseCandidate(
            candidate_id="cause-1",
            status="identified",
            description="Missing anchor.",
            node_ids=[],
            confidence="suspected",
        )
