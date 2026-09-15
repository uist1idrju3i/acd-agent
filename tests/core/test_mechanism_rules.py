"""Mechanism feature extraction and deterministic rule tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.electrical import GraphExtractionError
from acd.core.mechanical import extract_mechanical_lane
from acd.core.mechanism_rules import check_mechanism_features
from acd.core.rationale import check_rationale_coverage
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode
from acd.schema.rationale import RationaleDocument

FIXTURE = Path(__file__).parents[2] / "fixtures/golden-design-1/graph.json"
MECHANISM_FIXTURE = Path(__file__).parents[2] / "fixtures/mechanism-library"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _feature(
    node_id: str,
    feature_type: str,
    dimensions: dict[str, float],
    *,
    extra: dict[str, AttrValue] | None = None,
) -> GraphNode:
    attrs: dict[str, AttrValue] = {
        "feature_type": feature_type,
        "face": "top",
        "x_mm": 15.0,
        "y_mm": 12.5,
        "rotation_deg": 0.0,
        **dimensions,
        **(extra or {}),
    }
    if feature_type == "hinge":
        attrs["motion_check"] = {
            "step_deg": 5.0,
            "sweep_margin_mm": 0.2,
            "allowed_contact_ids": [],
        }
    elif feature_type == "button":
        attrs["motion_check"] = {
            "step_mm": 0.1,
            "sweep_margin_mm": 0.2,
            "allowed_contact_ids": [],
        }
    return GraphNode(
        id=node_id,
        kind="mechanism_feature",
        attrs=attrs,
        depends_on=["mechanical.enclosure.gd1"],
    )


def _with(*features: GraphNode) -> DesignGraph:
    graph = _graph()
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "material": "PA"}})
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": [*nodes, *features]})


def test_no_mechanism_features_are_opt_in() -> None:
    lane = extract_mechanical_lane(_graph())
    assert lane.mechanism_features == ()
    assert check_mechanism_features(lane) == ()


def test_mechanism_fixture_has_rationale_coverage() -> None:
    graph = DesignGraph.model_validate_json(
        (MECHANISM_FIXTURE / "graph.json").read_text(encoding="utf-8")
    )
    rationale = RationaleDocument.model_validate_json(
        (MECHANISM_FIXTURE / "rationale.json").read_text(encoding="utf-8")
    )
    report = check_rationale_coverage(graph, rationale)
    assert report.status == "pass"
    assert len(extract_mechanical_lane(graph).mechanism_features) == 6


def test_all_mechanism_features_extract_and_pass_rules() -> None:
    graph = _with(
        _feature(
            "mechanism.snap",
            "snap_fit",
            {
                "hook_length_mm": 8.0,
                "hook_thickness_mm": 0.8,
                "undercut_mm": 0.5,
                "insertion_angle_deg": 30.0,
                "retention_angle_deg": 15.0,
                "deflection_mm": 0.4,
            },
        ),
        _feature(
            "mechanism.hinge",
            "hinge",
            {
                "pin_diameter_mm": 2.0,
                "knuckle_width_mm": 3.0,
                "knuckle_count": 3,
                "clearance_mm": 0.15,
                "swing_deg": 120.0,
            },
        ),
        _feature(
            "mechanism.button",
            "button",
            {
                "cap_diameter_mm": 7.0,
                "stroke_mm": 0.5,
                "travel_clearance_mm": 1.0,
                "web_thickness_mm": 0.8,
            },
            extra={"refdes": "SW1"},
        ),
        _feature(
            "mechanism.light",
            "light_pipe",
            {"diameter_mm": 2.1, "length_mm": 4.0},
            extra={"led_refdes": "D1"},
        ),
        _feature(
            "mechanism.boss",
            "boss",
            {
                "outer_diameter_mm": 4.0,
                "hole_diameter_mm": 1.0,
                "height_mm": 4.0,
                "fillet_mm": 0.2,
            },
        ),
        _feature(
            "mechanism.rib",
            "rib",
            {"length_mm": 8.0, "height_mm": 4.0, "thickness_mm": 1.0, "draft_deg": 1.0},
        ),
    )
    lane = extract_mechanical_lane(graph)
    assert len(lane.mechanism_features) == 6
    assert {item.status for item in check_mechanism_features(lane)} == {"pass"}


@pytest.mark.parametrize(
    ("feature_type", "dimensions", "expected_rule"),
    [
        (
            "snap_fit",
            {
                "hook_length_mm": 2.0,
                "hook_thickness_mm": 2.0,
                "undercut_mm": 0.5,
                "insertion_angle_deg": 30.0,
                "retention_angle_deg": 15.0,
                "deflection_mm": 1.0,
            },
            "snap_fit_strain",
        ),
        (
            "rib",
            {"length_mm": 5.0, "height_mm": 3.0, "thickness_mm": 2.0, "draft_deg": 1.0},
            "rib_geometry",
        ),
        (
            "boss",
            {
                "outer_diameter_mm": 4.0,
                "hole_diameter_mm": 3.8,
                "height_mm": 3.0,
                "fillet_mm": 0.2,
            },
            "boss_wall",
        ),
    ],
)
def test_rule_violations_fail(
    feature_type: str, dimensions: dict[str, float], expected_rule: str
) -> None:
    lane = extract_mechanical_lane(_with(_feature("mechanism.bad", feature_type, dimensions)))
    finding = check_mechanism_features(lane)[0]
    assert finding.rule_id == expected_rule
    assert finding.status == "fail"


def test_unknown_material_is_unknown() -> None:
    graph = _with(
        _feature(
            "mechanism.snap",
            "snap_fit",
            {
                "hook_length_mm": 8.0,
                "hook_thickness_mm": 0.8,
                "undercut_mm": 0.5,
                "insertion_angle_deg": 30.0,
                "retention_angle_deg": 15.0,
                "deflection_mm": 0.4,
            },
        )
    )
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, "material": "UNOBTAINIUM"}})
        if node.kind == "mechanical.enclosure"
        else node
        for node in graph.nodes
    ]
    finding = check_mechanism_features(
        extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))
    )[0]
    assert finding.status == "unknown"


def test_light_pipe_requires_led_reference() -> None:
    with pytest.raises(GraphExtractionError, match="does not reference an LED"):
        extract_mechanical_lane(
            _with(
                _feature(
                    "mechanism.light",
                    "light_pipe",
                    {"diameter_mm": 2.1, "length_mm": 4.0},
                    extra={"led_refdes": "SW1"},
                )
            )
        )


def test_movable_feature_requires_motion_check() -> None:
    graph = _with(
        _feature(
            "mechanism.hinge",
            "hinge",
            {
                "pin_diameter_mm": 2.0,
                "knuckle_width_mm": 3.0,
                "knuckle_count": 3,
                "clearance_mm": 0.15,
                "swing_deg": 120.0,
            },
        )
    )
    node = graph.node_by_id("mechanism.hinge")
    attrs = dict(node.attrs)
    attrs.pop("motion_check")
    graph = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": attrs})
                if item.id == node.id
                else item
                for item in graph.nodes
            ]
        }
    )
    with pytest.raises(GraphExtractionError, match="motion_check"):
        extract_mechanical_lane(graph)
