from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.design_graph import GraphNode
from acd.schema.node_attrs import (
    KIND_ATTRS_MODELS,
    FunctionalBlockAttrs,
    NetAttrs,
    PlacementGroupAttrs,
    RedundantGroupAttrs,
)


def test_typed_attrs_returns_kind_specific_view() -> None:
    node = GraphNode(
        id="pg1",
        kind="electrical.placement_group",
        attrs={
            "primary_refdes": "U1",
            "coupled_refdes": ["C1", "C2"],
            "max_distance_mm": 3,
        },
    )
    view = node.typed_attrs(PlacementGroupAttrs)
    assert view.primary_refdes == "U1"
    assert view.coupled_refdes == ["C1", "C2"]
    assert view.max_distance_mm == 3
    assert view.move_together is None


def test_open_attrs_keep_lane_local_keys() -> None:
    node = GraphNode(
        id="n1",
        kind="electrical.net",
        attrs={"signal_class": "power", "power_rail": True, "net_name": "+5V"},
    )
    view = node.typed_attrs(NetAttrs)
    assert view.signal_class == "power"
    assert view.model_extra == {"power_rail": True, "net_name": "+5V"}


@pytest.mark.parametrize(
    ("kind", "attrs", "message"),
    [
        (
            "electrical.placement_group",
            {"primary_refdes": "U1", "coupled_refdes": ["C1"]},
            "explicit max_distance_mm",
        ),
        (
            "electrical.placement_group",
            {"primary_refdes": "U1", "coupled_refdes": ["C1"], "max_distance_mm": 0},
            "max_distance_mm must be positive",
        ),
        (
            "electrical.placement_group",
            {"primary_refdes": "U1", "coupled_refdes": ["C1"], "max_distance_mm": True},
            "max_distance_mm",
        ),
        (
            "electrical.placement_group",
            {"primary_refdes": "U1", "coupled_refdes": [], "max_distance_mm": 1},
            "coupled_refdes",
        ),
        (
            "electrical.placement_group",
            {
                "primary_refdes": "U1",
                "coupled_refdes": ["C1"],
                "max_distance_mm": 1,
                "extra": 1,
            },
            "extra",
        ),
        ("design.functional_block", {"block_id": ""}, "block_id"),
        ("design.functional_block", {"other": "x"}, "other"),
        ("electrical.net", {"signal_class": "rf"}, "signal_class"),
        ("electrical.net", {"critical": "yes"}, "critical"),
        ("electrical.net", {"intended_coupling": ["", "a"]}, "intended_coupling"),
        ("electrical.component", {"protection_role": "breaker"}, "protection_role"),
        ("safety.redundant_group", {"members": ["a"]}, "resources_shared_forbidden"),
        (
            "safety.redundant_group",
            {"members": ["a"], "resources_shared_forbidden": ["cable"]},
            "resources_shared_forbidden",
        ),
    ],
)
def test_malformed_kind_attrs_fail_closed(
    kind: str, attrs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        GraphNode.model_validate({"id": "n1", "kind": kind, "attrs": attrs})


def test_kinds_without_a_model_accept_free_form_attrs() -> None:
    assert "requirement" not in KIND_ATTRS_MODELS
    node = GraphNode(id="r1", kind="requirement", attrs={"anything": [1, {"a": None}]})
    assert node.attrs["anything"] == [1, {"a": None}]


def test_typed_attrs_revalidates_unvalidated_nodes() -> None:
    node = GraphNode.model_construct(
        id="rg1",
        kind="safety.redundant_group",
        attrs={"members": ["a"], "resources_shared_forbidden": ["cable"]},
        depends_on=[],
    )
    with pytest.raises(ValidationError):
        node.typed_attrs(RedundantGroupAttrs)


def test_functional_block_attrs_allow_root_blocks() -> None:
    node = GraphNode(id="fb1", kind="design.functional_block", attrs={"block_id": "b"})
    view = node.typed_attrs(FunctionalBlockAttrs)
    assert view.block_id == "b"
    assert view.parent_block_id is None
