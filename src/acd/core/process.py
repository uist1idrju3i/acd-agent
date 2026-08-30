"""Adapter-boundary helper for external tool processes.

Every run is wrapped in a ToolEnvelope with input/output/config hashes and is
executed unconditionally: gates are re-run on every change. This module
performs no gate judgment.
"""

from __future__ import annotations

import hashlib
import math
import os
import platform
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from acd.schema import ToolEnvelope
from acd.schema.common import HashOrUnknown
from acd.schema.tool_envelope import ConvergenceState


class ExternalToolError(RuntimeError):
    """Raised when an external tool run cannot be trusted (fail-closed)."""


DEFAULT_TOOL_TIMEOUT_S: float = 600.0


class ToolTimeoutError(ExternalToolError):
    """Raised when an external tool exceeds its configured timeout."""

    def __init__(
        self,
        *,
        tool_name: str,
        timeout_s: float,
        stdout: str,
        stderr: str,
    ) -> None:
        self.tool_name = tool_name
        self.timeout_s = timeout_s
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"{tool_name} timed out after {timeout_s} seconds (fail-closed)")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


_CONTAINER_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


def _in_container() -> bool:
    """Return whether the current process has a container marker."""
    return Path("/.dockerenv").exists() or os.getenv("ACD_IN_CONTAINER", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def execution_env() -> str:
    """Describe the host and fail-closed container identity."""
    _, digest = execution_provenance()
    container = digest or "none"
    return f"{platform.system().lower()}-{platform.machine()}; container={container}"


def execution_provenance() -> tuple[Literal["container", "host", "unknown"], HashOrUnknown | None]:
    """Return typed execution context and optional container image digest."""
    digest = os.getenv("ACD_CONTAINER_IMAGE_DIGEST", "")
    if _in_container():
        if _CONTAINER_DIGEST.fullmatch(digest):
            return "container", digest
        return "container", "unknown"
    return "host", None


@dataclass(frozen=True)
class ToolRun:
    envelope: ToolEnvelope
    stdout: str
    stderr: str


def _hash_paths_with(
    paths: list[Path], normalizer: Callable[[Path], bytes] | None
) -> str:
    if normalizer is None:
        return sha256_paths(paths)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(b"\x00")
        digest.update(normalizer(path))
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def run_tool(
    *,
    tool_name: str,
    tool_version: str,
    format_version: str,
    command: list[str],
    input_paths: list[Path],
    output_paths: list[Path],
    envelope_path: Path,
    target_revision: str,
    measurement_conditions: str,
    convergence_state: ConvergenceState = "not_applicable",
    allowed_exit_codes: frozenset[int] = frozenset({0}),
    cwd: Path | None = None,
    timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
) -> ToolRun:
    """Run ``command`` and envelope the run."""
    try:
        valid_timeout = math.isfinite(timeout_s) and timeout_s > 0
    except (TypeError, ValueError):
        valid_timeout = False
    if not valid_timeout:
        raise ExternalToolError("tool timeout must be finite and positive")
    for path in input_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: input file missing: {path}")
    input_hash = sha256_paths(input_paths)
    config_hash = sha256_bytes("\x00".join(command).encode())

    started_at = datetime.now(UTC)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = datetime.now(UTC)
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr)
        context, digest = execution_provenance()
        envelope = ToolEnvelope(
            tool_name=tool_name,
            tool_version=tool_version,
            format_version=format_version,
            config_hash=config_hash,
            input_hash=input_hash,
            output_hash="unknown",
            execution_env=execution_env(),
            execution_context=context,
            container_image_digest=digest,
            measurement_conditions=measurement_conditions,
            convergence_state="timed_out",
            target_revision=target_revision,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=None,
            uncertainty=(
                f"tool timed out after {timeout_s} seconds; outputs not produced"
            ),
        )
        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        envelope_path.write_text(envelope.model_dump_json(indent=2) + "\n")
        raise ToolTimeoutError(
            tool_name=tool_name,
            timeout_s=timeout_s,
            stdout=stdout,
            stderr=stderr,
        ) from exc
    finished_at = datetime.now(UTC)
    if result.returncode not in allowed_exit_codes:
        raise ExternalToolError(
            f"{tool_name} exited with {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    for path in output_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: expected output missing: {path}")

    context, digest = execution_provenance()
    envelope = ToolEnvelope(
        tool_name=tool_name,
        tool_version=tool_version,
        format_version=format_version,
        config_hash=config_hash,
        input_hash=input_hash,
        output_hash=sha256_paths(output_paths),
        execution_env=execution_env(),
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions=measurement_conditions,
        convergence_state=convergence_state,
        target_revision=target_revision,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=result.returncode,
    )
    envelope_path.parent.mkdir(parents=True, exist_ok=True)
    envelope_path.write_text(envelope.model_dump_json(indent=2) + "\n")
    return ToolRun(envelope=envelope, stdout=result.stdout, stderr=result.stderr)


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def run_in_process(
    *,
    tool_name: str,
    tool_version: str,
    format_version: str,
    input_paths: list[Path],
    output_paths: list[Path],
    envelope_path: Path,
    target_revision: str,
    measurement_conditions: str,
    runner: Callable[[], None],
    config: bytes,
    output_normalizer: Callable[[Path], bytes] | None = None,
) -> ToolRun:
    """Run an in-process projection and envelope the run."""
    for path in input_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: input file missing: {path}")
    input_hash = sha256_paths(input_paths)
    config_hash = sha256_bytes(config)
    started_at = datetime.now(UTC)
    runner()
    finished_at = datetime.now(UTC)
    for path in output_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: expected output missing: {path}")
    context, digest = execution_provenance()
    envelope = ToolEnvelope(
        tool_name=tool_name,
        tool_version=tool_version,
        format_version=format_version,
        config_hash=config_hash,
        input_hash=input_hash,
        output_hash=_hash_paths_with(output_paths, output_normalizer),
        execution_env=execution_env(),
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions=measurement_conditions,
        convergence_state="converged",
        target_revision=target_revision,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=0,
    )
    envelope_path.parent.mkdir(parents=True, exist_ok=True)
    envelope_path.write_text(envelope.model_dump_json(indent=2) + "\n")
    return ToolRun(envelope=envelope, stdout="", stderr="")
