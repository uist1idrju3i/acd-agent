"""External freerouting invocation (DSN in, SES out) with a tool envelope.

The router is a proposal generator: its output is only trusted after the
SES is re-imported and the resulting board passes KiCad DRC. Convergence is
read from the router's own completion report; anything unparsable stays
``unknown`` and can never support a pass verdict.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from acd.core.process import ExternalToolError, ToolRun, run_tool
from acd.schema.tool_envelope import ConvergenceState


class RouterUnavailableError(ExternalToolError):
    """Raised when no usable router is present (fail-closed)."""


_VERSION_PATTERN = re.compile(r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)")


class FreeroutingRunner:
    def __init__(self, executable: str = "freerouting") -> None:
        self.executable = executable
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            path = shutil.which(self.executable)
            if path is None:
                raise RouterUnavailableError(
                    f"router executable {self.executable!r} not found (fail-closed)"
                )
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            match = _VERSION_PATTERN.search(result.stdout + result.stderr)
            if match is None:
                raise RouterUnavailableError("router version banner unparsable (fail-closed)")
            self._version = match.group(1)
        version = self._version
        if version is None:
            raise RouterUnavailableError("router version unknown (fail-closed)")
        return version

    def route(
        self,
        dsn_path: Path,
        ses_path: Path,
        target_revision: str,
        max_passes: int = 100,
    ) -> ToolRun:
        version = self.version()
        command = [
            self.executable,
            "-de",
            str(dsn_path),
            "-do",
            str(ses_path),
            "-mp",
            str(max_passes),
        ]
        run = run_tool(
            tool_name="freerouting",
            tool_version=version,
            format_version="specctra-dsn/ses",
            command=command,
            input_paths=[dsn_path],
            output_paths=[ses_path],
            envelope_path=ses_path.with_suffix(ses_path.suffix + ".envelope.json"),
            target_revision=target_revision,
            measurement_conditions=f"headless; max {max_passes} passes",
            convergence_state="unknown",
        )
        convergence = _convergence_from_log(run.stdout + run.stderr)
        envelope = run.envelope.model_copy(update={"convergence_state": convergence})
        envelope_path = ses_path.with_suffix(ses_path.suffix + ".envelope.json")
        envelope_path.write_text(envelope.model_dump_json(indent=2) + "\n")
        return ToolRun(envelope=envelope, stdout=run.stdout, stderr=run.stderr)


def _convergence_from_log(log: str) -> ConvergenceState:
    matches = re.findall(r"\(([0-9]+) unrouted", log)
    if not matches:
        return "unknown"
    return "converged" if int(matches[-1]) == 0 else "not_converged"
