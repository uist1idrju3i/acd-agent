"""Tests for troubleshooting knowledge derivation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.troubleshooting import (
    derive_troubleshooting_knowledge,
    load_pin_macros,
    parse_pin_macros,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.troubleshooting import (
    TroubleshootingEntry,
    TroubleshootingExpectation,
    TroubleshootingKnowledge,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = REPO_ROOT / "fixtures/golden-design-1/graph.json"

PINS_HEADER = """\
#pragma once

#define ACD_TARGET_REVISION "r1"

#define ACD_PIN_LED 7
#define ACD_PIN_I2C_SDA 8
#define ACD_PIN_I2C_SCL 9
#define ACD_PIN_UART_TX 21
#define ACD_PIN_UART_RX 20
#define ACD_PIN_BOOT 9
#define ACD_PIN_USB_DN 18
#define ACD_PIN_USB_DP 19

#define ACD_SHT40_I2C_ADDRESS 0x44
#define ACD_LED_BLINK_PERIOD_MS 1000
#define ACD_LOG_PERIOD_MS 2000
"""


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )


def test_all_entries_are_derived_from_complete_inputs() -> None:
    knowledge = derive_troubleshooting_knowledge(
        _graph(), pin_macros=parse_pin_macros(PINS_HEADER)
    )

    assert knowledge.graph_id == "golden-design-1"
    assert knowledge.target_revision == "r1"
    assert knowledge.pass_evidence is False
    assert knowledge.unknown_entries() == ()
    entry_ids = [entry.entry_id for entry in knowledge.entries]
    assert entry_ids == sorted(entry_ids)
    assert "ts-led-not-blinking" in entry_ids
    led = next(e for e in knowledge.entries if e.entry_id == "ts-led-not-blinking")
    expected = {item.description: item.expected for item in led.expectations}
    assert expected["Status LED GPIO number"] == "7"
    assert expected["LED blink period in milliseconds"] == "1000"


def test_power_rail_expectations_come_from_the_graph() -> None:
    knowledge = derive_troubleshooting_knowledge(
        _graph(), pin_macros=parse_pin_macros(PINS_HEADER)
    )

    entry = next(
        e for e in knowledge.entries if e.entry_id == "ts-power-rail-out-of-range"
    )
    values = {item.citation: item.expected for item in entry.expectations}
    assert values["net.p3v3"] == "3.3 V"
    assert values["net.vbus_5v"] == "5 V"


def test_missing_pin_projection_yields_unknown_entries() -> None:
    knowledge = derive_troubleshooting_knowledge(_graph(), pin_macros={})

    unknown_ids = {entry.entry_id for entry in knowledge.unknown_entries()}
    assert "ts-led-not-blinking" in unknown_ids
    assert "ts-no-serial-log" in unknown_ids
    assert "ts-power-rail-out-of-range" not in unknown_ids
    for entry in knowledge.unknown_entries():
        assert entry.reason is not None


def test_graph_without_power_rail_yields_unknown_power_entry() -> None:
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    for node in payload["nodes"]:
        if node["kind"] == "electrical.net":
            node["attrs"].pop("power_rail", None)
    graph = DesignGraph.model_validate(payload)

    knowledge = derive_troubleshooting_knowledge(
        graph, pin_macros=parse_pin_macros(PINS_HEADER)
    )

    entry = next(
        e for e in knowledge.entries if e.entry_id == "ts-power-rail-out-of-range"
    )
    assert entry.status == "unknown"
    assert entry.reason == "graph declares no power rail net"


def test_load_pin_macros_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_pin_macros(tmp_path / "acd_pins.h") == {}


def test_derived_entry_cannot_carry_unknown_expectation() -> None:
    with pytest.raises(ValueError, match="unknown expectation"):
        TroubleshootingEntry(
            entry_id="ts-x",
            symptom="symptom",
            checks=["check"],
            expectations=[
                TroubleshootingExpectation(
                    description="value", expected="unknown", citation="node"
                )
            ],
            status="derived",
        )


def test_unknown_entry_requires_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        TroubleshootingEntry(
            entry_id="ts-x",
            symptom="symptom",
            checks=["check"],
            expectations=[
                TroubleshootingExpectation(
                    description="value", expected="unknown", citation="node"
                )
            ],
            status="unknown",
        )


def test_entries_must_be_sorted() -> None:
    def entry(entry_id: str) -> TroubleshootingEntry:
        return TroubleshootingEntry(
            entry_id=entry_id,
            symptom="symptom",
            checks=["check"],
            expectations=[
                TroubleshootingExpectation(
                    description="value", expected="1", citation="node"
                )
            ],
            status="derived",
        )

    with pytest.raises(ValueError, match="sorted"):
        TroubleshootingKnowledge(
            graph_id="g",
            target_revision="r1",
            entries=[entry("ts-b"), entry("ts-a")],
        )
