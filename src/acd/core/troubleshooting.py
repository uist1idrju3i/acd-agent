"""Derivation of troubleshooting knowledge from the graph and pin projection.

The expected values a user compares against (LED GPIO, blink period, I2C
address, serial log period, supply voltages) exist already in the design graph
and in the generated ``acd_pins.h`` pin projection. This module projects them
into machine-readable troubleshooting entries so the question answering path and
the published FAQ share one derivation instead of restating values by hand.
Anything that cannot be derived becomes an ``unknown`` entry with a reason.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from acd.schema.design_graph import DesignGraph
from acd.schema.troubleshooting import (
    UNKNOWN_EXPECTATION,
    TroubleshootingEntry,
    TroubleshootingExpectation,
    TroubleshootingKnowledge,
)

PIN_PROJECTION_NAME = "acd_pins.h"
_DEFINE_PATTERN = re.compile(r"^#define\s+(?P<name>[A-Z0-9_]+)\s+(?P<value>\S+)\s*$")


class TroubleshootingDerivationError(ValueError):
    """Raised when troubleshooting knowledge cannot be derived at all."""


def parse_pin_macros(text: str) -> dict[str, str]:
    """Return the macro values declared by a generated pin projection header."""
    macros: dict[str, str] = {}
    for line in text.splitlines():
        match = _DEFINE_PATTERN.match(line)
        if match is not None:
            macros[match.group("name")] = match.group("value")
    return macros


def load_pin_macros(path: Path) -> dict[str, str]:
    """Load the pin projection macros, or return an empty mapping if absent."""
    try:
        return parse_pin_macros(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _macro_expectation(
    macros: Mapping[str, str], macro: str, description: str
) -> tuple[TroubleshootingExpectation, str | None]:
    value = macros.get(macro)
    citation = f"{PIN_PROJECTION_NAME}#{macro}"
    if value is None:
        return (
            TroubleshootingExpectation(
                description=description,
                expected=UNKNOWN_EXPECTATION,
                citation=citation,
            ),
            f"pin projection macro {macro} is missing",
        )
    return (
        TroubleshootingExpectation(
            description=description, expected=value, citation=citation
        ),
        None,
    )


def _entry(
    *,
    entry_id: str,
    symptom: str,
    checks: Sequence[str],
    resolved: Sequence[tuple[TroubleshootingExpectation, str | None]],
) -> TroubleshootingEntry:
    expectations = [item for item, _ in resolved]
    reasons = sorted({reason for _, reason in resolved if reason is not None})
    if reasons:
        return TroubleshootingEntry(
            entry_id=entry_id,
            symptom=symptom,
            checks=list(checks),
            expectations=expectations,
            status="unknown",
            reason="; ".join(reasons),
        )
    return TroubleshootingEntry(
        entry_id=entry_id,
        symptom=symptom,
        checks=list(checks),
        expectations=expectations,
        status="derived",
    )


def _power_rail_entry(graph: DesignGraph) -> TroubleshootingEntry:
    resolved: list[tuple[TroubleshootingExpectation, str | None]] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.net" or node.attrs.get("power_rail") is not True:
            continue
        name = node.attrs.get("name")
        voltage = node.attrs.get("voltage_nominal_v")
        label = name if isinstance(name, str) and name else node.id
        description = f"Nominal voltage of the {label} rail"
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float)):
            resolved.append(
                (
                    TroubleshootingExpectation(
                        description=description,
                        expected=UNKNOWN_EXPECTATION,
                        citation=node.id,
                    ),
                    f"net {node.id} declares no nominal voltage",
                )
            )
            continue
        resolved.append(
            (
                TroubleshootingExpectation(
                    description=description,
                    expected=f"{float(voltage):g} V",
                    citation=node.id,
                ),
                None,
            )
        )
    if not resolved:
        resolved.append(
            (
                TroubleshootingExpectation(
                    description="Nominal voltage of each power rail",
                    expected=UNKNOWN_EXPECTATION,
                    citation=graph.graph_id,
                ),
                "graph declares no power rail net",
            )
        )
    return _entry(
        entry_id="ts-power-rail-out-of-range",
        symptom="The board does not start up, or a supply rail reads an unexpected voltage.",
        checks=[
            "Supply the board through its power input and keep the load connected.",
            "Measure each power rail against ground with a multimeter.",
            "Compare every measured voltage with the declared nominal voltage.",
        ],
        resolved=resolved,
    )


def derive_troubleshooting_knowledge(
    graph: DesignGraph, *, pin_macros: Mapping[str, str]
) -> TroubleshootingKnowledge:
    """Derive troubleshooting entries from the graph and the pin projection."""
    entries = [
        _entry(
            entry_id="ts-led-not-blinking",
            symptom="The status LED stays dark or does not blink.",
            checks=[
                "Confirm the firmware of the target revision is flashed.",
                "Observe the LED and measure the blink period.",
                "Probe the LED GPIO for a square wave at the declared period.",
            ],
            resolved=[
                _macro_expectation(pin_macros, "ACD_PIN_LED", "Status LED GPIO number"),
                _macro_expectation(
                    pin_macros,
                    "ACD_LED_BLINK_PERIOD_MS",
                    "LED blink period in milliseconds",
                ),
            ],
        ),
        _entry(
            entry_id="ts-no-sensor-reading",
            symptom="Sensor values are missing or the sensor does not answer.",
            checks=[
                "Watch the measurement log lines for sensor values.",
                "Probe the I2C bus lines for clock and data activity.",
                "Confirm the sensor answers on the declared I2C address.",
            ],
            resolved=[
                _macro_expectation(pin_macros, "ACD_PIN_I2C_SCL", "I2C clock GPIO number"),
                _macro_expectation(pin_macros, "ACD_PIN_I2C_SDA", "I2C data GPIO number"),
                _macro_expectation(
                    pin_macros, "ACD_SHT40_I2C_ADDRESS", "Sensor I2C address"
                ),
            ],
        ),
        _entry(
            entry_id="ts-no-serial-log",
            symptom="The serial console shows no log output.",
            checks=[
                "Open the serial console on the host at the firmware baud rate.",
                "Reset the board and watch for the startup log lines.",
                "Confirm the console is attached to the declared UART pins.",
            ],
            resolved=[
                _macro_expectation(pin_macros, "ACD_PIN_UART_RX", "UART receive GPIO number"),
                _macro_expectation(pin_macros, "ACD_PIN_UART_TX", "UART transmit GPIO number"),
                _macro_expectation(
                    pin_macros, "ACD_LOG_PERIOD_MS", "Log period in milliseconds"
                ),
            ],
        ),
        _entry(
            entry_id="ts-usb-not-detected",
            symptom="The host does not detect the board over USB.",
            checks=[
                "Use a USB cable that carries data, not power only.",
                "Check whether the host enumerates the board after a reset.",
                "Enter the download mode with the boot control before flashing.",
            ],
            resolved=[
                _macro_expectation(pin_macros, "ACD_PIN_BOOT", "Boot control GPIO number"),
                _macro_expectation(pin_macros, "ACD_PIN_USB_DN", "USB D- GPIO number"),
                _macro_expectation(pin_macros, "ACD_PIN_USB_DP", "USB D+ GPIO number"),
            ],
        ),
        _power_rail_entry(graph),
    ]
    return TroubleshootingKnowledge(
        graph_id=graph.graph_id,
        target_revision=graph.revision,
        entries=sorted(entries, key=lambda item: item.entry_id),
    )
