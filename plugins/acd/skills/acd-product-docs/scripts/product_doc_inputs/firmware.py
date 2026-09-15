"""Firmware configuration report loading and graph-consistency guards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.core.firmware_lane import extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from acd.schema.firmware_inspection import FirmwareInspectionSequence
from product_doc_inputs.common import (
    DocumentGenerationError,
    load_json_object,
    require_list,
    require_object,
    require_str,
)


@dataclass(frozen=True)
class ReportPin:
    """One pin entry of the firmware config report."""

    node_id: str
    gpio: int
    net: str


@dataclass(frozen=True)
class ReportDevice:
    """One device entry of the firmware config report provenance."""

    mpn: str
    driver_id: str
    i2c_address: int


@dataclass(frozen=True)
class FirmwareConfigReport:
    """Parsed firmware config report written by the FW pipeline."""

    graph_id: str
    target_revision: str
    pins: tuple[ReportPin, ...]
    capabilities: tuple[str, ...]
    devices: tuple[ReportDevice, ...]
    led_blink_period_ms: int
    log_period_ms: int
    boot_log_message: str
    inspection_entry_command: str | None


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentGenerationError(f"report field {field!r} is missing or not an int")
    return value


def load_firmware_config_report(path: Path) -> FirmwareConfigReport:
    """Load the firmware config report, failing closed on any defect."""
    data = load_json_object(path, label="firmware config report")
    report = data
    pins = tuple(
        ReportPin(
            node_id=require_str(item.get("node_id"), field="pins[].node_id"),
            gpio=_require_int(item.get("gpio"), field="pins[].gpio"),
            net=require_str(item.get("net"), field="pins[].net"),
        )
        for item in (
            require_object(item, field="pins[]")
            for item in require_list(report.get("pins"), field="pins")
        )
    )
    settings = require_object(report.get("settings"), field="settings")
    provenance = require_object(report.get("provenance"), field="provenance")
    capabilities = tuple(
        sorted(
            require_str(item.get("capability_id"), field="capabilities[].capability_id")
            for item in (
                require_object(entry, field="capabilities[]")
                for entry in require_list(provenance.get("capabilities"), field="capabilities")
            )
        )
    )
    devices = tuple(
        sorted(
            (
                ReportDevice(
                    mpn=require_str(item.get("mpn"), field="devices[].mpn"),
                    driver_id=require_str(item.get("driver_id"), field="devices[].driver_id"),
                    i2c_address=_require_int(
                        item.get("i2c_address"), field="devices[].i2c_address"
                    ),
                )
                for item in (
                    require_object(entry, field="devices[]")
                    for entry in require_list(provenance.get("devices"), field="devices")
                )
            ),
            key=lambda device: device.driver_id,
        )
    )
    return FirmwareConfigReport(
        graph_id=require_str(report.get("graph_id"), field="graph_id"),
        target_revision=require_str(report.get("target_revision"), field="target_revision"),
        pins=pins,
        capabilities=capabilities,
        devices=devices,
        led_blink_period_ms=_require_int(
            settings.get("led_blink_period_ms"), field="settings.led_blink_period_ms"
        ),
        log_period_ms=_require_int(settings.get("log_period_ms"), field="settings.log_period_ms"),
        boot_log_message=require_str(
            settings.get("boot_log_message"), field="settings.boot_log_message"
        ),
        inspection_entry_command=(
            None
            if settings.get("inspection_entry_command") is None
            else require_str(
                settings.get("inspection_entry_command"),
                field="settings.inspection_entry_command",
            )
        ),
    )


def load_firmware_inspection_sequence(path: Path) -> FirmwareInspectionSequence:
    """Load an optional firmware inspection sequence as a governed contract."""
    data = load_json_object(path, label="firmware inspection sequence")
    try:
        return FirmwareInspectionSequence.model_validate(data)
    except ValueError as exc:
        raise DocumentGenerationError(
            f"firmware inspection sequence {path} is not valid: {exc}"
        ) from exc


def _guard_report(graph: DesignGraph, report: FirmwareConfigReport) -> None:
    if report.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"firmware config report targets graph {report.graph_id!r}, not {graph.graph_id!r}"
        )
    if report.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"firmware config report targets revision {report.target_revision!r}, "
            f"not {graph.revision!r}"
        )


def _guard_revision(graph: DesignGraph, macros: dict[str, str]) -> None:
    revision = macros["ACD_TARGET_REVISION"].strip('"')
    if revision != graph.revision:
        raise DocumentGenerationError(
            f"pin projection targets revision {revision!r}, not {graph.revision!r}"
        )


def _macro_int(macros: dict[str, str], name: str, *, because: str) -> int:
    raw = macros.get(name)
    if raw is None:
        raise DocumentGenerationError(
            f"pin projection lacks {name} although the report declares {because}"
        )
    try:
        return int(raw, 0)
    except ValueError as exc:
        raise DocumentGenerationError(
            f"pin projection macro {name} is not an integer: {raw!r}"
        ) from exc


def _guard_pins(
    graph: DesignGraph,
    report: FirmwareConfigReport,
    macros: dict[str, str],
) -> tuple[ReportPin, ...]:
    graph_pins = {
        assignment.net: assignment.gpio
        for assignment in extract_firmware_lane(graph).pin_assignments
    }
    report_pins = {pin.net: pin.gpio for pin in report.pins}
    if report_pins != graph_pins:
        raise DocumentGenerationError(
            "firmware config report pins do not match graph "
            f"firmware.pin_assignment nodes: report={sorted(report_pins.items())}, "
            f"graph={sorted(graph_pins.items())}"
        )
    for pin in report.pins:
        macro = "ACD_PIN_" + pin.net.removeprefix("net.").upper()
        header_gpio = _macro_int(macros, macro, because=f"pin {pin.net}")
        if header_gpio != pin.gpio:
            raise DocumentGenerationError(
                f"pin projection macro {macro}={header_gpio} does not match "
                f"report gpio {pin.gpio} for net {pin.net!r}"
            )
    return tuple(sorted(report.pins, key=lambda pin: pin.net))


def _guard_devices(
    report: FirmwareConfigReport, macros: dict[str, str]
) -> tuple[ReportDevice, ...]:
    seen_addresses: dict[int, str] = {}
    for device in report.devices:
        macro = f"ACD_{device.driver_id.upper()}_I2C_ADDRESS"
        header_address = _macro_int(macros, macro, because=f"device {device.driver_id}")
        if header_address != device.i2c_address:
            raise DocumentGenerationError(
                f"pin projection macro {macro}=0x{header_address:02x} does not "
                f"match report i2c_address 0x{device.i2c_address:02x} for "
                f"driver {device.driver_id!r}"
            )
        owner = seen_addresses.get(device.i2c_address)
        if owner is not None:
            raise DocumentGenerationError(
                f"drivers {owner!r} and {device.driver_id!r} share I2C address "
                f"0x{device.i2c_address:02x}"
            )
        seen_addresses[device.i2c_address] = device.driver_id
    return report.devices


guard_devices = _guard_devices


guard_pins = _guard_pins


guard_report = _guard_report


guard_revision = _guard_revision
