# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@b821b5466e2feee0783f2f819d8c4105ccf77eb8",
# ]
# ///
"""Typed extraction of the firmware lane from a design graph.

The design graph is the only source of firmware pin assignments. Projections
consume these views; missing or malformed attributes fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from acd.schema.design_graph import DesignGraph


class FirmwareExtractionError(ValueError):
    """Raised when the firmware lane cannot be extracted (fail-closed)."""


@dataclass(frozen=True)
class FirmwarePinView:
    node_id: str
    gpio: int
    net_id: str


@dataclass(frozen=True)
class FirmwareLane:
    pins: tuple[FirmwarePinView, ...]

    def pin_by_id(self, node_id: str) -> FirmwarePinView:
        for pin in self.pins:
            if pin.node_id == node_id:
                return pin
        raise KeyError(node_id)

    def gpio_for_net(self, net_id: str) -> int:
        for pin in self.pins:
            if pin.net_id == net_id:
                return pin.gpio
        raise FirmwareExtractionError(f"no firmware pin assignment for net {net_id!r}")


def extract_firmware_lane(graph: DesignGraph) -> FirmwareLane:
    pins: list[FirmwarePinView] = []
    for node in graph.nodes:
        if node.kind != "firmware.pin_assignment":
            continue
        gpio = node.attrs.get("gpio")
        net = node.attrs.get("net")
        if isinstance(gpio, bool) or not isinstance(gpio, int):
            raise FirmwareExtractionError(f"node {node.id!r}: attr 'gpio' missing or not an int")
        if not isinstance(net, str) or not net:
            raise FirmwareExtractionError(f"node {node.id!r}: attr 'net' missing or not a string")
        pins.append(FirmwarePinView(node_id=node.id, gpio=gpio, net_id=net))
    if not pins:
        raise FirmwareExtractionError("graph has no firmware.pin_assignment nodes")
    gpios = [pin.gpio for pin in pins]
    if len(set(gpios)) != len(gpios):
        raise FirmwareExtractionError("duplicate GPIO in firmware pin assignments")
    nets = [pin.net_id for pin in pins]
    if len(set(nets)) != len(nets):
        raise FirmwareExtractionError("duplicate net in firmware pin assignments")
    return FirmwareLane(pins=tuple(sorted(pins, key=lambda p: p.node_id)))
