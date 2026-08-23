"""Placement-coupling graph contract tests."""

from __future__ import annotations

import pytest

from acd.core.placement_constraints import (
    PlacementConstraintError,
    load_placement_coupling_constraints,
)
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode


def _graph(
    group_attrs: dict[str, AttrValue], depends_on: list[str] | None = None
) -> DesignGraph:
    return DesignGraph(
        graph_id="g",
        revision="r1",
        nodes=[
            GraphNode(id="comp.u3", kind="electrical.component", attrs={"refdes": "U3"}),
            GraphNode(id="comp.c5", kind="electrical.component", attrs={"refdes": "C5"}),
            GraphNode(id="comp.r4", kind="electrical.component", attrs={"refdes": "R4"}),
            GraphNode(
                id="group",
                kind="electrical.placement_group",
                attrs=group_attrs,
                depends_on=depends_on or ["comp.u3", "comp.c5", "comp.r4"],
            ),
        ],
    )


def test_group_resolves_deterministically() -> None:
    group = load_placement_coupling_constraints(
        _graph(
            {
                "primary_refdes": "U3",
                "coupled_refdes": ["C5", "R4"],
                "max_distance_mm": 3.0,
                "move_together": True,
            }
        )
    )[0]
    assert group.primary_refdes == "U3"
    assert group.coupled_refdes == ("C5", "R4")
    assert group.max_distance_mm == 3.0


def test_unknown_group_member_fails_closed() -> None:
    with pytest.raises(PlacementConstraintError, match="unknown components"):
        load_placement_coupling_constraints(
            _graph(
                {
                    "primary_refdes": "U3",
                    "coupled_refdes": ["C5", "UNKNOWN"],
                    "max_distance_mm": 3.0,
                }
            )
        )


def test_malformed_distance_fails_closed_at_schema_boundary() -> None:
    with pytest.raises(ValueError, match="max_distance_mm"):
        _graph(
            {
                "primary_refdes": "U3",
                "coupled_refdes": ["C5"],
                "max_distance_mm": 0,
            }
        )


def test_group_dependency_mismatch_fails_closed() -> None:
    with pytest.raises(PlacementConstraintError, match="dependencies"):
        load_placement_coupling_constraints(
            _graph(
                {
                    "primary_refdes": "U3",
                    "coupled_refdes": ["C5", "R4"],
                    "move_together": True,
                },
                depends_on=["comp.u3", "comp.c5"],
            )
        )
