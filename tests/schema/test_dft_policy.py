from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import DftPolicy


def _payload() -> dict[str, object]:
    return {
        "graph_id": "golden-design-1",
        "revision": "r1",
        "required_net_classes": ["power_rail"],
        "required_net_ids": [],
        "min_probe_pitch_mm": 2.54,
        "min_pad_diameter_mm": 1.0,
        "probe_side": "either",
        "keepout_from_components_mm": 0.5,
    }


def test_dft_policy_validates_contract() -> None:
    policy = DftPolicy.model_validate(_payload())
    assert policy.artifact_kind == "dft_policy"


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_probe_pitch_mm", 0.0),
        ("min_probe_pitch_mm", -1.0),
        ("min_pad_diameter_mm", 0.0),
        ("min_pad_diameter_mm", -1.0),
        ("keepout_from_components_mm", -0.1),
        ("required_net_classes", ["not_a_class"]),
    ],
)
def test_dft_policy_rejects_invalid_values(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        DftPolicy.model_validate(payload)


def test_dft_policy_requires_a_class_or_explicit_net() -> None:
    payload = _payload()
    payload["required_net_classes"] = []
    payload["required_net_ids"] = []
    with pytest.raises(ValidationError):
        DftPolicy.model_validate(payload)


def test_dft_policy_accepts_explicit_nets_without_classes() -> None:
    payload = _payload()
    payload["required_net_classes"] = []
    payload["required_net_ids"] = ["net.gnd"]
    assert DftPolicy.model_validate(payload).required_net_ids == ["net.gnd"]
