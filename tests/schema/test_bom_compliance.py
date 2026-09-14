from datetime import date
from typing import Any, cast

import pytest
from pydantic import ValidationError

from acd.schema import ComplianceDeclarationRegistry


def _payload() -> dict[str, Any]:
    return {
        "registry_id": "bom-compliance-test",
        "graph_id": "golden-design-1",
        "revision": "r1",
        "as_of": "2026-09-01",
        "regimes": ["rohs", "reach_svhc"],
        "entries": [
            {
                "mpn": "TEST-MPN",
                "declarations": [
                    {
                        "regime": "rohs",
                        "declared_status": "declared_compliant",
                        "source": {
                            "kind": "manual_declaration",
                            "reference": "internal:test",
                            "observed_at": "2026-08-15",
                        },
                    }
                ],
            }
        ],
        "policy": {
            "required_regimes": ["rohs"],
            "max_declaration_age_days": 60,
        },
    }


def test_compliance_registry_validates_declaration_contract() -> None:
    registry = ComplianceDeclarationRegistry.model_validate(_payload())
    assert registry.artifact_kind == "compliance_declaration_registry"
    assert registry.as_of == date(2026, 9, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"regimes": ["rohs", "rohs"]},
        {
            "entries": [
                {
                    "mpn": "TEST-MPN",
                    "declarations": [
                        {
                            "regime": "rohs",
                            "declared_status": "declared_compliant",
                            "source": {
                                "kind": "manual_declaration",
                                "reference": "internal:test",
                                "observed_at": "2026-08-15",
                            },
                        },
                        {
                            "regime": "rohs",
                            "declared_status": "unknown",
                            "source": {
                                "kind": "manual_declaration",
                                "reference": "internal:test-2",
                                "observed_at": "2026-08-15",
                            },
                        },
                    ],
                }
            ]
        },
        {
            "entries": [
                {
                    "mpn": "TEST-MPN",
                    "declarations": [
                        {
                            "regime": "rohs",
                            "declared_status": "declared_compliant",
                            "exemption_reference": "RoHS Annex III 7(c)-I",
                            "source": {
                                "kind": "manual_declaration",
                                "reference": "internal:test",
                                "observed_at": "2026-08-15",
                            },
                        }
                    ],
                }
            ]
        },
    ],
)
def test_compliance_registry_rejects_malformed_contract(
    change: dict[str, object],
) -> None:
    payload = _payload()
    payload.update(change)
    with pytest.raises(ValidationError):
        ComplianceDeclarationRegistry.model_validate(payload)


def test_duplicate_mpn_is_rejected() -> None:
    payload = _payload()
    entries = cast(list[dict[str, Any]], payload["entries"])
    payload["entries"] = [entries[0], entries[0]]
    with pytest.raises(ValidationError):
        ComplianceDeclarationRegistry.model_validate(payload)
