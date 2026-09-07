"""Requirement-to-firmware-sequence coverage check (fail-closed diagnostic).

The firmware capability registry declares which actions, pin roles, and
emitted triggers a design may use. This module compares the declared graph
against that registry so that dropped requirement content — an LED indicator
no sequence step toggles, a transition trigger no used capability emits, a
pin role nothing consumes — fails closed with an actionable finding instead
of silently degrading the firmware. The check is purely graph and registry
based; it never reads requirement prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from acd.core.firmware_lane import extract_firmware_lane
from acd.schema.design_graph import DesignGraph
from acd.schema.firmware_capability import FirmwareCapabilityRegistryDocument

FirmwareCoverageCode = Literal[
    "led_indicator_untargeted",
    "trigger_unemitted",
    "pin_role_unconsumed",
    "action_unregistered",
]


@dataclass(frozen=True)
class FirmwareCoverageFinding:
    """One coverage gap between the declared graph and the registry."""

    code: FirmwareCoverageCode
    node_id: str
    message: str


@dataclass(frozen=True)
class FirmwareCoverageReport:
    """Aggregate coverage verdict; ``fail`` when any finding exists."""

    status: Literal["pass", "fail"]
    findings: tuple[FirmwareCoverageFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [
                {
                    "code": finding.code,
                    "node_id": finding.node_id,
                    "message": finding.message,
                }
                for finding in self.findings
            ],
        }


def check_firmware_coverage(
    graph: DesignGraph,
    registry: FirmwareCapabilityRegistryDocument,
) -> FirmwareCoverageReport:
    """Fail closed on declared firmware content the registry cannot cover.

    ``GraphExtractionError`` propagates: a graph the firmware lane cannot
    even extract is reported by the extraction contract, not by coverage
    findings.
    """
    lane = extract_firmware_lane(graph)
    capability_by_action = {
        action: capability
        for capability in registry.capabilities
        for action in capability.actions
    }
    sequence_actions = {step.action for step in lane.sequence_steps}
    used_capabilities = {
        capability_by_action[action].capability_id: capability_by_action[action]
        for action in sequence_actions
        if action in capability_by_action
    }

    findings: list[FirmwareCoverageFinding] = []

    for step in lane.sequence_steps:
        if step.action not in capability_by_action:
            findings.append(
                FirmwareCoverageFinding(
                    code="action_unregistered",
                    node_id=step.node_id,
                    message=(
                        f"firmware sequence step {step.node_id!r} uses action "
                        f"{step.action!r} which no registry capability declares; "
                        "use a registered action or register a capability "
                        "declaring it via acd-firmware-capability-entry"
                    ),
                )
            )

    step_targets = {step.target for step in lane.sequence_steps}
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.component":
            continue
        if node.attrs.get("led_indicator") is not True:
            continue
        if node.id in step_targets:
            continue
        findings.append(
            FirmwareCoverageFinding(
                code="led_indicator_untargeted",
                node_id=node.id,
                message=(
                    f"LED indicator {node.id!r} is not targeted by any "
                    f"firmware.sequence_step; add a step (e.g. action "
                    f"'toggle_led' target {node.id!r}) or remove the "
                    "led_indicator declaration"
                ),
            )
        )

    emitted_triggers = {
        trigger
        for capability in used_capabilities.values()
        for trigger in capability.emits_triggers
    }
    for transition in lane.transitions:
        if transition.trigger in emitted_triggers:
            continue
        emitters = sorted(
            capability.capability_id
            for capability in registry.capabilities
            if transition.trigger in capability.emits_triggers
        )
        if emitters:
            hint = (
                "add a sequence step using a capability that emits it "
                f"(registered emitters: {', '.join(emitters)})"
            )
        else:
            hint = (
                "no registered capability emits this trigger; register one "
                "via acd-firmware-capability-entry"
            )
        findings.append(
            FirmwareCoverageFinding(
                code="trigger_unemitted",
                node_id=transition.node_id,
                message=(
                    f"firmware state transition {transition.node_id!r} uses "
                    f"trigger {transition.trigger!r} which no capability used "
                    f"by the firmware sequence emits; {hint}"
                ),
            )
        )

    consumed_roles = set(registry.pin_role_order) | {
        role
        for capability in used_capabilities.values()
        for role in capability.required_pin_roles
    }
    registered_roles = ", ".join(sorted(registry.pin_role_order))
    for pin in lane.pin_assignments:
        role = pin.net.removeprefix("net.")
        if role in consumed_roles:
            continue
        findings.append(
            FirmwareCoverageFinding(
                code="pin_role_unconsumed",
                node_id=pin.node_id,
                message=(
                    f"firmware pin {pin.node_id!r} role {role!r} is not "
                    "consumed by any firmware capability and is not a "
                    f"registered pin role (registered: {registered_roles}); "
                    "rename the net to a registered role or register a "
                    "capability consuming it via acd-firmware-capability-entry"
                ),
            )
        )

    findings.sort(key=lambda finding: (finding.code, finding.node_id))
    return FirmwareCoverageReport(
        status="fail" if findings else "pass",
        findings=tuple(findings),
    )


__all__ = [
    "FirmwareCoverageCode",
    "FirmwareCoverageFinding",
    "FirmwareCoverageReport",
    "check_firmware_coverage",
]
