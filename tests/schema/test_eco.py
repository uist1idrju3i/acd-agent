"""Schema validation tests for ECO contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema.eco import EcoRecord

ROOT = Path(__file__).resolve().parents[2]
ECO_PATH = ROOT / "fixtures/eco/sample/eco.json"


def _payload() -> dict[str, object]:
    body = cast(dict[str, Any], json.loads(ECO_PATH.read_text(encoding="utf-8")))
    assert isinstance(body, dict)
    ecos: list[Any] = body["ecos"]
    assert isinstance(ecos, list)
    assert ecos
    record: dict[str, object] = cast(dict[str, object], ecos[0])
    assert isinstance(record, dict)
    return record


def test_deferred_disposition_cannot_target_own_eco() -> None:
    payload = _payload()
    payload["horizontal_dispositions"] = [
        {
            "defect_id": "defect.r4-mpn",
            "node_id": "comp.r5",
            "disposition": "deferred",
            "reason": "Track in the current ECO.",
            "deferred_to": "ECO-001",
        }
    ]
    with pytest.raises(ValidationError, match="cannot defer to itself"):
        EcoRecord.model_validate(payload)


def test_eco_rejects_non_increasing_revision() -> None:
    payload = _payload()
    payload["from_revision"] = "r2"
    payload["to_revision"] = "r2"
    with pytest.raises(ValidationError, match="newer"):
        EcoRecord.model_validate(payload)


@pytest.mark.parametrize("field", ["from_revision", "to_revision"])
def test_eco_rejects_workaround_revision(field: str) -> None:
    payload = _payload()
    payload[field] = "r1+WA-001"
    with pytest.raises(ValidationError, match="canonical"):
        EcoRecord.model_validate(payload)
