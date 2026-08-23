"""Deterministic routing connectivity observation tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from acd.adapters.freerouting.ses import SesImportError, parse_ses
from acd.core.board_model import (
    BoardModel,
    BoardNet,
    ComponentPlacement,
    FootprintShape,
    PadShape,
    RoutedDesign,
    RoutedVia,
    RoutedWire,
)
from acd.pipeline.gate_evidence import (
    unavailable_observation,
    write_gate_evidence,
    write_gate_evidence_or_unavailable,
)
from acd.pipeline.routing_connectivity import measure_routing_connectivity


def _board() -> BoardModel:
    def pad(number: str, x: float) -> PadShape:
        return PadShape(
            number=number,
            x_mm=x,
            y_mm=0.0,
            rotation_deg=0.0,
            shape="rect",
            size_x_mm=1.0,
            size_y_mm=1.0,
            through_hole=False,
            drill_mm=None,
            on_front=True,
            on_back=False,
        )

    def footprint(number: str) -> FootprintShape:
        return FootprintShape(
            library_ref="Test:Footprint",
            pads=(pad(number, 0.0),),
        )
    return BoardModel(
        width_mm=20.0,
        height_mm=20.0,
        layers=2,
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_clearance_mm=0.25,
        placements=(
            ComponentPlacement("J1", footprint("1"), 2.0, 2.0, 0.0),
            ComponentPlacement("J2", footprint("1"), 8.0, 2.0, 0.0),
            ComponentPlacement("J3", footprint("1"), 2.0, 8.0, 0.0),
            ComponentPlacement("J4", footprint("1"), 8.0, 8.0, 0.0),
        ),
        nets=(
            BoardNet("GND", (("J3", "1"), ("J4", "1"))),
            BoardNet("VCC", (("J1", "1"), ("J2", "1"))),
        ),
    )


def _connected_routes() -> RoutedDesign:
    return RoutedDesign(
        wires=(
            RoutedWire("GND", "B.Cu", 0.2, ((2.0, 8.0), (8.0, 8.0))),
            RoutedWire("VCC", "F.Cu", 0.2, ((2.0, 2.0), (5.0, 2.0))),
            RoutedWire("VCC", "B.Cu", 0.2, ((5.0, 2.0), (8.0, 2.0))),
        ),
        vias=(RoutedVia("VCC", 5.0, 2.0),),
    )


def test_routing_connectivity_reports_connected_nets() -> None:
    result = measure_routing_connectivity(_board(), _connected_routes())
    nets = cast(list[dict[str, object]], result["nets"])
    assert result["status"] == "pass"
    assert all(net["unconnected_pad_pairs"] == [] for net in nets)
    assert all(net["unattached_pads"] == [] for net in nets)


def test_routing_connectivity_reports_unconnected_pad_pair() -> None:
    routes = _connected_routes()
    routes = RoutedDesign(
        wires=tuple(wire for wire in routes.wires if wire.net != "GND"),
        vias=routes.vias,
    )
    result = measure_routing_connectivity(_board(), routes)
    nets = cast(list[dict[str, object]], result["nets"])
    gnd = next(net for net in nets if net["net"] == "GND")
    assert result["status"] == "fail"
    assert gnd["unconnected_pad_pairs"] == [[["J3", "1"], ["J4", "1"]]]
    assert gnd["unattached_pads"] == [["J3", "1"], ["J4", "1"]]


def test_routing_connectivity_accepts_duplicate_pad_shapes() -> None:
    board = _board()
    j3 = next(placement for placement in board.placements if placement.refdes == "J3")
    pad = j3.footprint.pads[0]
    duplicate = replace(pad, x_mm=0.2)
    duplicate_footprint = replace(j3.footprint, pads=(pad, duplicate))
    placements = tuple(
        replace(placement, footprint=duplicate_footprint)
        if placement.refdes == "J3"
        else placement
        for placement in board.placements
    )
    result = measure_routing_connectivity(
        replace(board, placements=placements),
        _connected_routes(),
    )
    assert result["status"] == "pass"


def test_routing_connectivity_is_deterministic() -> None:
    first = measure_routing_connectivity(_board(), _connected_routes())
    second = measure_routing_connectivity(_board(), _connected_routes())
    first_json = json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    second_json = json.dumps(second, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert first_json == second_json


def test_malformed_ses_is_recorded_as_unavailable(tmp_path: Path) -> None:
    with pytest.raises(SesImportError):
        parse_ses("(session (routes (resolution mm 1)))")
    path = write_gate_evidence(
        tmp_path,
        "routing-connectivity.json",
        target_revision="r1",
        gate="routing_connectivity",
        status="unavailable",
        message="routing connectivity diagnostic unavailable; not gate authority",
        observation=unavailable_observation(
            SesImportError("session has no network_out section (fail-closed)")
        ),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "unavailable"
    assert payload["observation"]["reason"].startswith("SesImportError:")


def test_evidence_writer_failure_is_recorded_as_unavailable(tmp_path: Path) -> None:
    def fail_writer() -> Path:
        raise RuntimeError("evidence serialization failed")

    assert (
        write_gate_evidence_or_unavailable(
            tmp_path,
            "routing-connectivity.json",
            target_revision="r1",
            gate="routing_connectivity",
            message="routing connectivity diagnostic unavailable; not gate authority",
            write_evidence=fail_writer,
        )
        is None
    )
    payload = json.loads(
        (tmp_path / "gate-evidence" / "routing-connectivity.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "unavailable"
    assert payload["observation"]["reason"] == "RuntimeError: evidence serialization failed"
