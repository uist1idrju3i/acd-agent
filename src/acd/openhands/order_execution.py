"""Fail-closed dry-run order execution at the OpenHands boundary."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from openhands.sdk.conversation.secret_registry import SecretRegistry
from openhands.sdk.hooks import HookConfig
from openhands.sdk.security.confirmation_policy import (
    ConfirmationPolicyBase,
    ConfirmRisky,
)
from openhands.sdk.security.risk import SecurityRisk

from acd.core.order_execution import build_dry_run_order_payload
from acd.core.side_effect_journal import (
    SideEffectJournalError,
    append_post_order,
    append_pre_order,
)
from acd.openhands.safety.hooks import validate_acd_hook_config
from acd.openhands.safety.secrets import (
    ACD_SECRET_ENV_VARS,
    build_acd_secret_mapping,
)
from acd.schema import (
    DryRunOrderPayload,
    ExecutionMode,
    JournalResultStatus,
    PostOrderJournalEntry,
    PreOrderGateRecord,
    PreOrderJournalEntry,
    dry_run_payload_hash,
)
from acd.schema.common import (
    IdempotencyKey,
    NonEmptyStr,
    Revision,
    Sha256,
    Timestamp,
    canonical_json_sha256,
)
from acd.schema.quote import QuoteAmount


class OrderExecutionError(ValueError):
    """Raised when an order execution cannot safely complete."""


@dataclass(frozen=True)
class DryRunOrderResult:
    """The non-authoritative result of one dry-run order execution."""

    payload: DryRunOrderPayload
    payload_hash: Sha256
    planned: PreOrderJournalEntry
    result: PostOrderJournalEntry


def default_confirmation_policy() -> ConfirmationPolicyBase:
    """Return the repository's confirmation policy for order dry-runs."""
    return ConfirmRisky(threshold=SecurityRisk.MEDIUM)


def load_order_hooks(path: Path) -> HookConfig:
    """Load the SDK hook configuration used by order execution."""
    try:
        return HookConfig.load(path)
    except (OSError, TypeError, ValueError) as exc:
        raise OrderExecutionError("order execution hooks could not be loaded") from exc


def _validate_confirmation_policy(
    policy: ConfirmationPolicyBase | None,
) -> None:
    if policy is None:
        raise OrderExecutionError("confirmation policy is required")
    try:
        confirms_medium = policy.should_confirm(SecurityRisk.MEDIUM)
        confirms_high = policy.should_confirm(SecurityRisk.HIGH)
    except (TypeError, ValueError) as exc:
        raise OrderExecutionError("confirmation policy could not be evaluated") from exc
    if not confirms_medium or not confirms_high:
        raise OrderExecutionError(
            "confirmation policy must require medium and high-risk confirmation"
        )


def _build_secret_registry() -> SecretRegistry:
    registry = SecretRegistry()
    registry.update_secrets(build_acd_secret_mapping())
    return registry


def _validate_secret_reference(
    secret_name: str,
) -> None:
    if secret_name not in ACD_SECRET_ENV_VARS:
        raise OrderExecutionError(
            "provider credential must be an allowlisted SecretRegistry name"
        )


def _validate_runtime_limit_override(
    runtime_upper_limit: QuoteAmount | None,
) -> None:
    if runtime_upper_limit is not None or "ACD_ORDER_TOTAL_LIMIT" in os.environ:
        raise OrderExecutionError(
            "runtime order-policy upper-limit override is not permitted"
        )


def _validate_dry_run_command(
    *,
    command: Sequence[str],
    registry: SecretRegistry,
) -> None:
    if not command or any(not argument for argument in command):
        raise OrderExecutionError("dry-run command must not be empty")
    command_text = " ".join(command)
    secret_values = registry.get_all_secrets_as_env_vars()
    if any(value and value in command_text for value in secret_values.values()):
        raise OrderExecutionError("provider credential value must not be a command argument")


