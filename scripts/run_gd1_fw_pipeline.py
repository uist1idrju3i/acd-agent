"""Golden Design #1 firmware pipeline: graph -> ESP-IDF build -> QEMU (fail-closed).

Single deterministic command:

    uv run python scripts/run_gd1_fw_pipeline.py --out out/gd1-fw

Stages: graph load/validation -> firmware + electrical lane extraction ->
ESP-IDF project projection (pins header generated from the graph) ->
pinned-toolchain build wrapped in a ToolEnvelope -> FwPackage projection with
source/artifact hashes -> pin-assignment consistency gate (package vs graph
vs electrical lane vs pinned module pad map) -> merged flash image -> QEMU
esp32c3 virtual run with serial log capture -> virtual log gate -> virtual
verification Evidence record. Virtual evidence is explicitly labelled and is
never a substitute for real-device measurement; real-device flashing/log
evidence is reported unavailable when no probe is attached. Any unknown or
failing state stops the pipeline with a nonzero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from acd_adapter_espidf.build import EspIdfBuilder, fw_package_from_lane
from acd_adapter_espidf.gates import (
    ESP32_C3_MINI_1_PAD_TO_GPIO,
    assert_build_known,
    assert_pin_assignments_consistent,
)
from acd_adapter_espidf.project import write_firmware_project
from acd_adapter_espidf.qemu import QemuRunner, assert_virtual_log_ok
from acd_core.electrical import extract_electrical_lane
from acd_core.firmware import extract_firmware_lane
from acd_core.process import sha256_paths
from acd_schema.design_graph import DesignGraph
from acd_schema.evidence import Evidence, EvidenceClaim
from acd_schema.fw_package import BuildInfo


def run_pipeline(fixture_dir: Path, out_dir: Path, run_seconds: int) -> dict[str, str]:
    graph = DesignGraph.model_validate(json.loads((fixture_dir / "graph.json").read_text()))
    revision = graph.revision
    fw_lane = extract_firmware_lane(graph)
    electrical = extract_electrical_lane(graph)

    project = write_firmware_project(fw_lane, revision, out_dir)
    print(f"[1/6] firmware project projected: {project.root}")

    builder = EspIdfBuilder()
    binary = builder.build(project, out_dir / "envelope-build.json", revision)
    print(f"[2/6] ESP-IDF build passed (version {builder.version()}): {binary}")

    build_info = BuildInfo(
        toolchain_version=f"esp-idf {builder.version()}",
        source_hash=builder.source_hash(project),
        artifact_hash=sha256_paths([binary]),
    )
    package = fw_package_from_lane(
        fw_lane, package_id="fw.gd1", target_revision=revision, build=build_info
    )
    assert_build_known(package)
    package_path = out_dir / "fw-package.json"
    package_path.write_text(package.model_dump_json(indent=2) + "\n")
    print(f"[3/6] fw package projected: {package_path}")

    assert_pin_assignments_consistent(
        package, fw_lane, electrical, "U1", ESP32_C3_MINI_1_PAD_TO_GPIO
    )
    print("[4/6] pin-assignment consistency gate passed (package/graph/electrical/datasheet)")

    merged = builder.merge_bin(project, out_dir / "envelope-merge.json", revision)
    qemu = QemuRunner()
    flash = qemu.make_flash_image(merged, out_dir / "flash.bin")
    result = qemu.run(
        flash,
        out_dir / "qemu-serial.log",
        out_dir / "envelope-qemu.json",
        revision,
        run_seconds=run_seconds,
    )
    log = result.log_path.read_text(errors="replace")
    led_gpio = fw_lane.gpio_for_net("net.led")
    assert_virtual_log_ok(log, target_revision=revision, led_gpio=led_gpio)
    print(f"[5/6] QEMU virtual run gate passed (version {qemu.version()}): {result.log_path}")

    evidence = Evidence(
        evidence_id="evidence.gd1.fw.virtual-run",
        target_revision=revision,
        status="valid",
        envelope=result.envelope,
        claims=[
            EvidenceClaim(
                subject_node="fw.pin.led",
                property="virtual_led_blink_observed",
                value=True,
                verified=True,
            ),
            EvidenceClaim(
                subject_node="fw.pin.led",
                property="real_device_led_measurement",
                value="unavailable",
                verified=False,
            ),
        ],
        created_at=datetime.now(UTC),
    )
    evidence_path = out_dir / "evidence-virtual-run.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n")
    print(f"[6/6] virtual verification evidence recorded: {evidence_path}")
    print("NOTE: real-device flashing/LED evidence unavailable (no debug probe attached)")

    return {
        "fw_package": str(package_path),
        "artifact_hash": build_info.artifact_hash,
        "source_hash": build_info.source_hash,
        "evidence": str(evidence_path),
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
        print(f"PIPELINE FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
