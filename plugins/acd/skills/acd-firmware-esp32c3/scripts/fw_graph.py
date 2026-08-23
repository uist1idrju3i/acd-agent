# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@75f667eb4dfc6a399c709570113e0f870533cd00",
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


@dataclass(frozen=True)
class FirmwareSettings:
    led_blink_period_ms: int = 1000
    log_period_ms: int = 2000
    boot_log_message: str = "ACD GD1 fw boot target_revision=%s"


def extract_firmware_settings(graph: DesignGraph) -> FirmwareSettings:
    modules = [node for node in graph.nodes if node.kind == "firmware.module"]
    if len(modules) != 1:
        raise FirmwareExtractionError("graph must contain exactly one firmware.module node")
    attrs = modules[0].attrs
    values: dict[str, object] = {}
    for name, default in (
        ("led_blink_period_ms", 1000),
        ("log_period_ms", 2000),
        ("boot_log_message", "ACD GD1 fw boot target_revision=%s"),
    ):
        value = attrs.get(name, default)
        if isinstance(value, bool) or not isinstance(value, type(default)):
            raise FirmwareExtractionError(
                f"node {modules[0].id!r}: attr {name!r} is malformed"
            )
        if isinstance(value, int) and value <= 0:
            raise FirmwareExtractionError(
                f"node {modules[0].id!r}: attr {name!r} must be positive"
            )
        if isinstance(value, str) and not value:
            raise FirmwareExtractionError(
                f"node {modules[0].id!r}: attr {name!r} must not be empty"
            )
        values[name] = value
    return FirmwareSettings(**values)


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
