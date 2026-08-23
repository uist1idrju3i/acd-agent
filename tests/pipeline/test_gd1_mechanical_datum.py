"""Mechanical datum derivation tests."""

from __future__ import annotations

import pytest

from acd.pipeline.gd1_fixture.mechanical import (
    MECHANICAL_OUTLINE_ATTRS,
    mechanical_nodes,
    mounting_hole_body_positions,
)


def test_mounting_hole_body_positions_derive_from_outline() -> None:
    positions = mounting_hole_body_positions()
    assert positions == ((1.5, 1.5), (28.5, 1.5), (1.5, 23.5), (28.5, 23.5))
    bodies = [
        node
        for node in mechanical_nodes()
        if node.kind == "mechanical.component_body"
        and "comp.h" in node.depends_on[0]
    ]
    assert [(node.attrs["x_mm"], node.attrs["y_mm"]) for node in bodies] == list(positions)


def test_malformed_outline_datum_fails_closed() -> None:
    attrs = dict(MECHANICAL_OUTLINE_ATTRS)
    attrs["mount_hole_2_x_mm"] = "28.5"
    with pytest.raises(ValueError, match="mount_hole_2 outline datum"):
        mounting_hole_body_positions(attrs)
