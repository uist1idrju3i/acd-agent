"""Tests for the lane artifact retention collector."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import collect_lane_artifacts

from acd.pipeline.lane_plan import build_lane_plan

GRAPH_ID = "golden-design-1"


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _firmware_output(out_root: Path) -> Path:
    plan = build_lane_plan(GRAPH_ID, out_root)
    output = plan.stage("firmware-pipeline").output_path
    assert output is not None
    _write(output / "summary.json")
    _write(output / "evidence-firmware.json")
    _write(output / "firmware-coverage.json")
    _write(output / "firmware-config-report.json")
    _write(output / "flash.bin")
    _write(output / "qemu-serial.log")
    _write(output / "gd1_fw" / "CMakeLists.txt")
    _write(output / "gd1_fw" / "sdkconfig.defaults")
    _write(output / "gd1_fw" / "main" / "acd_main.c")
    _write(output / "gd1_fw" / "main" / "acd_pins.h")
    _write(output / "gd1_fw" / "build" / "app.elf", "regenerable")
    return output


def test_collects_only_the_declared_minimal_set(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    _firmware_output(out_root)
    dest = tmp_path / "retained"

    manifest = collect_lane_artifacts.collect(
        GRAPH_ID, out_root, dest, lanes=["firmware-pipeline"]
    )

    assert (dest / "firmware-pipeline" / "flash.bin").is_file()
    assert (dest / "firmware-pipeline" / "gd1_fw" / "main" / "acd_main.c").is_file()
    assert not (dest / "firmware-pipeline" / "gd1_fw" / "build").exists()
    assert (dest / "retention-manifest.json").is_file()
    assert manifest["pass_evidence"] is False
    assert manifest["record_class"] == "L3"


def test_manifest_is_deterministic_across_runs(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    _firmware_output(out_root)

    dest_a = tmp_path / "a"
    dest_b = tmp_path / "b"
    collect_lane_artifacts.collect(GRAPH_ID, out_root, dest_a, lanes=["firmware-pipeline"])
    collect_lane_artifacts.collect(GRAPH_ID, out_root, dest_b, lanes=["firmware-pipeline"])
    assert (dest_a / "retention-manifest.json").read_bytes() == (
        dest_b / "retention-manifest.json"
    ).read_bytes()


def test_missing_required_exits_nonzero_but_writes_manifest(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    plan = build_lane_plan(GRAPH_ID, out_root)
    output = plan.stage("firmware-pipeline").output_path
    assert output is not None
    output.mkdir(parents=True)

    dest = tmp_path / "retained"
    code = collect_lane_artifacts.main(
        [
            "--out-root",
            str(out_root),
            "--graph-id",
            GRAPH_ID,
            "--dest",
            str(dest),
            "--lane",
            "firmware-pipeline",
        ]
    )

    assert code == 1
    manifest = json.loads(
        (dest / "retention-manifest.json").read_text(encoding="utf-8")
    )
    lane = manifest["lanes"][0]
    assert lane["status"] == "missing_required"
    assert "flash.bin" in lane["missing_required"]


def test_unknown_lane_selector_fails_closed(tmp_path: Path) -> None:
    code = collect_lane_artifacts.main(
        [
            "--out-root",
            str(tmp_path / "out"),
            "--graph-id",
            GRAPH_ID,
            "--dest",
            str(tmp_path / "retained"),
            "--lane",
            "bogus-lane",
        ]
    )
    assert code == 1
