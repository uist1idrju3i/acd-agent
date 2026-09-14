from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import UseEnvironment


def _payload() -> dict[str, object]:
    return {
        "graph_id": "golden-design-1",
        "revision": "r1",
        "installation": "indoor_residential",
        "power_system": "usb_host",
        "temperature_c": {"min": 0.0, "max": 40.0},
        "humidity_rh_pct": {"min": 20.0, "max": 80.0},
        "vibration": "stationary",
        "external_ports": [{"connector_node_id": "comp.j1", "exposure": "user_accessible"}],
    }


def test_use_environment_validates_contract() -> None:
    environment = UseEnvironment.model_validate(_payload())
    assert environment.artifact_kind == "use_environment"


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperature_c", {"min": 41.0, "max": 40.0}),
        ("temperature_c", {"min": float("inf"), "max": 40.0}),
        ("humidity_rh_pct", {"min": -1.0, "max": 80.0}),
        ("humidity_rh_pct", {"min": 20.0, "max": 101.0}),
        ("installation", "laboratory"),
        ("power_system", "generator"),
        ("vibration", "rotating"),
    ],
)
def test_use_environment_rejects_invalid_values(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        UseEnvironment.model_validate(payload)


def test_unknown_enum_values_are_allowed() -> None:
    payload = _payload()
    payload.update(
        installation="unknown",
        power_system="unknown",
        vibration="unknown",
    )
    assert UseEnvironment.model_validate(payload).installation == "unknown"


def test_external_port_ids_are_unique() -> None:
    payload = _payload()
    payload["external_ports"] = [
        {"connector_node_id": "comp.j1", "exposure": "user_accessible"},
        {"connector_node_id": "comp.j1", "exposure": "internal"},
    ]
    with pytest.raises(ValidationError):
        UseEnvironment.model_validate(payload)
