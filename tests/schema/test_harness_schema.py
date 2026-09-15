"""Schema tests for the declared harness contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema import HarnessContract

FIXTURE = Path("fixtures/harness/gd1-external-sensor/harness.json")


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_harness_fixture_is_valid() -> None:
    contract = HarnessContract.model_validate(_payload())
    assert len(contract.wires) == 4


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("wire_type_id", "missing-wire-type"),
        ("connector_id", "missing-connector"),
    ],
)
def test_harness_rejects_dangling_references(
    field: str, replacement: str
) -> None:
    payload = _payload()
    if field == "wire_type_id":
        payload["wires"][0][field] = replacement  # type: ignore[index]
    else:
        payload["wires"][0]["from"][field] = replacement  # type: ignore[index]
    with pytest.raises(ValidationError):
        HarnessContract.model_validate(payload)


def test_harness_rejects_duplicate_cavity() -> None:
    payload = _payload()
    payload["wires"][1]["from"]["cavity"] = "1"  # type: ignore[index]
    with pytest.raises(ValidationError):
        HarnessContract.model_validate(payload)


def test_harness_rejects_zero_length() -> None:
    payload = _payload()
    payload["wires"][0]["length_mm"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError):
        HarnessContract.model_validate(payload)
