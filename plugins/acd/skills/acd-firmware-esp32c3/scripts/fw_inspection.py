# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@96ec5b953e54d747cba65f902e9940af80fea083",
# ]
# ///
"""Derive the opt-in firmware inspection sequence from graph projections."""

from __future__ import annotations

from acd.schema.design_graph import DesignGraph
from acd.schema.firmware_inspection import (
    FirmwareInspectionItem,
    FirmwareInspectionSequence,
)
from acd.schema.shipping_inspection import CriterionSource
from fw_graph import FirmwareCapabilityPlan, FirmwareLane, FirmwareSettings


def _source(item_id: str) -> CriterionSource:
    return CriterionSource(
        kind="firmware_projection",
        ref=f"firmware-inspection-sequence.json#{item_id}",
    )


def _component_for_device(graph: DesignGraph, mpn: str) -> str | None:
    return next(
        (
            node.id
            for node in graph.nodes
            if node.kind == "electrical.component" and node.attrs.get("mpn") == mpn
        ),
        None,
    )


def derive_inspection_sequence(
    graph: DesignGraph,
    lane: FirmwareLane,
    plan: FirmwareCapabilityPlan,
    settings: FirmwareSettings,
) -> FirmwareInspectionSequence | None:
    """Derive a deterministic operator-confirmed inspection sequence."""
    if settings.inspection_entry_command is None:
        return None
    items: list[FirmwareInspectionItem] = []
    pins = {pin.role: pin for pin in lane.pins}
    for step in plan.steps:
        if step.capability_id in {"led_blink", "led2_blink"}:
            role = "led2" if step.capability_id == "led2_blink" else "led"
            pin = pins[role]
            item_id = f"{role}-led"
            items.append(
                FirmwareInspectionItem(
                    item_id=item_id,
                    kind="led",
                    subject_node_ids=[pin.node_id],
                    source=_source(item_id),
                    expected_line=(
                        f"ACD_INSPECT led:{role} gpio={pin.gpio} result=executed"
                    ),
                    status="derived",
                )
            )
        if step.device is not None and step.capability_id == "i2c_sensor_read":
            subject = _component_for_device(graph, step.device.mpn)
            if subject is None:
                subject_ids = [
                    pin.node_id
                    for role in ("i2c_sda", "i2c_scl")
                    if (pin := pins.get(role)) is not None
                ]
            else:
                subject_ids = [subject]
            item_id = f"i2c-{step.device.driver_id}"
            items.append(
                FirmwareInspectionItem(
                    item_id=item_id,
                    kind="i2c_probe",
                    subject_node_ids=subject_ids,
                    source=_source(item_id),
                    expected_line=(
                        f"ACD_INSPECT i2c:{step.device.driver_id} "
                        f"addr=0x{step.device.i2c_address:02X} result=pass"
                    ),
                    failure_line=(
                        f"ACD_INSPECT i2c:{step.device.driver_id} "
                        f"addr=0x{step.device.i2c_address:02X} result=fail err=<name>"
                    ),
                    status="derived",
                )
            )
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    power_id = "power-self-check"
    items.append(
        FirmwareInspectionItem(
            item_id=power_id,
            kind="power_self_check",
            subject_node_ids=[module.id],
            status="unknown",
            unknown_reason="no self-measurement source declared in graph",
        )
    )
    serial_id = "serial-echo"
    items.append(
        FirmwareInspectionItem(
            item_id=serial_id,
            kind="serial_echo",
            subject_node_ids=[module.id],
            source=_source(serial_id),
            expected_line="ACD_INSPECT serial result=pass",
            status="derived",
        )
    )
    return FirmwareInspectionSequence(
        schema_version="0.1",
        graph_id=graph.graph_id,
        target_revision=graph.revision,
        entry_command=settings.inspection_entry_command,
        begin_line=f"ACD_INSPECT begin target_revision={graph.revision}",
        end_line=f"ACD_INSPECT end items={len(items)}",
        items=items,
    )


__all__ = ["derive_inspection_sequence"]
