from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acd_core.electrical import ElectricalLane, GraphExtractionError, extract_electrical_lane
from acd_core.fab import load_fab_profile
from acd_core.routing_width import derive_net_widths, group_netclasses
from acd_schema import DesignGraph

ROOT = Path(__file__).parents[3]
FIXTURE = ROOT / "fixtures/golden-design-1/graph.json"
PROFILE = load_fab_profile(ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json")


def _lane() -> ElectricalLane:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return extract_electrical_lane(DesignGraph.model_validate(data))


def test_missing_width_basis_fails_closed() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    net = next(node for node in data["nodes"] if node["kind"] == "electrical.net")
    del net["attrs"]["width_basis"]
    with pytest.raises(GraphExtractionError, match="width_basis"):
        extract_electrical_lane(DesignGraph.model_validate(data))


@pytest.mark.parametrize(
    "removed",
    [
        "outer_copper_thickness_um",
        "copper_thickness_source",
        "allowable_temperature_rise_k",
        "ipc2221_external_k",
    ],
)
def test_current_basis_missing_board_input_fails_closed(removed: str) -> None:
    lane = _lane()
    board = replace(lane.board, **{removed: None})
    with pytest.raises(GraphExtractionError):
        derive_net_widths(replace(lane, board=board), 0.1)


def test_netclass_grouping_is_deterministic() -> None:
    requirements = derive_net_widths(_lane(), 0.1)
    grouped = group_netclasses(requirements)
    assert grouped == (
        (
            "ACD_0150um",
            (
                "+3V3",
                "BOOT",
                "CC1",
                "CC2",
                "EN",
                "GND",
                "I2C_SCL",
                "I2C_SDA",
                "LED",
                "LED_A",
                "UART_RX",
                "UART_TX",
                "USB_D+",
                "USB_D-",
                "VBUS_5V",
            ),
            0.15,
        ),
    )
