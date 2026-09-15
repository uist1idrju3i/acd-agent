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
INTENDED_TIMEOUT_EXIT_CODE = 124


class QemuUnavailableError(RuntimeError):
    """Raised when the QEMU binary cannot be verified."""


class VirtualRunCheckError(RuntimeError):
    """The captured virtual serial log does not show required behaviour."""


def sht40_crc(data: bytes) -> int:
    """Return the SHT40 CRC-8 (polynomial 0x31, initial value 0xff)."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode_sht40_sample(t_c: float, rh_pct: float) -> bytes:
    """Encode one quantized SHT40 sample using the generated C model."""
    t_raw = round((t_c + 45.0) * 65535.0 / 175.0)
    rh_raw = round((rh_pct + 6.0) * 65535.0 / 125.0)
    t = max(0, min(65535, t_raw)).to_bytes(2, "big")
    rh = max(0, min(65535, rh_raw)).to_bytes(2, "big")
    return t + bytes([sht40_crc(t)]) + rh + bytes([sht40_crc(rh)])


def assert_sensor_log_matches_scenario(
    log: str, scenario: list[dict[str, float]], tolerance: float = 0.01
) -> None:
    """Require each declared cyclic SHT40 sample to appear in the virtual log."""
    matches = re.findall(r"SHT40 temp_c=(-?\d+(?:\.\d+)?) rh=(-?\d+(?:\.\d+)?)", log)
    if len(matches) < len(scenario):
        raise VirtualRunCheckError(
            f"SHT40 scenario requires {len(scenario)} samples, got {len(matches)}"
        )
    for index, expected in enumerate(scenario):
        actual_t, actual_rh = (float(value) for value in matches[index])
        if (
            abs(actual_t - expected["t_c"]) > tolerance
            or abs(actual_rh - expected["rh_pct"]) > tolerance
        ):
            raise VirtualRunCheckError(
                f"SHT40 scenario mismatch at index {index}: "
                f"expected {expected}, got t_c={actual_t}, rh_pct={actual_rh}"
            )


@dataclass(frozen=True)
class VirtualRunResult:
    record: CommandRecord
    log_path: Path
    run_seconds: int

    @property
    def stopped_by_intended_timeout(self) -> bool:
        """Whether the bounded run was stopped by its own intended timeout."""
        return self.record.exit_code == INTENDED_TIMEOUT_EXIT_CODE

    def termination_condition(self) -> str:
        """Describe how the bounded virtual run ended.

        The bounded QEMU run has no self-terminating end state, so the
        intended timeout is the normal completion condition of this virtual
        run and not a failure. This wording matches the
        ``measurement_conditions`` recorded in the firmware ToolEnvelope.
        """
        if self.stopped_by_intended_timeout:
            return (
                f"stopped by the intended {self.run_seconds}s bound "
                f"(exit code {INTENDED_TIMEOUT_EXIT_CODE}); this is the normal "
                "completion condition of the bounded virtual run, not a failure"
            )
        return (
            f"exited on its own before the {self.run_seconds}s bound "
            f"(exit code {self.record.exit_code})"
        )


class QemuRunner:
    def __init__(self, binary: str = "qemu-system-riscv32") -> None:
        resolved = resolve_tool(binary)
        if resolved is None:
            raise QemuUnavailableError(f"{binary} not found on PATH or in the ESP-IDF tools")
        self._binary = resolved
        result = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
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
            allowed_exit_codes=frozenset({0, INTENDED_TIMEOUT_EXIT_CODE}),
        )
        return VirtualRunResult(
            record=record, log_path=log_path, run_seconds=run_seconds
        )


def assert_virtual_log_ok(
    log: str,
    *,
    target_revision: str,
    boot_log_message: str,
    lane: FirmwareLane,
    plan: FirmwareCapabilityPlan,
    inspection_sequence: object | None = None,
) -> None:
    if inspection_sequence is not None and "ACD_INSPECT begin" in log:
        raise VirtualRunCheckError(
            "inspection mode must not autorun without a UART entry command"
        )
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
    if "led2_blink" in capability_ids:
        led2_gpio = lane.gpio_for_role("led2")
        toggles = re.findall(rf"LED2 gpio={led2_gpio} state=([01])", log)
        if len(toggles) < 2 or {"0", "1"} != set(toggles):
            raise VirtualRunCheckError(
                f"expected LED2 toggles in both states, got {toggles[:4]}"
            )
    if "button_input" in capability_ids and re.search(r"paused=1", log):
        raise VirtualRunCheckError(
            "virtual run must not show a button pause; QEMU never presses "
            "the button but the log contains paused=1"
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
