"""KiCad project netclass projection tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from acd_adapter_kicad.project import _project_settings  # pyright: ignore[reportPrivateUsage]
from acd_core.electrical import extract_electrical_lane
from acd_core.fab import load_fab_profile
from acd_core.routing_width import derive_net_widths, group_netclasses
from acd_schema import DesignGraph

ROOT = Path(__file__).parents[4]
FIXTURE = ROOT / "fixtures/golden-design-1/graph.json"
PROFILE = load_fab_profile(ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json")


def test_project_settings_projects_class_membership_and_widths() -> None:
    lane = extract_electrical_lane(
        DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    )
    minimum = float(PROFILE.data["capabilities"]["min_track_width"]["value"])
    settings = _project_settings(
        "gd1.kicad_pro",
        lane.board,
        PROFILE,
        group_netclasses(derive_net_widths(lane, minimum)),
    )
    net_settings = cast(dict[str, object], settings["net_settings"])
    classes = cast(list[dict[str, object]], net_settings["classes"])
    patterns = cast(list[dict[str, str]], net_settings["netclass_patterns"])
    assert classes == [
        {
            "name": "Default",
            "clearance": 0.15,
            "track_width": 0.15,
            "via_diameter": 0.6,
            "via_drill": 0.3,
        },
        {
            "name": "ACD_0150um",
            "clearance": 0.15,
            "track_width": 0.15,
            "via_diameter": 0.6,
            "via_drill": 0.3,
        }
    ]
    assert len(patterns) == len(lane.nets)
    assert {item["pattern"] for item in patterns} == {net.name for net in lane.nets}


def test_project_settings_missing_netclasses_fails_closed() -> None:
    lane = extract_electrical_lane(
        DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    )
    with pytest.raises(ValueError, match="netclass declarations"):
        _project_settings("gd1.kicad_pro", lane.board, PROFILE)
