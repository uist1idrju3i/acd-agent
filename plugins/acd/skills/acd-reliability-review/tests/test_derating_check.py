"""Derating screening tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import pytest

from derating_check import evaluate, evaluate_item


def item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "refdes": "C1",
        "parameter": "voltage",
        "rating": 16.0,
        "derating_factor": 0.5,
        "applied_worst_case": 5.5,
        "conditions": {"ambient_c": 45.0},
        "validity_domain": {"ambient_c": [-40.0, 85.0]},
    }
    base.update(overrides)
    return base


def test_within_allowed_stress_passes() -> None:
    result = evaluate_item(item())
    assert result.verdict == "pass"
    assert result.allowed == pytest.approx(8.0)
    assert result.margin_ratio == pytest.approx(0.6875)


def test_stress_above_allowed_fails() -> None:
    result = evaluate_item(item(applied_worst_case=9.0))
    assert result.verdict == "fail"
    assert "exceeds" in result.reason


def test_unknown_rating_needs_analysis_not_pass() -> None:
    result = evaluate_item(item(rating=None))
    assert result.verdict == "needs_analysis"
    assert result.allowed is None


def test_condition_outside_validity_domain_needs_analysis() -> None:
    result = evaluate_item(item(conditions={"ambient_c": 105.0}))
    assert result.verdict == "needs_analysis"
    assert "outside" in result.reason


def test_missing_validity_domain_needs_analysis() -> None:
    declared = item()
    del declared["validity_domain"]
    assert evaluate_item(declared).verdict == "needs_analysis"


def test_invalid_derating_factor_fails_closed() -> None:
    with pytest.raises(ValueError, match="derating factor"):
        evaluate_item(item(derating_factor=1.5))


def test_missing_identity_fails_closed() -> None:
    declared = item()
    del declared["refdes"]
    with pytest.raises(ValueError, match="refdes"):
        evaluate_item(declared)


def test_results_are_sorted_by_refdes_and_parameter() -> None:
    results = evaluate(
        [
            item(refdes="R2", parameter="power"),
            item(refdes="R1", parameter="voltage"),
            item(refdes="R1", parameter="power"),
        ]
    )
    assert [(result.refdes, result.parameter) for result in results] == [
        ("R1", "power"),
        ("R1", "voltage"),
        ("R2", "power"),
    ]
