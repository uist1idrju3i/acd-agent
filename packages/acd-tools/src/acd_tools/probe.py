"""External tool capability probes.

Each probe detects presence and version of one external tool. Absence or an
unparsable version is recorded as ``unknown`` — never as a success — so the
result can gate session start and evidence validity (fail-closed).

Output determinism measurements are not part of the probe: they live in the
``acd-cad-determinism-probe`` skill under ``plugins/acd/skills/``.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import re
import shutil
import subprocess
from collections.abc import Callable

from pydantic import Field

from acd_schema import AcdModel
from acd_schema.common import NonEmptyStr


class ToolProbeResult(AcdModel):
    """Structured result of probing one external tool."""

    tool_name: NonEmptyStr
    present: bool
    version: NonEmptyStr  # concrete version or "unknown"
    path: str | None = None
    detail: str = ""

    @property
    def is_known(self) -> bool:
        return self.present and self.version != "unknown"


def _run_version_command(
    executable: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unknown", f"version command failed: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    match = re.search(version_pattern, output)
    exit_ok = completed.returncode == 0 or allow_nonzero_exit
    if not exit_ok or match is None:
        return "unknown", f"unparsable version output (exit={completed.returncode})"
    return match.group(1), f"version detected (exit={completed.returncode})"


def probe_executable(
    tool_name: str,
    executable: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> ToolProbeResult:
    path = shutil.which(executable)
    if path is None:
        return ToolProbeResult(
            tool_name=tool_name,
            present=False,
            version="unknown",
            path=None,
            detail="executable not found on PATH",
        )
    version, detail = _run_version_command(
        path, args, version_pattern, allow_nonzero_exit=allow_nonzero_exit
    )
    return ToolProbeResult(
        tool_name=tool_name, present=True, version=version, path=path, detail=detail
    )


def probe_kicad_cli() -> ToolProbeResult:
    return probe_executable("kicad-cli", "kicad-cli", ["version"], r"([0-9]+\.[0-9]+\.[0-9]+)")


def probe_freerouting() -> ToolProbeResult:
    # freerouting v2 prints its version banner but exits nonzero when invoked
    # without an input/output pair, so a nonzero exit is tolerated here as long
    # as the banner is parsable.
    return probe_executable(
        "freerouting",
        "freerouting",
        ["--version"],
        r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)",
        allow_nonzero_exit=True,
    )


def probe_cad_kernel() -> ToolProbeResult:
    """Probe the Python CAD kernel (build123d on OCP) without requiring it."""
    versions: dict[str, str] = {}
    for dist_name in ("build123d", "cadquery-ocp"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            versions[dist_name] = importlib.metadata.version(dist_name)
    if not versions:
        return ToolProbeResult(
            tool_name="cad-kernel",
            present=False,
            version="unknown",
            path=None,
            detail="no CAD kernel distribution installed (build123d / cadquery-ocp)",
        )
    return ToolProbeResult(
        tool_name="cad-kernel",
        present=True,
        version=versions.get("build123d", versions["cadquery-ocp"]),
        path=None,
        detail="python distributions " + ", ".join(f"{k}={v}" for k, v in versions.items()),
    )


PROBES: dict[str, Callable[[], ToolProbeResult]] = {
    "kicad-cli": probe_kicad_cli,
    "freerouting": probe_freerouting,
    "cad-kernel": probe_cad_kernel,
}


class ProbeReport(AcdModel):
    results: list[ToolProbeResult] = Field(default_factory=list[ToolProbeResult])

    def versions(self) -> dict[str, str]:
        """Tool-name to version map for SessionStart validation."""
        return {result.tool_name: result.version for result in self.results}


def probe_all() -> ProbeReport:
    return ProbeReport(results=[probe() for probe in PROBES.values()])
