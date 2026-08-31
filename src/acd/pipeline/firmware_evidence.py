"""Authoritative Evidence for the virtual firmware lane.

The firmware Skill runs as a subprocess and never produces Evidence itself.
This module turns its hashed summary into one deterministic Evidence record
whose envelope carries the execution provenance of the current process, so a
digest-pinned container run yields authoritative Evidence while a host run
stays provisional. The record always states that execution was virtual (QEMU)
and is never promoted to real-device measurement Evidence: real-device claims
require ``PhysicalEvidence`` with ``measurement_class="measured"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acd.core.naming import evidence_id, subject_node_id
from acd.core.process import (
    execution_env,
    execution_provenance,
    sha256_bytes,
    sha256_paths,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim
from acd.schema.tool_envelope import ToolEnvelope

FIRMWARE_EVIDENCE_FILENAME = "evidence-firmware.json"
FIRMWARE_EVIDENCE_LANE = "firmware-virtual"
_REQUIRED_SUMMARY_KEYS = (
    "target_revision",
    "toolchain_version",
    "source_hash",
    "artifact_hash",
    "qemu_version",
    "measurement_conditions",
    "virtual_run_termination",
    "virtual_log",
)


class FirmwareEvidenceError(ValueError):
    """Raised when firmware Evidence cannot be derived from the Skill summary."""


def _required_text(summary: dict[str, Any], key: str) -> str:
    value = summary.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FirmwareEvidenceError(
            f"firmware Skill summary has no usable {key!r} value"
        )
    return value


def build_firmware_evidence(
    graph: DesignGraph,
    summary: dict[str, Any],
    out_dir: Path,
    *,
    script_sha256: str,
    started_at: datetime,
    finished_at: datetime,
) -> Evidence:
    """Return the firmware-lane Evidence derived from one Skill summary."""
    missing = [key for key in _REQUIRED_SUMMARY_KEYS if key not in summary]
    if missing:
        raise FirmwareEvidenceError(
            f"firmware Skill summary is missing required keys: {sorted(missing)}"
        )
    target_revision = _required_text(summary, "target_revision")
    if target_revision != graph.revision:
        raise FirmwareEvidenceError(
            "firmware Skill summary revision does not match the graph revision "
            f"({target_revision!r} != {graph.revision!r})"
        )
    virtual_log = Path(_required_text(summary, "virtual_log"))
    if not virtual_log.is_file():
        raise FirmwareEvidenceError(f"virtual serial log is missing: {virtual_log}")
    summary_path = out_dir / "summary.json"
    if not summary_path.is_file():
        raise FirmwareEvidenceError(f"firmware Skill summary is missing: {summary_path}")
    graph_path = out_dir.parent / "graph.json"
    conditions = _required_text(summary, "measurement_conditions")
    termination = _required_text(summary, "virtual_run_termination")
    context, digest = execution_provenance()
    envelope = ToolEnvelope(
        tool_name="acd-firmware-esp32c3",
        tool_version=_required_text(summary, "qemu_version"),
        format_version="0.1",
        config_hash=sha256_bytes(script_sha256.encode()),
        input_hash=(
            sha256_paths([graph_path]) if graph_path.is_file() else "unknown"
        ),
        output_hash=sha256_paths([summary_path, virtual_log]),
        execution_env=execution_env(),
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions=f"{conditions}; virtual run {termination}",
        convergence_state="converged",
        target_revision=graph.revision,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=0,
    )
    subject_node = subject_node_id(graph, "firmware.module")
    claims = [
        EvidenceClaim(
            subject_node=subject_node,
            property="measurement_class",
            value="virtual",
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="real_device_measurement",
            value=False,
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="virtual_target",
            value="qemu-esp32c3",
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="virtual_run_termination",
            value=termination,
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="toolchain_version",
            value=_required_text(summary, "toolchain_version"),
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="firmware_source_hash",
            value=_required_text(summary, "source_hash"),
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="firmware_artifact_hash",
            value=_required_text(summary, "artifact_hash"),
            verified=True,
        ),
        EvidenceClaim(
            subject_node=subject_node,
            property="firmware_skill_script_sha256",
            value=script_sha256,
            verified=True,
        ),
    ]
    return Evidence(
        evidence_id=evidence_id(graph.graph_id, FIRMWARE_EVIDENCE_LANE),
        target_revision=graph.revision,
        status="valid",
        envelope=envelope,
        claims=claims,
        created_at=datetime.now(UTC),
    )


def write_firmware_evidence(
    graph: DesignGraph,
    summary: dict[str, Any],
    out_dir: Path,
    *,
    script_sha256: str,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[Path, Evidence]:
    """Write the firmware-lane Evidence next to the Skill outputs."""
    evidence = build_firmware_evidence(
        graph,
        summary,
        out_dir,
        script_sha256=script_sha256,
        started_at=started_at,
        finished_at=finished_at,
    )
    path = out_dir / FIRMWARE_EVIDENCE_FILENAME
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path, evidence
