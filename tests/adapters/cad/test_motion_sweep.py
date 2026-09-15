"""Deterministic motion-sweep gate tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import build123d
import pytest

from acd.adapters.cad.motion_sweep import check_motion_sweep
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).parents[3] / "fixtures/mechanism-library/graph.json"


def _lane():
    graph = DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    return extract_mechanical_lane(graph)


def test_fixture_motion_sweep_is_deterministic_and_passes() -> None:
    lane = _lane()
    shell = build123d.Box(36.0, 31.0, 10.0)
    lid = build123d.Pos(0, 0, 12.0) * build123d.Box(36.0, 31.0, 2.0)
    first = check_motion_sweep(lane, shell, lid)
    second = check_motion_sweep(lane, shell, lid)
    assert first == second
    assert {item.status for item in first} == {"pass"}
    assert [(item.feature_id, item.poses_checked) for item in first] == [
        ("mechanism.button", 6),
        ("mechanism.hinge", 25),
    ]


def test_button_component_collision_fails_with_body_id() -> None:
    lane = _lane()
    tall_body = next(
        body for body in lane.component_bodies if body.node_id == "mechanical.component_body.1"
    )
    lane = replace(
        lane,
        component_bodies=tuple(
            replace(tall_body, height_mm=5.0)
            if body.node_id == tall_body.node_id
            else body
            for body in lane.component_bodies
        ),
    )
    button = next(item for item in lane.mechanism_features if item.feature_type == "button")
    assert button.motion_check is not None
    button = replace(
        button,
        x_mm=0.0,
        y_mm=0.0,
        dimensions={**button.dimensions, "travel_clearance_mm": 2.0},
        motion_check=replace(button.motion_check, allowed_contact_ids=()),
    )
    lane = replace(
        lane,
        mechanism_features=tuple(
            button if item.node_id == button.node_id else item
            for item in lane.mechanism_features
        ),
    )
    shell = build123d.Box(36.0, 31.0, 10.0)
    lid = build123d.Pos(0, 0, 12.0) * build123d.Box(36.0, 31.0, 2.0)
    findings = check_motion_sweep(lane, shell, lid)
    finding = next(item for item in findings if item.feature_id == button.node_id)
    assert finding.status == "fail"
    assert "mechanical.component_body.1" in finding.colliding_ids


def test_hinge_tall_component_collision_records_pose_and_body() -> None:
    lane = _lane()
    tall_body = next(
        body for body in lane.component_bodies if body.node_id == "mechanical.component_body.7"
    )
    lane = replace(
        lane,
        component_bodies=tuple(
            replace(tall_body, x_mm=27.0, y_mm=4.0, height_mm=20.0)
            if body.node_id == tall_body.node_id
            else body
            for body in lane.component_bodies
        ),
    )
    hinge = next(
        item for item in lane.mechanism_features if item.feature_type == "hinge"
    )
    assert hinge.motion_check is not None
    hinge = replace(
        hinge,
        motion_check=replace(
            hinge.motion_check,
            allowed_contact_ids=tuple(
                item
                for item in hinge.motion_check.allowed_contact_ids
                if item != tall_body.node_id
            ),
        ),
    )
    lane = replace(
        lane,
        mechanism_features=tuple(
            hinge if item.node_id == hinge.node_id else item
            for item in lane.mechanism_features
        ),
    )
    shell = build123d.Box(36.0, 31.0, 10.0)
    lid = build123d.Pos(0, 0, 12.0) * build123d.Box(36.0, 31.0, 2.0)
    finding = next(
        item
        for item in check_motion_sweep(lane, shell, lid)
        if item.feature_id == "mechanism.hinge"
    )
    assert finding.status == "fail"
    assert finding.worst_pose == 90.0
    assert tall_body.node_id in finding.colliding_ids


def test_boolean_failure_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    lane = _lane()
    shell = build123d.Box(36.0, 31.0, 10.0)
    lid = build123d.Pos(0, 0, 12.0) * build123d.Box(36.0, 31.0, 2.0)

    def fail_intersection(_self: Any, _other: Any) -> Any:
        raise RuntimeError("synthetic boolean failure")

    monkeypatch.setattr(build123d.Solid, "__and__", fail_intersection)
    monkeypatch.setattr(build123d.Compound, "__and__", fail_intersection)
    findings = check_motion_sweep(lane, shell, lid)
    assert {item.status for item in findings} == {"unknown"}
