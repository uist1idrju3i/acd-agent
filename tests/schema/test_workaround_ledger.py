"""Schema validation tests for workaround traceability contracts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema.workaround_ledger import (
    UnitDisposition,
    UnitRef,
    WorkaroundApplication,
    WorkaroundLedger,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "fixtures/workaround-ledger/sample/ledger.json"


def _ledger_payload() -> dict[str, Any]:
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def test_unit_ref_requires_lot_or_serial() -> None:
    with pytest.raises(ValidationError, match="requires lot or serial"):
        UnitRef()


def test_duplicate_application_is_rejected() -> None:
    payload = _ledger_payload()
    application = cast(list[Any], payload["applications"])[0]
    payload["applications"].append(application)
    with pytest.raises(ValidationError, match="unique per workaround and unit"):
        WorkaroundLedger.model_validate(payload)


def test_naive_application_datetime_is_rejected() -> None:
    ledger = _ledger_payload()
    application = cast(list[Any], ledger["applications"])[0]
    assert isinstance(application, dict)
    application["applied_at"] = datetime(2026, 1, 2).isoformat()
    with pytest.raises(ValidationError):
        WorkaroundApplication.model_validate(application)


def test_scrapped_disposition_cannot_have_revision() -> None:
    with pytest.raises(ValidationError, match="must not have revision"):
        UnitDisposition(
            unit=UnitRef(lot="LOT-GD1-001"),
            disposition="scrapped",
            revision="r2",
            reason="Unit was scrapped.",
        )


def test_upgraded_disposition_requires_revision() -> None:
    with pytest.raises(ValidationError, match="requires revision"):
        UnitDisposition(
            unit=UnitRef(lot="LOT-GD1-001"),
            disposition="upgraded_to_revision",
            reason="Unit was upgraded.",
        )
