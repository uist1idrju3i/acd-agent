# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@806dc3ab4aa3c6585630f30098d3b260c2450344",
# ]
# ///
"""Firmware pin-consistency check.

Cross-checks two independent sources:

1. the design graph firmware lane (``firmware.pin_assignment`` nodes),
2. the electrical lane (module pad connected to each net), resolved through
   a pinned module pad-to-GPIO map taken from the module datasheet.

Any missing, unknown or mismatched entry fails. This is a plain check run as
part of firmware development, not an ACD gate: pass/fail of the design is
still decided by ERC/DRC and the projection reload gates.
"""

from __future__ import annotations

from acd.core.electrical import ElectricalLane
from fw_graph import FirmwareLane


class PinConsistencyError(RuntimeError):
    """The firmware and electrical pin assignments are inconsistent."""


# ESP32-C3-MINI-1 module pad number -> GPIO number for the pads used by
# Golden Design #1. Source: Espressif "ESP32-C3-MINI-1 & ESP32-C3-MINI-1U
# Datasheet" v1.4, section pin definitions.
ESP32_C3_MINI_1_PAD_TO_GPIO: dict[str, int] = {
    "18": 4,
    "19": 5,
    "20": 6,
    "21": 7,
    "22": 8,
    "23": 9,
    "24": 10,
    "26": 18,
    "27": 19,
    "30": 20,
    "31": 21,
}


def assert_pin_assignments_consistent(
    fw_lane: FirmwareLane,
    electrical: ElectricalLane,
    module_refdes: str,
    pad_to_gpio: dict[str, int],
) -> None:
    module = next(
        (c for c in electrical.components if c.refdes == module_refdes),
        None,
    )
    if module is None:
        raise PinConsistencyError(f"module {module_refdes!r} not found in electrical lane")

    for pin in sorted(fw_lane.pins, key=lambda p: p.node_id):
        module_pads = [
            module_pin.pad
            for module_pin in electrical.pins_of_component(module.node_id)
            if module_pin.net_id == pin.net_id
        ]
        if len(module_pads) != 1:
            raise PinConsistencyError(
                f"net {pin.net_id!r}: expected exactly one {module_refdes} pad, got {module_pads}"
            )
        pad = module_pads[0]
        datasheet_gpio = pad_to_gpio.get(pad)
        if datasheet_gpio is None:
            raise PinConsistencyError(f"net {pin.net_id!r}: pad {pad!r} not in pinned pad map")
        if datasheet_gpio != pin.gpio:
            raise PinConsistencyError(
                f"net {pin.net_id!r}: graph GPIO {pin.gpio} but module pad {pad} "
                f"is GPIO {datasheet_gpio}"
            )


def assert_header_matches_lane(header: str, fw_lane: FirmwareLane) -> None:
    """The generated header must state exactly the graph's GPIO numbers."""
    for pin in fw_lane.pins:
        macro = "ACD_PIN_" + pin.net_id.removeprefix("net.").upper()
        if f"#define {macro} {pin.gpio}\n" not in header + "\n":
            raise PinConsistencyError(f"generated header does not define {macro} as {pin.gpio}")
