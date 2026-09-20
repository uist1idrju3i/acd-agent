"""Deterministic build123d primitives for opt-in enclosure mechanisms."""

from __future__ import annotations

import importlib
from typing import Any

from acd.core.mechanical.mechanical import MechanicalLane, MechanismFeatureView


def _bd() -> Any:
    return importlib.import_module("build123d")


def _place(shape: Any, view: MechanismFeatureView) -> Any:
    bd = _bd()
    shape = bd.Rot(0, 0, view.rotation_deg) * shape
    if view.face in {"top", "lid"}:
        transform = bd.Pos(view.x_mm, view.y_mm, 0)
    elif view.face == "bottom":
        transform = bd.Pos(view.x_mm, view.y_mm, 0) * bd.Rot(180, 0, 0)
    elif view.face == "front":
        transform = bd.Pos(view.x_mm, view.y_mm, 0) * bd.Rot(90, 0, 0)
    elif view.face == "back":
        transform = bd.Pos(view.x_mm, view.y_mm, 0) * bd.Rot(-90, 0, 0)
    elif view.face == "left":
        transform = bd.Pos(view.x_mm, view.y_mm, 0) * bd.Rot(0, 90, 0)
    elif view.face == "right":
        transform = bd.Pos(view.x_mm, view.y_mm, 0) * bd.Rot(0, -90, 0)
    else:
        raise ValueError(f"unsupported mechanism face: {view.face}")
    return transform * shape


def build_snap_fit(view: MechanismFeatureView) -> Any:
    """Build a cantilever hook with a rectangular root and undercut tip."""
    bd = _bd()
    d = view.dimensions
    root = bd.Pos(d["hook_length_mm"] / 2, 0, d["hook_thickness_mm"] / 2) * bd.Box(
        d["hook_length_mm"], d["hook_thickness_mm"], d["hook_thickness_mm"]
    )
    tip = bd.Pos(
        d["hook_length_mm"] - d["undercut_mm"] / 2,
        0,
        d["hook_thickness_mm"] + d["undercut_mm"] / 2,
    ) * bd.Box(d["undercut_mm"], d["hook_thickness_mm"], d["undercut_mm"])
    return _place(root + tip, view)


def build_hinge(view: MechanismFeatureView) -> Any:
    """Build a coaxial pin and deterministic knuckle barrel."""
    bd = _bd()
    d = view.dimensions
    width = d["knuckle_width_mm"] * d["knuckle_count"]
    barrel_radius = d["pin_diameter_mm"] / 2 + d["clearance_mm"]
    barrel = bd.Pos(width / 2, 0, barrel_radius) * bd.Cylinder(
        barrel_radius,
        width,
        rotation=bd.Rot(0, 90, 0),
    )
    pin_cut = bd.Pos(width / 2, 0, barrel_radius) * bd.Cylinder(
        d["pin_diameter_mm"] / 2,
        width + 0.2,
        rotation=bd.Rot(0, 90, 0),
    )
    return _place(barrel - pin_cut, view)


def build_button(view: MechanismFeatureView) -> Any:
    """Build a round cap and its declared web."""
    bd = _bd()
    d = view.dimensions
    web_length = d["web_thickness_mm"] + d["stroke_mm"]
    cap = bd.Pos(0, 0, web_length + d["web_thickness_mm"] / 2) * bd.Cylinder(
        d["cap_diameter_mm"] / 2,
        d["web_thickness_mm"],
    )
    web = bd.Pos(0, 0, web_length / 2) * bd.Cylinder(
        d["cap_diameter_mm"] / 2,
        web_length,
    )
    return _place(cap + web, view)


def _button_opening(view: MechanismFeatureView) -> Any:
    bd = _bd()
    d = view.dimensions
    opening = bd.Pos(
        0,
        0,
        d["web_thickness_mm"] / 2,
    ) * bd.Cylinder(
        max(d["cap_diameter_mm"] / 2 - 0.05, 0.01),
        d["web_thickness_mm"] + 2.0,
    )
    return _place(opening, view)


def build_light_pipe(view: MechanismFeatureView) -> Any:
    """Build a cylindrical light pipe with the declared optical length."""
    bd = _bd()
    d = view.dimensions
    return _place(
        bd.Pos(0, 0, d["length_mm"] / 2)
        * bd.Cylinder(d["diameter_mm"] / 2, d["length_mm"]),
        view,
    )


def build_boss(view: MechanismFeatureView) -> Any:
    """Build an annular mounting boss."""
    bd = _bd()
    d = view.dimensions
    outer = bd.Pos(0, 0, d["height_mm"] / 2) * bd.Cylinder(
        d["outer_diameter_mm"] / 2, d["height_mm"]
    )
    hole = bd.Pos(0, 0, d["height_mm"] / 2) * bd.Cylinder(
        d["hole_diameter_mm"] / 2, d["height_mm"] + 0.2
    )
    return _place(outer - hole, view)


def build_rib(view: MechanismFeatureView) -> Any:
    """Build a tapered rectangular reinforcing rib."""
    bd = _bd()
    d = view.dimensions
    draft = max(0.5, min(89.0, d["draft_deg"]))
    profile = bd.Trapezoid(
        d["length_mm"],
        d["thickness_mm"],
        left_side_angle=90.0 - draft,
    )
    return _place(
        bd.Pos(d["length_mm"] / 2, 0, 0)
        * bd.extrude(profile, amount=d["height_mm"]),
        view,
    )


_BUILDERS = {
    "snap_fit": build_snap_fit,
    "hinge": build_hinge,
    "button": build_button,
    "light_pipe": build_light_pipe,
    "boss": build_boss,
    "rib": build_rib,
}


def build_mechanism_feature(view: MechanismFeatureView) -> Any:
    """Build the deterministic primitive for a declared mechanism feature."""
    return _BUILDERS[view.feature_type](view)


def apply_mechanism_features(shell: Any, lid: Any, lane: MechanicalLane) -> tuple[Any, Any]:
    """Apply mechanism solids to the declared enclosure target."""
    for feature in lane.mechanism_features:
        builder = _BUILDERS[feature.feature_type]
        solid = builder(feature)
        if feature.face == "lid":
            if feature.feature_type == "button":
                lid = lid - _button_opening(feature)
            lid = lid + solid
        else:
            if feature.feature_type == "button":
                shell = shell - _button_opening(feature)
            shell = shell + solid
    return shell, lid
