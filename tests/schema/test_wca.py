from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from acd.schema import ToleranceTable, WcaRequest

ROOT = Path(__file__).parents[2]


def _payload(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_gd1_wca_contracts_validate() -> None:
    table = ToleranceTable.model_validate(
        _payload("fixtures/wca/gd1-tolerances.json")
    )
    request = WcaRequest.model_validate(
        _payload("fixtures/wca/gd1-request.json")
    )
    assert table.table_id == "gd1-tolerances-2026-09"
    assert request.service_life_years == 10.0


def test_duplicate_tolerance_entries_are_rejected() -> None:
    payload = _payload("fixtures/wca/gd1-tolerances.json")
    payload["entries"] = [payload["entries"][0], payload["entries"][0]]
    with pytest.raises(ValidationError):
        ToleranceTable.model_validate(payload)


def test_declared_quantity_requires_nominal_value() -> None:
    payload = _payload("fixtures/wca/gd1-request.json")
    quantity = dict(payload["quantities"][0])
    quantity["nominal_source"] = "declared"
    quantity.pop("nominal_value", None)
    payload["quantities"] = [quantity]
    with pytest.raises(ValidationError):
        WcaRequest.model_validate(payload)
