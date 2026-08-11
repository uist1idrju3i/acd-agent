"""Adapter-boundary helper for external tool processes.

Every external run is wrapped in a ToolEnvelope with input/output/config
hashes. Reruns with identical input, config, and tool version are skipped
when a matching envelope and intact outputs already exist, so side effects
are never duplicated. This module performs no gate judgment.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from acd_schema import ToolEnvelope
from acd_schema.tool_envelope import ConvergenceState


class ExternalToolError(RuntimeError):
    """Raised when an external tool run cannot be trusted (fail-closed)."""


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


def execution_env() -> str:
    return f"{platform.system().lower()}-{platform.machine()}; container=none"


@dataclass(frozen=True)
class ToolRun:
    envelope: ToolEnvelope
    stdout: str
    stderr: str
    skipped: bool


def _load_previous(envelope_path: Path) -> ToolEnvelope | None:
    if not envelope_path.is_file():
        return None
    try:
        return ToolEnvelope.model_validate(json.loads(envelope_path.read_text()))
    except ValueError:
        return None


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
) -> ToolRun:
    """Run ``command`` once per (input, config, tool version) and envelope it."""
    for path in input_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: input file missing: {path}")
    input_hash = sha256_paths(input_paths)
    config_hash = sha256_bytes("\x00".join(command).encode())

    previous = _load_previous(envelope_path)
    if (
        previous is not None
        and previous.tool_name == tool_name
        and previous.tool_version == tool_version
        and previous.input_hash == input_hash
        and previous.config_hash == config_hash
        and all(p.is_file() for p in output_paths)
        and previous.output_hash == sha256_paths(output_paths)
    ):
        return ToolRun(envelope=previous, stdout="", stderr="", skipped=True)

    started_at = datetime.now(UTC)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        timeout=600,
    )
    finished_at = datetime.now(UTC)
    if result.returncode not in allowed_exit_codes:
        raise ExternalToolError(
            f"{tool_name} exited with {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    for path in output_paths:
        if not path.is_file():
            raise ExternalToolError(f"{tool_name}: expected output missing: {path}")

    envelope = ToolEnvelope(
        tool_name=tool_name,
        tool_version=tool_version,
        format_version=format_version,
        config_hash=config_hash,
        input_hash=input_hash,
        output_hash=sha256_paths(output_paths),
        execution_env=execution_env(),
        measurement_conditions=measurement_conditions,
        convergence_state=convergence_state,
        target_revision=target_revision,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=result.returncode,
    )
    envelope_path.parent.mkdir(parents=True, exist_ok=True)
    envelope_path.write_text(envelope.model_dump_json(indent=2) + "\n")
    return ToolRun(envelope=envelope, stdout=result.stdout, stderr=result.stderr, skipped=False)
