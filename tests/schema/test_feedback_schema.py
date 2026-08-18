"""Tests for the feedback policy and proposal contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema import FeedbackPolicy, FeedbackProposal


def test_feedback_policy_fixture_is_typed() -> None:
    policy = FeedbackPolicy.model_validate_json(
        Path("fixtures/feedback/policy.json").read_text(encoding="utf-8")
    )
    assert policy.graph_id == "golden-design-1"
    assert [rule.rule_id for rule in policy.rules] == [
        "led-frequency-reconfirm",
        "artifact-count",
    ]


def test_feedback_policy_rejects_duplicate_rule_ids() -> None:
    with pytest.raises(ValidationError):
        FeedbackPolicy.model_validate(
            {
                "graph_id": "golden-design-1",
                "revision": "r1",
                "rules": [
                    {
                        "rule_id": "same",
                        "measurement_name": "led_frequency",
                        "node_id": "fw.pin.led",
                        "attr": "gpio",
                        "rule_kind": "set_value",
                        "tolerance": 0,
                        "decision_kind": "firmware_pin",
                    },
                    {
                        "rule_id": "same",
                        "measurement_name": "temperature",
                        "node_id": "fw.pin.uart_rx",
                        "attr": "gpio",
                        "rule_kind": "set_value",
                        "tolerance": 0,
                        "decision_kind": "firmware_pin",
                    },
                ],
            }
        )


def test_unknown_proposal_contract_accepts_fallback_values() -> None:
    proposal = FeedbackProposal(
        status="unknown",
        graph_id="unknown",
        revision="unknown",
        input_hash="unknown",
        output_hash="unknown",
        error="invalid input",
    )
    assert proposal.items == []
