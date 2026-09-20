"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.placement_constraints``.
"""

from acd.core.electrical.placement_constraints import (
    PlacementConstraintError,
    PlacementCouplingConstraint,
    load_placement_coupling_constraints,
)

__all__ = [
    "PlacementConstraintError",
    "PlacementCouplingConstraint",
    "load_placement_coupling_constraints",
]
