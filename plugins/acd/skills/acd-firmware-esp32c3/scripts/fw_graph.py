# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@adc2d4f9b1cd10ab4748e53c5d4b222e410f15d4",
# ]
# ///
"""Typed extraction of the firmware lane from a design graph.

The design graph is the only source of firmware pin assignments. Projections
consume these views; missing or malformed attributes fail closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.core.firmware_capability import (
    FirmwareCapabilityRegistry,
    load_firmware_capability_registry,
)
from acd.schema.design_graph import DesignGraph


class FirmwareExtractionError(ValueError):
    """Raised when the firmware lane cannot be extracted (fail-closed)."""


@dataclass(frozen=True)
class FirmwarePinView:
    node_id: str
    gpio: int
    net_id: str
    role: str


@dataclass(frozen=True)
class FirmwareDeviceView:
    mpn: str
    driver_id: str
    i2c_address: int
    measurement_command: int


@dataclass(frozen=True)
class FirmwareCapabilityStep:
    capability_id: str
    action: str
    step_index: int
    device: FirmwareDeviceView | None = None


@dataclass(frozen=True)
class FirmwareCapabilityPlan:
    steps: tuple[FirmwareCapabilityStep, ...]
    pin_role_order: tuple[str, ...]
    required_pin_roles: tuple[str, ...]
    registry_hash: str
    registry_path: str


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

    def gpio_for_role(self, role: str) -> int:
        for pin in self.pins:
            if pin.role == role:
                return pin.gpio
        raise FirmwareExtractionError(f"no firmware pin assignment for role {role!r}")


@dataclass(frozen=True)
class FirmwareSettings:
    boot_log_message: str
    led_blink_period_ms: int = 1000
    log_period_ms: int = 2000


def validate_boot_log_message(value: object) -> str:
    if not isinstance(value, str):
        raise FirmwareExtractionError("boot_log_message must be a string")
    if (
        not value
        or value.count("%s") != 1
        or any(
            character in value
            for character in ('"', "\\", "\r", "\n")
        )
        or any(
            character == "%"
            and value[index : index + 2] != "%s"
            for index, character in enumerate(value)
        )
    ):
        raise FirmwareExtractionError(
            "boot_log_message must be a C string literal template with exactly "
            "one %s and no quotes, backslashes, newlines, or other percent directives"
        )
    return value


def extract_firmware_settings(graph: DesignGraph) -> FirmwareSettings:
    modules = [node for node in graph.nodes if node.kind == "firmware.module"]
    if len(modules) != 1:
        raise FirmwareExtractionError("graph must contain exactly one firmware.module node")
    attrs = modules[0].attrs
    values: dict[str, object] = {}
    for name, default in (
        ("led_blink_period_ms", 1000),
        ("log_period_ms", 2000),
        ("boot_log_message", f"ACD {graph.graph_id} fw boot target_revision=%s"),
    ):
        value = attrs.get(name, default)
        if name == "boot_log_message":
            value = validate_boot_log_message(value)
        else:
            if isinstance(value, bool) or not isinstance(value, type(default)):
                raise FirmwareExtractionError(
                    f"node {modules[0].id!r}: attr {name!r} is malformed"
                )
            if isinstance(value, int) and value <= 0:
                raise FirmwareExtractionError(
                    f"node {modules[0].id!r}: attr {name!r} must be positive"
                )
        values[name] = value
    return FirmwareSettings(
        led_blink_period_ms=cast(int, values["led_blink_period_ms"]),
        log_period_ms=cast(int, values["log_period_ms"]),
        boot_log_message=cast(str, values["boot_log_message"]),
    )


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
        pins.append(
            FirmwarePinView(
                node_id=node.id,
                gpio=gpio,
                net_id=net,
                role=net.removeprefix("net."),
            )
        )
    if not pins:
        raise FirmwareExtractionError("graph has no firmware.pin_assignment nodes")
    gpios = [pin.gpio for pin in pins]
    if len(set(gpios)) != len(gpios):
        raise FirmwareExtractionError("duplicate GPIO in firmware pin assignments")
    nets = [pin.net_id for pin in pins]
    if len(set(nets)) != len(nets):
        raise FirmwareExtractionError("duplicate net in firmware pin assignments")
    return FirmwareLane(pins=tuple(sorted(pins, key=lambda p: p.node_id)))


def resolve_firmware_capability_plan(
    graph: DesignGraph,
    lane: FirmwareLane,
    registry: FirmwareCapabilityRegistry | None = None,
) -> FirmwareCapabilityPlan:
    registry = registry or load_firmware_capability_registry()
    capabilities = {
        action: capability
        for capability in registry.capabilities
        for action in capability.actions
    }
    devices = {device.mpn: device for device in registry.devices}
    nodes = {node.id: node for node in graph.nodes}
    raw_steps = [
        node for node in graph.nodes if node.kind == "firmware.sequence_step"
    ]
    seen_indexes: set[int] = set()
    steps: list[FirmwareCapabilityStep] = []
    for node in raw_steps:
        step_index = node.attrs.get("step_index")
        if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index <= 0:
            raise FirmwareExtractionError(
                f"firmware sequence step {node.id!r} has an invalid step_index"
            )
        if step_index in seen_indexes:
            raise FirmwareExtractionError(
                f"duplicate firmware sequence step index: {step_index}"
            )
        seen_indexes.add(step_index)
        action = node.attrs.get("action")
        if not isinstance(action, str) or not action:
            raise FirmwareExtractionError(
                f"firmware sequence step {node.id!r} has no action"
            )
        capability = capabilities.get(action)
        if capability is None:
            raise FirmwareExtractionError(
                f"firmware action {action!r} is not registered in "
                f"{registry.path}"
            )
        missing_roles = sorted(
            role
            for role in capability.required_pin_roles
            if not any(pin.role == role for pin in lane.pins)
        )
        if missing_roles:
            raise FirmwareExtractionError(
                f"firmware action {action!r} capability {capability.capability_id!r} "
                f"is missing pin roles: {', '.join(missing_roles)}"
            )
        device: FirmwareDeviceView | None = None
        if capability.requires_device:
            target = node.attrs.get("target")
            if not isinstance(target, str) or not target:
                raise FirmwareExtractionError(
                    f"firmware action {action!r} capability "
                    f"{capability.capability_id!r} requires a target device"
                )
            target_node = nodes.get(target)
            if target_node is None or target_node.kind != "electrical.component":
                raise FirmwareExtractionError(
                    f"firmware action {action!r} target {target!r} is not an "
                    "electrical component"
                )
            mpn = target_node.attrs.get("mpn")
            if not isinstance(mpn, str) or not mpn:
                raise FirmwareExtractionError(
                    f"firmware action {action!r} target {target!r} has no mpn"
                )
            registered = devices.get(mpn)
            if registered is None:
                raise FirmwareExtractionError(
                    f"firmware device {mpn!r} is not registered in {registry.path}"
                )
            device = FirmwareDeviceView(
                mpn=registered.mpn,
                driver_id=registered.driver_id,
                i2c_address=registered.i2c_address,
                measurement_command=registered.measurement_command,
            )
        steps.append(
            FirmwareCapabilityStep(
                capability_id=capability.capability_id,
                action=action,
                step_index=step_index,
                device=device,
            )
        )
    if not steps:
        raise FirmwareExtractionError("graph has no firmware.sequence_step nodes")
    ordered_steps = tuple(sorted(steps, key=lambda step: step.step_index))
    expected_indexes = list(range(1, len(ordered_steps) + 1))
    if [step.step_index for step in ordered_steps] != expected_indexes:
        raise FirmwareExtractionError(
            "firmware sequence step_index must be a contiguous 1-based sequence"
        )
    capability_by_id = {
        capability.capability_id: capability for capability in registry.capabilities
    }
    required_roles = {
        role
        for step in ordered_steps
        for role in capability_by_id[step.capability_id].required_pin_roles
    }
    role_order = {
        role: index for index, role in enumerate(registry.document.pin_role_order)
    }
    required_pin_roles = tuple(
        sorted(
            required_roles,
            key=lambda role: (role_order.get(role, len(role_order)), role),
        )
    )
    return FirmwareCapabilityPlan(
        steps=ordered_steps,
        pin_role_order=tuple(registry.document.pin_role_order),
        required_pin_roles=required_pin_roles,
        registry_hash=registry.registry_hash,
        registry_path=Path(
            os.path.relpath(
                registry.path.resolve(), Path(__file__).resolve().parents[5]
            )
        ).as_posix(),
    )
