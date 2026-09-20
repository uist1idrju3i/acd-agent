"""Fail-closed KiCad board STEP export."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from acd.core.mechanical.cad_normalize import normalize_step
from acd.core.runtime.fileio import read_json
from acd.core.runtime.process import ExternalToolError, run_tool, sha256_bytes


@dataclass(frozen=True)
class StepExportRecord:
    status: Literal["pass", "unknown"]
    pcb_sha256: str
    model_directory_sha256: str
    kicad_version: str | None
    output_step_sha256: str | None
    error: str | None = None
    envelope_path: Path | None = None


def _expected_version() -> str | None:
    lock_path = Path(__file__).resolve().parents[4] / "docker" / "image-digests.json"
    try:
        lock = read_json(lock_path)
        value = lock["acd_tools"]["tools"]["kicad-cli"]
    except (KeyError, OSError, TypeError, ValueError):
        return None
    match = re.search(r"\d+\.\d+\.\d+", str(value))
    return match.group(0) if match else None


def _model_directory_hash(models_dir: Path) -> str:
    paths = sorted(
        path
        for path in models_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".step", ".stp", ".wrl"}
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(models_dir).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def _version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError("kicad-cli is unavailable") from exc
    match = re.search(r"\d+\.\d+\.\d+", result.stdout.strip())
    if result.returncode != 0 or match is None:
        raise ExternalToolError("kicad-cli version probe failed")
    return match.group(0)


def export_board_step(
    pcb_path: Path,
    out_step: Path,
    *,
    kicad_cli: str,
    models_dir: Path,
) -> StepExportRecord:
    """Export a board without tracks, returning unknown instead of raising."""
    pcb_sha256 = sha256_bytes(pcb_path.read_bytes()) if pcb_path.is_file() else "unknown"
    version: str | None = None
    try:
        model_hash = _model_directory_hash(models_dir)
    except OSError:
        model_hash = "unknown"
    envelope_path = out_step.with_suffix(out_step.suffix + ".envelope.json")
    try:
        if not pcb_path.is_file():
            raise ExternalToolError("PCB input is missing")
        if not models_dir.is_dir():
            raise ExternalToolError("KiCad model directory is missing")
        version = _version(kicad_cli)
        expected = _expected_version()
        if expected is None or version != expected:
            raise ExternalToolError(
                f"KiCad version mismatch: measured {version}, expected {expected}"
            )
        run_tool(
            tool_name="kicad-cli",
            tool_version=version,
            format_version=version,
            command=[
                kicad_cli,
                "pcb",
                "export",
                "step",
                "--subst-models",
                "--no-dnp",
                "--output",
                str(out_step),
                str(pcb_path),
            ],
            input_paths=[pcb_path],
            output_paths=[out_step],
            envelope_path=envelope_path,
            target_revision="component-3d",
            measurement_conditions=f"KiCad model directory: {models_dir}",
        )
        if out_step.stat().st_size == 0:
            raise ExternalToolError("KiCad exported an empty STEP")
        output_hash = sha256_bytes(normalize_step(out_step.read_bytes()))
        return StepExportRecord(
            status="pass",
            pcb_sha256=pcb_sha256,
            model_directory_sha256=model_hash,
            kicad_version=version,
            output_step_sha256=output_hash,
            envelope_path=envelope_path,
        )
    except Exception as exc:
        return StepExportRecord(
            status="unknown",
            pcb_sha256=pcb_sha256,
            model_directory_sha256=model_hash,
            kicad_version=version,
            output_step_sha256=None,
            error=str(exc),
            envelope_path=envelope_path,
        )
