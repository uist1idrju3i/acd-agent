from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.rework_diff import ReworkDiff


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "workaround_id": "WA-001",
        "graph_id": "golden-design-1",
        "base_revision": "r1",
        "defect_ids": ["defect.r4-mpn"],
        "operations": [
            {
                "op": "replace",
                "component_id": "comp.r4",
                "attrs": {"value": "10k"},
                "reason": "Change the resistor value.",
            }
        ],
        "touches_safety_boundary": False,
    }
    value.update(overrides)
    return value


def test_operation_discriminator_and_derived_revision() -> None:
    diff = ReworkDiff.model_validate(_payload())
    assert diff.operations[0].op == "replace"
    assert diff.derived_revision == "r1+WA-001"


def test_bad_workaround_id_fails() -> None:
    with pytest.raises(ValidationError):
        ReworkDiff.model_validate(_payload(workaround_id="WA-1"))


def test_empty_operations_fail() -> None:
    with pytest.raises(ValidationError):
        ReworkDiff.model_validate(_payload(operations=[]))


def test_replace_with_disallowed_key_fails() -> None:
    with pytest.raises(ValidationError):
        ReworkDiff.model_validate(
            _payload(
                operations=[
                    {
                        "op": "replace",
                        "component_id": "comp.r4",
                        "attrs": {"voltage": 3.3},
                        "reason": "Change an unsupported attribute.",
                    }
                ]
            )
        )
