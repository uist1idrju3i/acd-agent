"""Core resolution tests for lane artifact retention."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.lane_artifact_retention import (
    LaneArtifactRetentionError,
    load_lane_artifact_retention,
    resolve_lane_retention,
)
from acd.pipeline.lane_plan import build_lane_plan
from acd.schema.lane_artifact_retention import LaneArtifactRetentionDocument

CONTRACT_PATH = Path("contracts/lane-artifact-retention.json")


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_the_declared_contract() -> None:
    declaration = load_lane_artifact_retention()
    assert declaration.path.name == "lane-artifact-retention.json"
    assert declaration.declaration_hash.startswith("sha256:")
    assert declaration.lane("firmware-pipeline") is not None


def test_contract_declares_every_lane_runner_stage_with_output() -> None:
    declaration = load_lane_artifact_retention()
    declared = {lane.lane_id for lane in declaration.document.lanes}
    # pytest-subset is a lane runner stage without an output path.
    for graph_id in ("golden-design-1",):
        plan = build_lane_plan(graph_id, Path("out"))
        expected = {
            stage.stage_id
            for stage in plan.lane_runner_stages
            if stage.output_path is not None
        }
    assert declared == expected


def test_resolution_reports_retained_missing_and_regenerable(tmp_path: Path) -> None:
    output = tmp_path / "gd1-fw"
    _write(output / "summary.json")
    _write(output / "evidence-firmware.json")
    _write(output / "firmware-coverage.json")
    _write(output / "firmware-config-report.json")
    _write(output / "flash.bin", "flash")
    _write(output / "qemu-serial.log", "serial")
    _write(output / "gd1_fw" / "CMakeLists.txt")
    _write(output / "gd1_fw" / "sdkconfig.defaults")
    _write(output / "gd1_fw" / "main" / "acd_main.c", "int main;")
    _write(output / "gd1_fw" / "main" / "acd_pins.h")
    _write(output / "gd1_fw" / "build" / "project.map", "large build map")
    _write(output / "gd1_fw" / "build" / "app.elf", "elf")

    declaration = load_lane_artifact_retention()
    report = resolve_lane_retention("firmware-pipeline", output, declaration)

    assert report.status == "complete"
    assert report.missing_required == ()
    paths = [item.path for item in report.retained]
    assert len(paths) == len(set(paths))
    second = resolve_lane_retention("firmware-pipeline", output, declaration)
    assert [item.path for item in second.retained] == paths
    assert "gd1_fw/main/acd_main.c" in paths
    assert "flash.bin" in paths
    assert all(item.sha256.startswith("sha256:") for item in report.retained)
    assert report.regenerable_files == 2
    assert report.regenerable_bytes > 0
    body = report.to_dict()
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert "manufacturing submission" in body["authority_statement"]


def test_missing_required_pattern_is_reported(tmp_path: Path) -> None:
    output = tmp_path / "gd1-fw"
    output.mkdir()

    declaration = load_lane_artifact_retention()
    report = resolve_lane_retention("firmware-pipeline", output, declaration)

    assert report.status == "missing_required"
    assert "flash.bin" in report.missing_required


def test_undeclared_lane_fails_closed(tmp_path: Path) -> None:
    declaration = load_lane_artifact_retention()
    with pytest.raises(LaneArtifactRetentionError):
        resolve_lane_retention("order-readiness", tmp_path, declaration)


def test_missing_contract_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LaneArtifactRetentionError):
        load_lane_artifact_retention(tmp_path / "absent.json")


def test_malformed_contract_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "contract.json"
    bad.write_text('{"schema_version": "0.1"', encoding="utf-8")
    with pytest.raises(LaneArtifactRetentionError):
        load_lane_artifact_retention(bad)


def test_document_model_directly(tmp_path: Path) -> None:
    document = LaneArtifactRetentionDocument.model_validate_json(
        CONTRACT_PATH.read_text(encoding="utf-8")
    )
    assert len(document.lanes) == 4
