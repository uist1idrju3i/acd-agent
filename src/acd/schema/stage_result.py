"""Common core of pipeline stage results.

Stage runners return free-form dicts because their payloads differ, but every
result must carry the same fail-closed core. `StageResultCore` validates that core
at the orchestration boundary; extra payload keys are carried through untouched.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import StrictBool, ValidationError, model_validator

from acd.schema.common import AcdModel, NonEmptyStr

STAGE_RESULT_CORE_KEYS: frozenset[str] = frozenset(
    {"stage_id", "ok", "fail_closed", "pass_evidence", "failure_reason"}
)


class StageResultCore(AcdModel):
    """Fields every stage result must agree on.

    `pass_evidence` is fixed to False: stage results are L3 records and never
    carry gate authority. A result cannot be both `ok` and `fail_closed`, and a
    failed result must state why.
    """

    stage_id: NonEmptyStr
    ok: StrictBool
    fail_closed: StrictBool
    pass_evidence: Literal[False] = False
    failure_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _consistent(self) -> StageResultCore:
        if self.ok and self.fail_closed:
            raise ValueError("a stage result cannot be both ok and fail_closed")
        if not self.ok and self.failure_reason is None:
            raise ValueError("a failed stage result must carry failure_reason")
        return self


def normalize_stage_result(stage_id: str, result: object) -> dict[str, Any]:
    """Return `result` with a validated core, or a fail-closed failure for `stage_id`.

    The orchestrator's `stage_id` is authoritative and overrides whatever the runner
    reported. Non-object results, non-boolean flags, contradictory flags, and any
    truthy `pass_evidence` are rewritten into a failure so orchestration never
    treats a malformed result as success.
    """
    if not isinstance(result, dict):
        return failed_stage_result(stage_id, "stage runner returned a non-object result")
    payload = cast(dict[str, Any], result)
    core_input = {key: payload[key] for key in STAGE_RESULT_CORE_KEYS if key in payload}
    core_input["stage_id"] = stage_id
    core_input.setdefault("pass_evidence", False)
    try:
        core = StageResultCore.model_validate(core_input)
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'result'}: {error['msg']}"
            for error in exc.errors()
        )
        return failed_stage_result(
            stage_id, f"stage result violates the StageResultCore contract: {reasons}"
        )
    return {**payload, **core.model_dump(exclude_none=True)}


def failed_stage_result(stage_id: str, reason: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "failure_reason": reason,
        **fields,
    }


def successful_stage_result(stage_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "ok": True,
        "fail_closed": False,
        "pass_evidence": False,
        **fields,
    }


__all__ = [
    "STAGE_RESULT_CORE_KEYS",
    "StageResultCore",
    "failed_stage_result",
    "normalize_stage_result",
    "successful_stage_result",
]