def _run_dry_run_command(
    *,
    command: Sequence[str],
    registry: SecretRegistry,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[int, str, str]:
    command_text = " ".join(command)
    secret_env = registry.get_secrets_as_env_vars(command_text)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ACD_SECRET_ENV_VARS
    }
    environment.update(secret_env)
    try:
        completed = run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        raise OrderExecutionError("dry-run subprocess could not start") from exc
    masked_stdout = registry.mask_secrets_in_output(completed.stdout)
    masked_stderr = registry.mask_secrets_in_output(completed.stderr)
    return completed.returncode, masked_stdout, masked_stderr


def _receipt(
    *,
    payload_hash: Sha256,
    exit_code: int,
    stdout: str,
    stderr: str,
    status: JournalResultStatus,
) -> tuple[NonEmptyStr, Sha256]:
    receipt_hash = canonical_json_sha256(
        {
            "execution_mode": "dry_run",
            "exit_code": exit_code,
            "payload_hash": payload_hash,
            "result_status": status,
            "stderr": stderr,
            "stdout": stdout,
        }
    )
    return f"dry-run:{receipt_hash.removeprefix('sha256:')}", receipt_hash


def execute_order(
    *,
    authorization: PreOrderGateRecord,
    journal_path: Path,
    idempotency_key: IdempotencyKey,
    package_hash: Sha256,
    destination: NonEmptyStr,
    target_revision: Revision,
    provider_credential_reference: str,
    confirmation_policy: ConfirmationPolicyBase | None,
    hook_config: HookConfig | None,
    occurred_at: Timestamp,
    execution_mode: ExecutionMode = "dry_run",
    runtime_upper_limit: QuoteAmount | None = None,
    command: Sequence[str],
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DryRunOrderResult:
    """Record and execute one deterministic dry-run order attempt."""
    if execution_mode not in ("dry_run", "real"):
        raise OrderExecutionError("unsupported order execution mode")
    if execution_mode == "real":
        raise OrderExecutionError(
            "real provider order execution is not enabled in this milestone"
        )
    if authorization.target_revision != target_revision:
        raise OrderExecutionError("authorization revision does not match order revision")
    _validate_runtime_limit_override(runtime_upper_limit)
    _validate_confirmation_policy(confirmation_policy)
    if hook_config is None:
        raise OrderExecutionError("required ACD hooks are not declared")
    try:
        validate_acd_hook_config(hook_config)
    except (TypeError, ValueError) as exc:
        raise OrderExecutionError("required ACD hooks are not declared") from exc
    registry = _build_secret_registry()
    _validate_secret_reference(provider_credential_reference)
    _validate_dry_run_command(command=command, registry=registry)
    payload = build_dry_run_order_payload(
        authorization=authorization,
        package_hash=package_hash,
        destination=destination,
    )
    payload_hash = dry_run_payload_hash(payload)
    try:
        planned = append_pre_order(
            journal_path,
            authorization=authorization,
            execution_mode="dry_run",
            package_hash=package_hash,
            destination=destination,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )
    except (OSError, SideEffectJournalError, ValueError) as exc:
        raise OrderExecutionError("pre-order journal append failed") from exc

    execution_error: OrderExecutionError | None = None
    try:
        exit_code, stdout, stderr = _run_dry_run_command(
            command=command,
            registry=registry,
            run=run,
        )
    except OrderExecutionError as exc:
        execution_error = exc
        exit_code, stdout, stderr = 1, "", "dry-run subprocess could not start"
    status: JournalResultStatus = "success" if exit_code == 0 else "failure"
    receipt_id, receipt_hash = _receipt(
        payload_hash=payload_hash,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        status=status,
    )
    try:
        result = append_post_order(
            journal_path,
            planned=planned,
            execution_mode="dry_run",
            result_status=status,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            occurred_at=occurred_at,
        )
    except (OSError, SideEffectJournalError, ValueError) as exc:
        raise OrderExecutionError("post-order journal append failed") from exc
    if exit_code != 0:
        if execution_error is not None:
            raise execution_error
        raise OrderExecutionError(
            f"dry-run subprocess failed with exit code {exit_code}"
        )
    return DryRunOrderResult(
        payload=payload,
        payload_hash=payload_hash,
        planned=planned,
        result=result,
    )


__all__ = [
    "DryRunOrderResult",
    "OrderExecutionError",
    "default_confirmation_policy",
    "execute_order",
    "load_order_hooks",
]
