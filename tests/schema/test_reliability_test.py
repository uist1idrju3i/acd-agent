from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from acd.schema import ReliabilityTestPlan

FIXTURE = "fixtures/reliability-test/gd1-indoor-usb.json"


def _payload() -> dict[str, object]:
    with open(FIXTURE, encoding="utf-8") as stream:
        return json.load(stream)


def test_reliability_plan_validates_fixture() -> None:
    plan = ReliabilityTestPlan.model_validate(_payload())
    assert plan.artifact_kind == "reliability_test_plan"
    assert plan.plan_id == "gd1-indoor-usb-reliability"


@pytest.mark.parametrize(
    "environment_ref",
    [
        {},
        {"path": "fixtures/use-environment/gd1-indoor-usb.json", "environment": {}},
    ],
)
def test_environment_reference_requires_exactly_one_form(
    environment_ref: dict[str, object],
) -> None:
    payload = _payload()
    payload["environment_ref"] = environment_ref
    with pytest.raises(ValidationError):
        ReliabilityTestPlan.model_validate(payload)


def test_measured_metadata_can_be_declared_for_gate_rejection() -> None:
    payload = _payload()
    payload["measured_results"] = [
        {
            "conditions": {"temperature_c": 25.0},
            "equipment": None,
            "specimen_revision": "r1",
            "test_item_id": "test-esd",
            "verdict": "observed",
        }
    ]
    plan = ReliabilityTestPlan.model_validate(payload)
    assert plan.measured_results[0].equipment is None
