"""Fail-closed order-execution runner tests."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openhands.sdk.hooks import HookConfig
from openhands.sdk.security import ConfirmRisky, SecurityRisk
from openhands.sdk.security.confirmation_policy import ConfirmationPolicyBase, NeverConfirm

from acd.core.side_effect_journal import (
    SideEffectJournalError,
    reconstruct_order,
)
from acd.openhands.order_execution import OrderExecutionError, execute_order
from acd.schema import (
    EvidenceReference,
    PreOrderGateRecord,
    QuoteAmount,
)
from acd.schema.common import NonEmptyStr, Revision, Sha256, Timestamp
from acd.schema.side_effect_journal import ExecutionMode

ROOT = Path(__file__).parents[2]
HOOKS = HookConfig.load(ROOT / "plugins/acd/hooks/hooks.json")
TIMESTAMP = datetime(2026, 8, 14, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
PACKAGE_HASH = "sha256:" + "b" * 64
DEFAULT_CONFIRMATION_POLICY = ConfirmRisky(threshold=SecurityRisk.MEDIUM)


def _authorization() -> PreOrderGateRecord:
    amount = QuoteAmount(amount_minor=100, currency="USD", minor_unit_digits=2)
    return PreOrderGateRecord.create(
        target_revision="r1",
        total=amount,
        upper_limit=amount,
        breakdown_hash=HASH,
        evidence=[
            EvidenceReference(evidence_id="evidence.gd1.electrical", canonical_hash=HASH),
            EvidenceReference(evidence_id="evidence.gd1.mechanical", canonical_hash=HASH),
        ],
        policy_hash=HASH,
        evaluated_at=TIMESTAMP,
    )


def _run_success(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["dry-run"],
        returncode=0,
        stdout="dry-run output",
        stderr="",
    )


def _execute(
    path: Path,
    *,
    confirmation_policy: ConfirmationPolicyBase | None = DEFAULT_CONFIRMATION_POLICY,
    provider_credential_reference: str = "ACD_API_KEY",
    execution_mode: ExecutionMode = "dry_run",
    run: Callable[..., subprocess.CompletedProcess[str]] = _run_success,
    command: Sequence[str] | None = ("dry-run",),
):
    idempotency_key = "order-20260814"
    package_hash: Sha256 = PACKAGE_HASH
    destination: NonEmptyStr = "supplier.example"
    target_revision: Revision = "r1"
    occurred_at: Timestamp = TIMESTAMP
    return execute_order(
        authorization=_authorization(),
        journal_path=path,
        idempotency_key=idempotency_key,
        package_hash=package_hash,
        destination=destination,
        target_revision=target_revision,
        provider_credential_reference=provider_credential_reference,
        confirmation_policy=confirmation_policy,
        hook_config=HOOKS,
        occurred_at=occurred_at,
        execution_mode=execution_mode,
        command=command,
        run=run,
    )


def test_dry_run_is_deterministic_and_journaled(tmp_path: Path) -> None:
    first = _execute(tmp_path / "first.jsonl")
    second = _execute(tmp_path / "second.jsonl")

    assert first.payload == second.payload
    assert first.payload_hash == second.payload_hash
    assert first.payload.execution_mode == "dry_run"
    assert first.planned.execution_mode == "dry_run"
    assert first.result.execution_mode == "dry_run"
    assert first.result.result_status == "success"


def test_dry_run_cannot_satisfy_real_completion(tmp_path: Path) -> None:
    result = _execute(tmp_path / "journal.jsonl")

    with pytest.raises(SideEffectJournalError, match="not a real execution"):
        reconstruct_order(
            tmp_path / "journal.jsonl",
            idempotency_key=result.planned.idempotency_key,
            require_real=True,
        )


def test_real_mode_is_explicitly_disabled_before_journal_write(tmp_path: Path) -> None:
    with pytest.raises(OrderExecutionError, match="not enabled"):
        _execute(tmp_path / "journal.jsonl", execution_mode="real")
    assert not (tmp_path / "journal.jsonl").exists()


def test_confirmation_policy_and_secret_reference_are_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(OrderExecutionError, match="confirmation policy"):
        _execute(tmp_path / "missing-confirmation.jsonl", confirmation_policy=None)
    with pytest.raises(OrderExecutionError, match="allowlisted"):
        _execute(
            tmp_path / "missing-secret.jsonl",
            provider_credential_reference="NOT_ALLOWED",
        )
    with pytest.raises(OrderExecutionError, match="confirmation policy"):
        _execute(
            tmp_path / "skip-confirmation.jsonl",
            confirmation_policy=NeverConfirm(),
        )


def test_subprocess_failure_is_recorded_as_failure_and_raises(
    tmp_path: Path,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["dry-run"],
            returncode=7,
            stdout="",
            stderr="provider failed",
        )

    path = tmp_path / "journal.jsonl"
    with pytest.raises(OrderExecutionError, match="exit code 7"):
        _execute(path, run=fail)
    recorded = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    assert recorded["result_status"] == "failure"


def test_subprocess_start_failure_is_recorded_as_failure(
    tmp_path: Path,
) -> None:
    def fail_to_start(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("not executable")

    path = tmp_path / "journal.jsonl"
    with pytest.raises(OrderExecutionError, match="could not start"):
        _execute(path, run=fail_to_start)
    recorded = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    assert recorded["result_status"] == "failure"


def test_secret_values_are_not_journaled_or_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-emit-this-value"
    monkeypatch.setenv("ACD_API_KEY", secret)

    def leak(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["dry-run"],
            returncode=0,
            stdout=secret,
            stderr=secret,
        )

    result = _execute(tmp_path / "journal.jsonl", run=leak)
    journal_text = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert secret not in journal_text
    assert secret not in json.dumps(result.payload.model_dump(mode="json"))
    assert secret not in result.result.receipt_id
