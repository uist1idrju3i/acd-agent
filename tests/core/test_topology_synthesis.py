"""Tests for functional-block topology synthesis."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import pytest

from acd.core.topology_synthesis import TopologySynthesisError, synthesize_topology


def test_gd1_blocks_synthesize_expected_subset() -> None:
    fragment = synthesize_topology(
        [
            "usb_c_cc_termination",
            "i2c_bus_pullup",
            "single_ldo_power_tree",
            "esp32c3_strapping_boot",
            "firmware_pin_map",
            "safety_power_boundary",
        ]
    )
    assert {"R1", "R2", "R4", "R5", "U2", "SW2"} <= {item.refdes for item in fragment.components}
    assert {"net.cc1", "net.cc2", "net.i2c_sda", "net.i2c_scl", "net.p3v3"} <= {
        item.net_id for item in fragment.nets
    }
    assert fragment.constraints


def test_unknown_and_template_less_blocks_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TopologySynthesisError, match="unknown"):
        synthesize_topology(["unknown_block"])
    import acd.core.topology_synthesis as synthesis

    monkeypatch.delitem(synthesis._TEMPLATES, "firmware_pin_map")
    with pytest.raises(TopologySynthesisError, match="検証不能"):
        synthesize_topology(["firmware_pin_map"])
