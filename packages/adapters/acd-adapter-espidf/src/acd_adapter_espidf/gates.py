"""Deterministic firmware pin-consistency gate.

Cross-checks three independent sources fail-closed:

1. the firmware package projection (``FwPackage.pin_assignments``),
2. the design graph firmware lane (``firmware.pin_assignment`` nodes),
3. the electrical lane (module pad connected to each net), resolved through
   a pinned module pad-to-GPIO map taken from the module datasheet.

Any missing, unknown, or mismatched entry fails the gate. The AI proposes,
this function decides.
"""

from __future__ import annotations

from acd_core.electrical import ElectricalLane
from acd_core.firmware import FirmwareLane
from acd_schema.fw_package import FwPackage


class PinGateError(RuntimeError):
    """The firmware/electrical pin assignments are inconsistent (fail-closed)."""


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
    package: FwPackage,
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
        raise PinGateError(f"module {module_refdes!r} not found in electrical lane")

    graph_by_net = {pin.net_id: pin.gpio for pin in fw_lane.pins}
    package_by_net = {a.net: a for a in package.pin_assignments}
    if set(graph_by_net) != set(package_by_net):
        missing = set(graph_by_net) ^ set(package_by_net)
        raise PinGateError(f"package/graph net sets differ: {sorted(missing)}")

    for net_id, gpio in sorted(graph_by_net.items()):
        assignment = package_by_net[net_id]
        if assignment.pin != f"IO{gpio}":
            raise PinGateError(
                f"net {net_id!r}: package pin {assignment.pin!r} != graph GPIO {gpio}"
            )
        module_pads = [
            pin.pad
            for pin in electrical.pins_of_component(module.node_id)
            if pin.net_id == net_id
        ]
        if len(module_pads) != 1:
            raise PinGateError(
                f"net {net_id!r}: expected exactly one {module_refdes} pad, got {module_pads}"
            )
        pad = module_pads[0]
        datasheet_gpio = pad_to_gpio.get(pad)
        if datasheet_gpio is None:
            raise PinGateError(f"net {net_id!r}: pad {pad!r} not in pinned pad map (unknown)")
        if datasheet_gpio != gpio:
            raise PinGateError(
                f"net {net_id!r}: graph GPIO {gpio} but module pad {pad} is GPIO {datasheet_gpio}"
            )


def assert_build_known(package: FwPackage) -> None:
    if package.build.has_unknown():
        raise PinGateError("firmware build info contains unknown values (fail-closed)")
