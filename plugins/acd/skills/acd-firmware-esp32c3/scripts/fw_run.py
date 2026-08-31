"""Minimal, self-contained process helpers for the firmware skill.

The skill deliberately does not depend on ACD gate infrastructure: firmware
build, analysis and test execution belong to the agent's normal software
development capability. These helpers only make runs reproducible enough to
compare hashes between reruns.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CommandFailedError(RuntimeError):
    """Raised when an external command exits with an unexpected status."""


def resolve_tool(binary: str) -> str | None:
    """Find a tool on PATH, falling back to the exported ESP-IDF environment.

    ESP-IDF installs its own tools (QEMU included) outside PATH; they only
    become visible after sourcing ``export.sh``.
    """
    found = shutil.which(binary)
    if found is not None:
        return found
    idf_path = os.environ.get("IDF_PATH")
    if idf_path is None:
        return None
    export = Path(idf_path) / "export.sh"
    if not export.is_file():
        return None
    result = subprocess.run(
        ["bash", "-c", f". {shlex.quote(str(export))} >/dev/null && command -v {binary}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=300,
    )
    path = result.stdout.strip()
    return path if result.returncode == 0 and path else None


def sha256_paths(paths: list[Path]) -> str:
    """Hash file contents in the given order, prefixed with each file name."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True)
class CommandRecord:
    command: list[str]
    tool_version: str
    exit_code: int
    input_hash: str
    output_hash: str


def run_command(
    command: list[str],
    *,
    tool_version: str,
    input_paths: list[Path],
    output_paths: list[Path],
    cwd: Path | None = None,
    allowed_exit_codes: frozenset[int] = frozenset({0}),
    timeout: int = 1800,
) -> CommandRecord:
    input_hash = sha256_paths(input_paths)
    result = subprocess.run(command, cwd=cwd, check=False, timeout=timeout)
    if result.returncode not in allowed_exit_codes:
        raise CommandFailedError(
            f"command exited with {result.returncode}: {shlex.join(command)}"
        )
    missing = [str(path) for path in output_paths if not path.is_file()]
    if missing:
        raise CommandFailedError(f"expected outputs missing: {missing}")
    return CommandRecord(
        command=command,
        tool_version=tool_version,
        exit_code=result.returncode,
        input_hash=input_hash,
        output_hash=sha256_paths(output_paths),
    )
