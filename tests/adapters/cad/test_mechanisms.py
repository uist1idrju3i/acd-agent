"""Real build123d construction tests for mechanism primitives."""

from __future__ import annotations

from pathlib import Path

from acd.adapters.cad.mechanisms import (
    apply_mechanism_features,
    build_boss,
    build_button,
    build_hinge,
    build_light_pipe,
    build_rib,
    build_snap_fit,
)
from acd.core.mechanical.mechanical import MechanismFeatureView, extract_mechanical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).parents[3] / "fixtures/mechanism-library/graph.json"


def _view(feature_type: str, dimensions: dict[str, float]) -> MechanismFeatureView:
    return MechanismFeatureView(
        node_id=f"mechanism.{feature_type}",
        feature_type=feature_type,
        face="top",
        x_mm=0.0,
        y_mm=0.0,
        rotation_deg=0.0,
        dimensions=dimensions,
        enclosure_node_id="enclosure",
    )


def test_build123d_mechanism_builders_create_real_solids() -> None:
    views = (
        (
            build_snap_fit,
            _view(
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
        ),
        (
            build_hinge,
            _view(
                "hinge",
                {
                    "pin_diameter_mm": 2.0,
                    "knuckle_width_mm": 3.0,
                    "knuckle_count": 3,
                    "clearance_mm": 0.15,
                    "swing_deg": 120.0,
                },
            ),
        ),
        (
            build_button,
            _view(
                "button",
                {
                    "cap_diameter_mm": 7.0,
                    "stroke_mm": 0.5,
                    "travel_clearance_mm": 1.0,
                    "web_thickness_mm": 0.8,
                },
            ),
        ),
        (
            build_light_pipe,
            _view("light_pipe", {"diameter_mm": 2.1, "length_mm": 4.0}),
        ),
        (
            build_boss,
            _view(
                "boss",
                {
                    "outer_diameter_mm": 4.0,
                    "hole_diameter_mm": 1.5,
                    "height_mm": 4.0,
                    "fillet_mm": 0.2,
                },
            ),
        ),
        (
            build_rib,
            _view(
                "rib",
                {"length_mm": 8.0, "height_mm": 4.0, "thickness_mm": 1.0, "draft_deg": 1.0},
            ),
        ),
    )
    for builder, view in views:
        solid = builder(view)
        assert solid.is_valid
        assert solid.volume > 0


def test_mechanism_fixture_projects_valid_shell_and_lid() -> None:
    build123d = __import__("build123d")
    graph = DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    shell, lid = apply_mechanism_features(
        build123d.Box(36.0, 31.0, 10.0),
        build123d.Pos(0, 0, 11.0) * build123d.Box(36.0, 31.0, 2.0),
        extract_mechanical_lane(graph),
    )
    assert shell.is_valid and lid.is_valid
    assert len(shell.solids()) == 1
    assert len(lid.solids()) == 1
    assert shell.volume > 0 and lid.volume > 0
