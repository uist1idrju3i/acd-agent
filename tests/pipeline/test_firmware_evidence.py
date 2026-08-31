"""Firmware-lane virtual Evidence construction tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from acd.pipeline.firmware_evidence import (
    FirmwareEvidenceError,
    build_firmware_evidence,
    write_firmware_evidence,
)
from acd.schema.design_graph import DesignGraph

GRAPH_PATH = Path("fixtures/golden-design-1/graph.json")
SCRIPT_SHA256 = "sha256:" + "d" * 64


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _summary(out_dir: Path, graph: DesignGraph, **overrides: Any) -> dict[str, Any]:
    log_path = out_dir / "qemu-serial.log"
    log_path.write_text("boot ok\n", encoding="utf-8")
    value: dict[str, Any] = {
        "target_revision": graph.revision,
        "toolchain_version": "esp-idf v5.3",
        "source_hash": "sha256:" + "a" * 64,
        "artifact_hash": "sha256:" + "b" * 64,
        "qemu_version": "qemu-system-riscv32 8.2.0",
        "measurement_conditions": "virtual esp32c3 run, 15s bound",
        "virtual_run_termination": (
            "stopped by its own intended 15s timeout, which is the normal "
            "completion condition of the bounded virtual run"
        ),
        "virtual_log": str(log_path),
    }
    value.update(overrides)
    return value


def _out_dir(tmp_path: Path) -> Path:
    out_dir = tmp_path / "gd1-fw"
    out_dir.mkdir(parents=True)
    return out_dir


def _write_summary(out_dir: Path, summary: dict[str, Any]) -> None:
    (out_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _build(out_dir: Path, summary: dict[str, Any], graph: DesignGraph) -> Any:
    now = datetime.now(UTC)
    return build_firmware_evidence(
        graph,
        summary,
        out_dir,
        script_sha256=SCRIPT_SHA256,
        started_at=now,
        finished_at=now,
    )


def test_firmware_evidence_states_virtual_execution(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    _write_summary(out_dir, summary)

    evidence = _build(out_dir, summary, graph)

    assert evidence.target_revision == graph.revision
    assert evidence.status == "valid"
    claims = {claim.property: claim.value for claim in evidence.claims}
    assert claims["measurement_class"] == "virtual"
    assert claims["real_device_measurement"] is False
    assert claims["virtual_target"] == "qemu-esp32c3"
    assert claims["firmware_skill_script_sha256"] == SCRIPT_SHA256
    assert "virtual run" in evidence.envelope.measurement_conditions


def test_host_execution_stays_provisional(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    _write_summary(out_dir, summary)

    evidence = _build(out_dir, summary, graph)

    if evidence.envelope.execution_context != "container":
        assert evidence.supports_authoritative_pass(graph.revision) is False


def test_revision_mismatch_is_rejected(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph, target_revision="r-does-not-match")
    _write_summary(out_dir, summary)

    with pytest.raises(FirmwareEvidenceError, match="revision"):
        _build(out_dir, summary, graph)


def test_evidence_does_not_pass_for_another_revision(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    _write_summary(out_dir, summary)

    evidence = _build(out_dir, summary, graph)

    assert evidence.supports_authoritative_pass("r-other") is False


def test_missing_summary_keys_are_rejected(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    del summary["virtual_run_termination"]
    _write_summary(out_dir, summary)

    with pytest.raises(FirmwareEvidenceError, match="missing required keys"):
        _build(out_dir, summary, graph)


def test_malformed_summary_value_is_rejected(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph, toolchain_version="  ")
    _write_summary(out_dir, summary)

    with pytest.raises(FirmwareEvidenceError, match="toolchain_version"):
        _build(out_dir, summary, graph)


def test_missing_virtual_log_is_rejected(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    _write_summary(out_dir, summary)
    Path(summary["virtual_log"]).unlink()

    with pytest.raises(FirmwareEvidenceError, match="virtual serial log"):
        _build(out_dir, summary, graph)


def test_missing_skill_summary_file_is_rejected(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)

    with pytest.raises(FirmwareEvidenceError, match="summary is missing"):
        _build(out_dir, summary, graph)


def test_write_firmware_evidence_persists_record(tmp_path: Path) -> None:
    graph = _graph()
    out_dir = _out_dir(tmp_path)
    summary = _summary(out_dir, graph)
    _write_summary(out_dir, summary)
    now = datetime.now(UTC)

    path, evidence = write_firmware_evidence(
        graph,
        summary,
        out_dir,
        script_sha256=SCRIPT_SHA256,
        started_at=now,
        finished_at=now,
    )

    assert path == out_dir / "evidence-firmware.json"
    assert json.loads(path.read_text(encoding="utf-8"))["evidence_id"] == (
        evidence.evidence_id
    )
