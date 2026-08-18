"""Tests for the model routing policy contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.model_routing import ModelRoutingPolicy


def _binding(role: str, model: str = "model-" + "a") -> dict[str, str]:
    return {
        "role": role,
        "model": model,
        "usage_id": f"{role}-usage",
        "profile": f"{role}-profile",
    }


def test_model_routing_policy_requires_distinct_agent_and_judge() -> None:
    with pytest.raises(ValidationError, match="different"):
        ModelRoutingPolicy.model_validate(
            {
                "bindings": [
                    _binding("agent", "same"),
                    _binding("judge", "same"),
                ]
            }
        )


@pytest.mark.parametrize(
    "bindings",
    [
        [_binding("agent")],
        [_binding("agent"), _binding("judge"), _binding("agent")],
        [_binding("agent"), _binding("judge"), _binding("other")],
        [
            _binding("agent"),
            _binding("judge", "model-b"),
            {**_binding("condenser"), "model": "unknown"},
        ],
    ],
)
def test_model_routing_policy_rejects_invalid_bindings(
    bindings: list[dict[str, str]],
) -> None:
    with pytest.raises(ValidationError):
        ModelRoutingPolicy.model_validate({"bindings": bindings})


def test_model_routing_policy_forbids_secret_fields() -> None:
    with pytest.raises(ValidationError):
        ModelRoutingPolicy.model_validate(
            {
                "bindings": [
                    _binding("agent"),
                    _binding("judge", "model-b"),
                ],
                "api_key": "not-allowed",
            }
        )
