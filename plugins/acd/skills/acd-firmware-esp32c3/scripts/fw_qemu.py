"""QEMU virtual-target run: bounded execution, serial log capture, log check.

Virtual-device logs are virtual verification only and are never a substitute
for real-device measurement.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fw_graph import FirmwareCapabilityPlan, FirmwareLane
from fw_run import CommandRecord, resolve_tool, run_command

FLASH_SIZE_BYTES = 4 * 1024 * 1024


class QemuUnavailableError(RuntimeError):
    """Raised when the QEMU binary cannot be verified."""


class VirtualRunCheckError(RuntimeError):
    """The captured virtual serial log does not show required behaviour."""


@dataclass(frozen=True)
class VirtualRunResult:
    record: CommandRecord
    log_path: Path


class QemuRunner:
    def __init__(self, binary: str = "qemu-system-riscv32") -> None:
        resolved = resolve_tool(binary)
        if resolved is None:
            raise QemuUnavailableError(f"{binary} not found on PATH or in the ESP-IDF tools")
        self._binary = resolved
        result = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, check=False, timeout=60
        )
        match = re.search(r"version ([^\s]+(?: \([^)]*\))?)", result.stdout)
        if result.returncode != 0 or match is None:
            raise QemuUnavailableError(f"unparsable qemu version: {result.stdout!r}")
        self._version = match.group(1)

    def version(self) -> str:
        return self._version

    def make_flash_image(self, merged_bin: Path, flash_path: Path) -> Path:
        data = merged_bin.read_bytes()
        if len(data) > FLASH_SIZE_BYTES:
            raise VirtualRunCheckError(
                f"merged binary {len(data)} bytes exceeds flash size {FLASH_SIZE_BYTES}"
            )
        flash_path.write_bytes(data + b"\xff" * (FLASH_SIZE_BYTES - len(data)))
        return flash_path

    def run(
        self,
        flash_path: Path,
        log_path: Path,
        run_seconds: int = 15,
    ) -> VirtualRunResult:
        command = [
            "timeout",
            str(run_seconds),
            self._binary,
            "-M",
            "esp32c3",
            "-drive",
            f"file={flash_path},if=mtd,format=raw",
            "-serial",
            f"file:{log_path}",
            "-nographic",
            "-monitor",
            "none",
        ]
        record = run_command(
            command,
            tool_version=self._version,
            input_paths=[flash_path],
            output_paths=[log_path],
            allowed_exit_codes=frozenset({0, 124}),
        )
        return VirtualRunResult(record=record, log_path=log_path)


def assert_virtual_log_ok(
    log: str,
    *,
    target_revision: str,
    boot_log_message: str,
    lane: FirmwareLane,
    plan: FirmwareCapabilityPlan,
) -> None:
    expected_boot_line = boot_log_message.replace("%s", target_revision)
    if expected_boot_line not in log:
        raise VirtualRunCheckError("boot line with matching target revision not found")
    capability_ids = {step.capability_id for step in plan.steps}
    if "led_blink" in capability_ids:
        led_gpio = lane.gpio_for_role("led")
        toggles = re.findall(rf"LED gpio={led_gpio} state=([01])", log)
        if len(toggles) < 2 or {"0", "1"} != set(toggles):
            raise VirtualRunCheckError(
                f"expected LED toggles in both states, got {toggles[:4]}"
            )
    if "i2c_sensor_read" in capability_ids:
        sensor_step = next(
            step for step in plan.steps if step.capability_id == "i2c_sensor_read"
        )
        if sensor_step.device is None:
            raise VirtualRunCheckError("sensor read capability has no resolved device")
        driver_tag = re.escape(sensor_step.device.driver_id.upper())
        if not re.search(
            rf"{driver_tag} temp_c=|{driver_tag} read failed",
            log,
        ):
            raise VirtualRunCheckError(
                f"no {sensor_step.device.driver_id.upper()} measurement result found "
                "in virtual log"
            )


def measurement_conditions_for_plan(plan: FirmwareCapabilityPlan) -> str:
    drivers = sorted(
        {
            step.device.driver_id.upper()
            for step in plan.steps
            if step.device is not None
        }
    )
    if not drivers:
        return (
            "virtual device (QEMU esp32c3); no external device attached; "
            "virtual verification only, not real-device evidence"
        )
    return (
        f"virtual device (QEMU esp32c3); no {', '.join(drivers)} attached; "
        "virtual verification only, not real-device evidence"
    )
