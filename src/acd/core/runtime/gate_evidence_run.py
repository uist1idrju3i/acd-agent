"""Load external gate evidence using the shared fail-closed contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from acd.core.runtime.fileio import read_json
from acd.schema.salvage import GateRun

GateStatus = Literal["pass", "fail", "unknown", "not_applicable"]


def external_gate_run(gate: str, path: Path | None, revision: str) -> GateRun:
    """Load one gate evidence file, returning unknown for invalid input."""
    if path is None:
        return GateRun(
            gate=gate,
            status="unknown",
            source="missing",
            detail=f"{gate} evidence is missing",
        )
    try:
        payload = read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence could not be read: {exc}",
            evidence_path=str(path),
        )
    if not isinstance(payload, dict):
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence is not an object",
            evidence_path=str(path),
        )
    body = cast(dict[str, Any], payload)
    if body.get("target_revision") != revision:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence revision does not match {revision}",
            evidence_path=str(path),
        )
    if body.get("gate") != gate:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence declares a different gate",
            evidence_path=str(path),
        )
    status = body.get("status")
    if status not in {"pass", "fail", "unknown", "not_applicable"}:
        return GateRun(
            gate=gate,
            status="unknown",
            source="evidence_file",
            detail=f"{gate} evidence has an invalid status",
            evidence_path=str(path),
        )
    message = body.get("message")
    detail = message if isinstance(message, str) and message else f"{gate} evidence loaded"
    return GateRun(
        gate=gate,
        status=cast(GateStatus, status),
        source="evidence_file",
        detail=detail,
        evidence_path=str(path),
    )


__all__ = ["external_gate_run"]
