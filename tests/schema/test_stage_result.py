import pytest

from acd.schema.stage_result import (
    StageResultCore,
    failed_stage_result,
    normalize_stage_result,
    successful_stage_result,
)


def test_success_and_failure_helpers_share_the_core() -> None:
    ok = normalize_stage_result("s", successful_stage_result("s", artifact="a"))
    assert ok["ok"] and not ok["fail_closed"] and ok["artifact"] == "a"
    failed = normalize_stage_result("s", failed_stage_result("s", "boom", detail=1))
    assert failed["fail_closed"] and failed["failure_reason"] == "boom"
    assert failed["detail"] == 1


def test_pass_evidence_never_survives_normalization() -> None:
    result = normalize_stage_result("s", {**successful_stage_result("s"), "pass_evidence": True})
    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["pass_evidence"] is False
    assert "pass_evidence" in result["failure_reason"]


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        "ok",
        {"ok": True},
        {"stage_id": "s", "ok": "yes", "fail_closed": False},
        {"stage_id": "s", "ok": True, "fail_closed": True},
        {"stage_id": "s", "ok": False, "fail_closed": True},
    ],
)
def test_malformed_results_fail_closed(malformed: object) -> None:
    result = normalize_stage_result("s", malformed)
    assert result["stage_id"] == "s"
    assert result["ok"] is False
    assert result["fail_closed"] is True
    assert result["pass_evidence"] is False
    assert isinstance(result["failure_reason"], str) and result["failure_reason"]


def test_orchestrator_stage_id_overrides_runner_report() -> None:
    result = normalize_stage_result("s", successful_stage_result("other"))
    assert result["stage_id"] == "s"
    assert result["ok"] is True


def test_core_model_rejects_contradictions_directly() -> None:
    with pytest.raises(ValueError):
        StageResultCore(stage_id="s", ok=True, fail_closed=True)
    with pytest.raises(ValueError):
        StageResultCore(stage_id="s", ok=False, fail_closed=True)
