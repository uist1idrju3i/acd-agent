# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@a6130e5ebe5a17abc6984fe9af9b97152ec20dd8",
# ]
# ///
"""Golden Design #1 firmware pipeline: graph -> ESP-IDF build -> QEMU.

Single command:

    uv run --script plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py \
        --out out/gd1-fw

Stages: graph load/validation -> firmware and electrical lane extraction ->
ESP-IDF project projection (pins header generated from the graph) ->
pinned-toolchain build -> pin-consistency check (graph vs electrical lane vs
pinned module pad map) -> merged flash image -> QEMU esp32c3 virtual run with
serial log capture -> virtual log check. The virtual log is explicitly
labelled virtual and never substitutes for real-device measurement.

This pipeline is a skill asset, not an ACD gate. It is the reference
procedure for firmware work; the design's pass/fail is decided by the ACD
electrical and mechanical gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acd.core.electrical import extract_electrical_lane
from acd.schema.design_graph import DesignGraph
from fw_build import EspIdfBuilder
from fw_checks import (
    ESP32_C3_MINI_1_PAD_TO_GPIO,
    assert_header_matches_lane,
    assert_pin_assignments_consistent,
)
from fw_graph import extract_firmware_lane
from fw_project import write_firmware_project
from fw_qemu import (
    VIRTUAL_MEASUREMENT_CONDITIONS,
    QemuRunner,
    assert_virtual_log_ok,
)


def run_pipeline(fixture_dir: Path, out_dir: Path, run_seconds: int) -> dict[str, str]:
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    revision = graph.revision
    fw_lane = extract_firmware_lane(graph)
    electrical = extract_electrical_lane(graph)

    project = write_firmware_project(fw_lane, revision, out_dir, graph.graph_id)
    print(f"[1/5] firmware project projected: {project.root}")

    assert_header_matches_lane(project.pins_header.read_text(encoding="utf-8"), fw_lane)
    assert_pin_assignments_consistent(
        fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO
    )
    print("[2/5] pin-consistency check passed (graph/electrical/datasheet)")

    builder = EspIdfBuilder()
    binary = builder.build(project)
    build = builder.build_info(project, binary)
    print(f"[3/5] ESP-IDF build passed (version {builder.version()}): {binary}")

    merged = builder.merge_bin(project)
    qemu = QemuRunner()
    flash = qemu.make_flash_image(merged, out_dir / "flash.bin")
    result = qemu.run(flash, out_dir / "qemu-serial.log", run_seconds=run_seconds)
    print(f"[4/5] QEMU virtual run finished (version {qemu.version()}): {result.log_path}")

    log = result.log_path.read_text(errors="replace")
    led_gpio = fw_lane.gpio_for_net("net.led")
    assert_virtual_log_ok(log, target_revision=revision, led_gpio=led_gpio)
    print("[5/5] virtual log check passed")
    print("NOTE: real-device flashing/LED measurement unavailable (no debug probe attached)")

    return {
        "target_revision": revision,
        "toolchain_version": build.toolchain_version,
        "source_hash": build.source_hash,
        "artifact_hash": build.artifact_hash,
        "qemu_version": qemu.version(),
        "measurement_conditions": VIRTUAL_MEASUREMENT_CONDITIONS,
        "virtual_log": str(result.log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/golden-design-1"))
    parser.add_argument("--out", type=Path, default=Path("out/gd1-fw"))
    parser.add_argument("--run-seconds", type=int, default=15)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        summary = run_pipeline(args.fixture, args.out, args.run_seconds)
    except Exception as exc:
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr)
        return 1
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
