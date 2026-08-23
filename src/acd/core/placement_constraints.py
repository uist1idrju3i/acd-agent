"""Validation and typed access for graph placement-coupling declarations."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from acd.schema.design_graph import DesignGraph


class PlacementConstraintError(ValueError):
    """Raised when placement-coupling input is malformed or unresolved."""


@dataclass(frozen=True)
class PlacementCouplingConstraint:
    group_id: str
    primary_refdes: str
    coupled_refdes: tuple[str, ...]
    max_distance_mm: float | None
    move_together: bool


def load_placement_coupling_constraints(
    graph: DesignGraph,
) -> tuple[PlacementCouplingConstraint, ...]:
    """Return deterministic, fail-closed placement groups from a graph."""
    components: dict[str, str] = {}
    for node in graph.nodes:
        if node.kind != "electrical.component":
            continue
        refdes = node.attrs.get("refdes")
        if not isinstance(refdes, str) or not refdes:
            raise PlacementConstraintError(
                f"component {node.id!r} has malformed refdes"
            )
        if refdes in components:
            raise PlacementConstraintError(f"duplicate component refdes {refdes!r}")
        components[refdes] = node.id

    groups: list[PlacementCouplingConstraint] = []
    claimed: set[str] = set()
    for node in sorted(
        (item for item in graph.nodes if item.kind == "electrical.placement_group"),
        key=lambda item: item.id,
    ):
        primary = node.attrs["primary_refdes"]
        coupled_value = node.attrs["coupled_refdes"]
        if not isinstance(primary, str) or not primary or not isinstance(
            coupled_value, list
        ):
            raise PlacementConstraintError(f"group {node.id!r} has malformed members")
        coupled = tuple(coupled_value)
        members = (primary, *coupled)
        if len(set(members)) != len(members):
            raise PlacementConstraintError(f"group {node.id!r} has duplicate members")
        unknown = sorted(set(members) - set(components))
        if unknown:
            raise PlacementConstraintError(
                f"group {node.id!r} references unknown components: {unknown}"
            )
        dependency_ids = {
            dependency
            for dependency in node.depends_on
            if dependency in set(components.values())
        }
        expected_ids = {components[refdes] for refdes in members}
        if dependency_ids != expected_ids:
            raise PlacementConstraintError(
                f"group {node.id!r} dependencies do not match declared members"
            )
        overlap = claimed & set(members)
        if overlap:
            raise PlacementConstraintError(
                f"placement groups overlap in components: {sorted(overlap)}"
            )
        claimed.update(members)
        distance_value = node.attrs.get("max_distance_mm")
        if distance_value is None:
            max_distance = None
        else:
            if isinstance(distance_value, bool) or not isinstance(
                distance_value, (int, float)
            ):
                raise PlacementConstraintError(
                    f"group {node.id!r} max_distance_mm is malformed"
                )
            max_distance = float(distance_value)
        if max_distance is not None and not isfinite(max_distance):
            raise PlacementConstraintError(
                f"group {node.id!r} max_distance_mm must be finite"
            )
        move_together = node.attrs.get("move_together", False)
        if not isinstance(move_together, bool):
            raise PlacementConstraintError(
                f"group {node.id!r} move_together is malformed"
            )
        groups.append(
            PlacementCouplingConstraint(
                group_id=node.id,
                primary_refdes=primary,
                coupled_refdes=tuple(sorted(coupled)),
                max_distance_mm=max_distance,
                move_together=move_together,
            )
        )
    return tuple(groups)


__all__ = [
    "PlacementConstraintError",
    "PlacementCouplingConstraint",
    "load_placement_coupling_constraints",
]
