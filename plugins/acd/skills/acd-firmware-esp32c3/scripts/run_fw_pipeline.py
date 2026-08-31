# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@d4b0323c346f34c4562a811ed95373f9ad4637fb",
# ]
# ///
# The PEP 723 git pin remains for standalone runs; project execution uses the checkout directly.
"""Graph-driven firmware pipeline: graph -> ESP-IDF build -> QEMU.

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
import os
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
from fw_graph import (
    extract_firmware_lane,
    extract_firmware_settings,
    resolve_firmware_capability_plan,
)
from fw_project import write_firmware_project
from fw_qemu import (
    QemuRunner,
    assert_virtual_log_ok,
    measurement_conditions_for_plan,
)


class _LegacyFlag(argparse.Action):
    """Reject a historic lane flag with the canonical replacement."""

    def __init__(self, option_strings: list[str], dest: str, **kwargs: object) -> None:
        replacement = kwargs.pop("replacement")
        if not isinstance(replacement, str):
            raise TypeError("replacement must be a string")
        self.replacement = replacement
        super().__init__(option_strings, dest, nargs=None, default=None)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values
        parser.error(
            f"{option_string} is not accepted; use {self.replacement} instead "
            "(every lane entry point takes --fixture and --out)"
        )


def resolve_mcu_refdes(graph: DesignGraph) -> str:
    """Resolve the firmware module MCU component reference designator."""
    modules = [node for node in graph.nodes if node.kind == "firmware.module"]
    if len(modules) != 1:
        raise ValueError("graph must contain exactly one firmware.module node")
    component_id = modules[0].attrs.get("mcu_component")
    if not isinstance(component_id, str) or not component_id:
        raise ValueError("firmware.module mcu_component is missing")
    try:
        component = graph.node_by_id(component_id)
    except KeyError as exc:
        raise ValueError(
            f"firmware.module mcu_component {component_id!r} does not resolve to a component"
        ) from exc
    if component.kind != "electrical.component":
        raise ValueError(
            f"firmware.module mcu_component {component_id!r} does not resolve to a component"
        )
    refdes = component.attrs.get("refdes")
    if not isinstance(refdes, str) or not refdes:
        raise ValueError("firmware MCU component has no refdes")
    return refdes


def run_pipeline(
    fixture_dir: Path, out_dir: Path, run_seconds: int
) -> dict[str, object]:
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    revision = graph.revision
    fw_lane = extract_firmware_lane(graph)
    plan = resolve_firmware_capability_plan(graph, fw_lane)
    fw_settings = extract_firmware_settings(graph)
    electrical = extract_electrical_lane(graph)

    project = write_firmware_project(
        fw_lane,
        revision,
        out_dir,
        graph.graph_id,
        fw_settings,
        plan=plan,
    )
    mcu_refdes = resolve_mcu_refdes(graph)
    config_report = {
        "schema_version": 1,
        "graph_id": graph.graph_id,
        "target_revision": revision,
        "pins": [
            {"node_id": pin.node_id, "gpio": pin.gpio, "net": pin.net_id}
            for pin in fw_lane.pins
        ],
        "settings": {
            "led_blink_period_ms": fw_settings.led_blink_period_ms,
            "log_period_ms": fw_settings.log_period_ms,
            "boot_log_message": fw_settings.boot_log_message,
        },
        "provenance": {
            "registry_path": plan.registry_path,
            "registry_hash": plan.registry_hash,
            "capabilities": [
                {
                    "capability_id": step.capability_id,
                    "action": step.action,
                    "step_index": step.step_index,
                }
                for step in plan.steps
            ],
            "devices": [
                {
                    "mpn": step.device.mpn,
                    "driver_id": step.device.driver_id,
                    "i2c_address": step.device.i2c_address,
                }
                for step in plan.steps
                if step.device is not None
            ],
        },
    }
    (out_dir / "firmware-config-report.json").write_text(
        json.dumps(config_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[1/5] firmware project projected: {project.root}")

    assert_header_matches_lane(project.pins_header.read_text(encoding="utf-8"), fw_lane)
    assert_pin_assignments_consistent(
        fw_lane, electrical, mcu_refdes, ESP32_C3_MINI_1_PAD_TO_GPIO
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
    print(f"       bounded virtual run {result.termination_condition()}")

    log = result.log_path.read_text(errors="replace")
    assert_virtual_log_ok(
        log,
        target_revision=revision,
        boot_log_message=fw_settings.boot_log_message,
        lane=fw_lane,
        plan=plan,
    )
    print("[5/5] virtual log check passed")
    print("NOTE: real-device flashing/LED measurement unavailable (no debug probe attached)")

    return {
        "target_revision": revision,
        "toolchain_version": build.toolchain_version,
        "source_hash": build.source_hash,
        "artifact_hash": build.artifact_hash,
        "qemu_version": qemu.version(),
        "measurement_conditions": measurement_conditions_for_plan(plan),
        "virtual_run_seconds": run_seconds,
        "virtual_run_exit_code": result.record.exit_code,
        "virtual_run_termination": result.termination_condition(),
        "virtual_run_stopped_by_intended_timeout": result.stopped_by_intended_timeout,
        "virtual_log": str(result.log_path),
        "config_report": str(out_dir / "firmware-config-report.json"),
    }


def main() -> int:
    if "ACD_REPOSITORY_ROOT" not in os.environ:
        os.environ["ACD_REPOSITORY_ROOT"] = str(Path(__file__).resolve().parents[5])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/golden-design-1"),
        help="design input directory containing graph.json",
    )
    parser.add_argument("--out", type=Path, default=Path("out/gd1-fw"))
    parser.add_argument("--run-seconds", type=int, default=15)
    for legacy, replacement in (
        ("--graph", "--fixture"),
        ("--graph-dir", "--fixture"),
        ("--fixture-dir", "--fixture"),
        ("--out-dir", "--out"),
        ("--output", "--out"),
    ):
        parser.add_argument(
            legacy,
            action=_LegacyFlag,
            replacement=replacement,
            help=argparse.SUPPRESS,
        )
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
