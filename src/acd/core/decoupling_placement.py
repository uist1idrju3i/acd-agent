"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.decoupling_placement``.
"""

from acd.core.electrical.decoupling_placement import (
    COURTYARD_CLEARANCE_MM,
    PLACEMENT_SOURCE,
    DecouplingPlacement,
    DecouplingPlacementDeficiency,
    DecouplingPlacementError,
    DecouplingPlacementReport,
    apply_decoupling_placements,
    solve_decoupling_placements,
)

__all__ = [
    "COURTYARD_CLEARANCE_MM",
    "PLACEMENT_SOURCE",
    "DecouplingPlacement",
    "DecouplingPlacementDeficiency",
    "DecouplingPlacementError",
    "DecouplingPlacementReport",
    "apply_decoupling_placements",
    "solve_decoupling_placements",
]
