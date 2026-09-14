from datetime import date
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema import PartLifecycleRegistry


def _payload() -> dict[str, object]:
    return {
        "registry_id": "gd1-lifecycle",
        "graph_id": "golden-design-1",
        "revision": "r1",
        "as_of": "2026-09-01",
        "entries": [
            {
                "mpn": "ESP32-C3-MINI-1-N4",
                "lifecycle_status": "active",
                "status_source": {
                    "kind": "manual_declaration",
                    "reference": "internal:gd1",
                    "observed_at": "2026-08-15",
                },
            }
        ],
        "policy": {
            "max_status_age_days": 60,
        },
    }


def test_part_lifecycle_registry_validates_contract() -> None:
    registry = PartLifecycleRegistry.model_validate(_payload())
    assert registry.artifact_kind == "part_lifecycle_registry"
    assert registry.as_of == date(2026, 9, 1)
    assert registry.policy.reject_statuses == ["eol", "obsolete"]


@pytest.mark.parametrize(
    "change",
    [
        {"entries": [{"mpn": "ESP32-C3-MINI-1-N4", "lifecycle_status": "bad"}]},
        {"policy": {"require_second_source_for": "single_source_risk_classes"}},
    ],
)
def test_part_lifecycle_registry_rejects_invalid_contract(change: dict[str, object]) -> None:
    payload = _payload()
    payload.update(change)
    with pytest.raises(ValidationError):
        PartLifecycleRegistry.model_validate(payload)


def test_duplicate_mpn_is_rejected() -> None:
    payload = _payload()
    entries = cast(list[dict[str, Any]], payload["entries"])
    payload["entries"] = [
        entries[0],
        {
            "mpn": "ESP32-C3-MINI-1-N4",
            "lifecycle_status": "active",
            "status_source": {
                "kind": "manual_declaration",
                "reference": "internal:gd1-2",
                "observed_at": "2026-08-15",
            },
        },
    ]
    with pytest.raises(ValidationError):
        PartLifecycleRegistry.model_validate(payload)
