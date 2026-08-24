"""L1 consistency gate for firmware Skill projections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph


@dataclass(frozen=True)
class FirmwareConsistencyReport:
    status: str
    reason: str | None
    report_hash: str | None

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def _expected_settings(graph: DesignGraph) -> dict[str, object]:
    modules = [node for node in graph.nodes if node.kind == "firmware.module"]
    if len(modules) != 1:
        raise ValueError("graph must contain exactly one firmware.module node")
    attrs = modules[0].attrs
    defaults: dict[str, object] = {
        "led_blink_period_ms": 1000,
        "log_period_ms": 2000,
        "boot_log_message": f"ACD {graph.graph_id} fw boot target_revision=%s",
    }
    for key in defaults:
        if key in attrs:
            value = attrs[key]
            if key.endswith("_ms"):
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError(f"malformed firmware setting: {key}")
            elif (
                not isinstance(value, str)
                or not value
                or "%s" not in value
            ):
                raise ValueError(f"malformed firmware setting: {key}")
            defaults[key] = value
    return defaults


def check_firmware_graph_consistency(
    graph: DesignGraph, report_path: Path
) -> FirmwareConsistencyReport:
    """Compare a Skill-produced report to graph declarations, fail closed."""
    try:
        loaded: Any = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("firmware report root must be an object")
        raw = cast(dict[str, object], loaded)
        report_hash = canonical_json_sha256(raw)
        if raw.get("graph_id") != graph.graph_id:
            raise ValueError("firmware report graph_id does not match")
        if raw.get("target_revision") != graph.revision:
            raise ValueError("firmware report revision does not match")
        pins = raw.get("pins")
        if not isinstance(pins, list):
            raise ValueError("firmware report pins are missing")
        pin_values = cast(list[object], pins)
        if not all(isinstance(item, dict) for item in pin_values):
            raise ValueError("firmware report pins are malformed")
        actual_pin_values = [cast(dict[str, object], item) for item in pin_values]
        expected_pins = sorted(
            (
                {"node_id": node.id, "gpio": node.attrs.get("gpio"), "net": node.attrs.get("net")}
                for node in graph.nodes
                if node.kind == "firmware.pin_assignment"
            ),
            key=lambda item: str(item["node_id"]),
        )
        actual_pins = sorted(
            actual_pin_values,
            key=lambda item: str(item.get("node_id")),
        )
        if actual_pins != expected_pins:
            raise ValueError("firmware report pin assignments do not match graph")
        if raw.get("settings") != _expected_settings(graph):
            raise ValueError("firmware report settings do not match graph")
        return FirmwareConsistencyReport("pass", None, report_hash)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return FirmwareConsistencyReport("unknown", str(exc), None)


evaluate_firmware_graph_consistency = check_firmware_graph_consistency


__all__ = [
    "FirmwareConsistencyReport",
    "check_firmware_graph_consistency",
    "evaluate_firmware_graph_consistency",
]
