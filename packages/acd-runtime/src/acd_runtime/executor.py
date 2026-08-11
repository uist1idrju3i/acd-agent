"""Common executor skeleton: every external tool run yields a ToolEnvelope.

This is the single enforcement point for the tool-envelope contract. The
Phase 0 skeleton runs a caller-provided function over byte inputs and wraps
the result; real adapters (kicad-cli, freerouting, CAD kernel) plug in later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from acd_schema import ToolEnvelope
from acd_schema.tool_envelope import ConvergenceState


def sha256_of(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def run_enveloped(
    *,
    tool_name: str,
    tool_version: str,
    format_version: str,
    config: bytes | None,
    input_data: bytes,
    target_revision: str,
    execution_env: str,
    measurement_conditions: str,
    runner: Callable[[bytes], tuple[bytes, int, ConvergenceState]],
    idempotency_key: str | None = None,
) -> tuple[bytes, ToolEnvelope]:
    """Run ``runner`` over ``input_data`` and return output plus its envelope.

    Hashes are computed from the exact bytes passed in and out; a missing
    config is recorded as ``unknown`` (which keeps the envelope out of any
    pass verdict) rather than being silently defaulted.
    """
    started_at = datetime.now(UTC)
    output, exit_code, convergence_state = runner(input_data)
    finished_at = datetime.now(UTC)
    envelope = ToolEnvelope(
        tool_name=tool_name,
        tool_version=tool_version,
        format_version=format_version,
        config_hash=sha256_of(config) if config is not None else "unknown",
        input_hash=sha256_of(input_data),
        output_hash=sha256_of(output),
        execution_env=execution_env,
        measurement_conditions=measurement_conditions,
        convergence_state=convergence_state,
        target_revision=target_revision,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        idempotency_key=idempotency_key,
    )
    return output, envelope
