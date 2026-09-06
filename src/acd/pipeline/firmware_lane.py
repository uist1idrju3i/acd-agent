"""Run the virtual firmware lane as a subprocess and record its Evidence.

The firmware Skill CLI only builds and runs the virtual image; it never
produces an Evidence record itself. This module owns the subprocess invocation
plus the deterministic Evidence write so both ``design_loop`` and the
standalone lane runner emit ``evidence-firmware.json`` through one path. Every
failure is fail-closed and reported as :class:`FirmwareLaneError`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from acd.pipeline.firmware_evidence import write_firmware_evidence
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence

FIRMWARE_LANE_TIMEOUT_SECONDS = 3600


class FirmwareLaneError(RuntimeError):
    """The firmware lane failed; the message is the failure reason."""

    def __init__(self, reason: str, *, output_path: Path | None = None) -> None:
        super().__init__(reason)
        self.output_path = output_path


@dataclass(frozen=True)
class FirmwareLaneResult:
    """Outcome of one successful firmware lane run."""

    output_path: Path
    summary: dict[str, Any]
    evidence_path: Path
    evidence: Evidence
    script_sha256: str
    script_path: Path


def firmware_script_path(repository: Path) -> Path:
    """Return the firmware Skill pipeline script inside the repository."""
    return (
        repository
        / "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py"
    )


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def run_firmware_lane(
    repository: Path,
    fixture_dir: Path,
    output: Path,
    *,
    run_seconds: int,
) -> FirmwareLaneResult:
    """Run the firmware Skill and write ``evidence-firmware.json``.

    Raises ``FirmwareLaneError`` on a missing script, a non-positive
    ``run_seconds``, a non-zero Skill exit, an invalid summary, or an
    Evidence write failure.
    """
    script = firmware_script_path(repository)
    if not script.is_file():
        raise FirmwareLaneError(f"firmware Skill script is missing: {script}")
    if run_seconds <= 0:
        raise FirmwareLaneError("run_seconds must be positive")
    started_at = datetime.now(UTC)
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(script),
            "--fixture",
            str(fixture_dir),
            "--out",
            str(output),
            "--run-seconds",
            str(run_seconds),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=FIRMWARE_LANE_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise FirmwareLaneError(
            completed.stderr.strip()
            or f"firmware Skill exited with code {completed.returncode}",
            output_path=output,
        )
    summary_path = output / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FirmwareLaneError(
            f"firmware Skill summary is invalid: {exc}"
        ) from exc
    if not isinstance(summary, dict):
        raise FirmwareLaneError("firmware Skill summary must be an object")
    script_sha256 = _file_sha256(script)
    try:
        graph = DesignGraph.model_validate_json(
            (fixture_dir / "graph.json").read_text(encoding="utf-8")
        )
        evidence_path, evidence = write_firmware_evidence(
            graph,
            cast(dict[str, Any], summary),
            output,
            graph_path=fixture_dir / "graph.json",
            script_sha256=script_sha256,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
    except (OSError, ValueError) as exc:
        raise FirmwareLaneError(
            f"firmware Evidence could not be recorded: {exc}",
            output_path=output,
        ) from exc
    return FirmwareLaneResult(
        output_path=output,
        summary=cast(dict[str, Any], summary),
        evidence_path=evidence_path,
        evidence=evidence,
        script_sha256=script_sha256,
        script_path=script,
    )
