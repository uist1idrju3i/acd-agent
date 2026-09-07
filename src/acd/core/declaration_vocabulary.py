"""Allowed-value vocabularies for free-form design-declaration attributes.

``DesignFixtureSpec`` attrs are free-form dicts, so the schema cannot constrain
the values the SB2 safety predicates and downstream gates accept. These tuples
are the single enumeration of those allowed values; ``design_predicates``
evaluates against them and the lane preflight lists them in its findings, so
both surfaces name exactly one vocabulary. Adding a value here is a contract
change and must be justified in the same change; nothing here widens a gate by
accident.
"""

from __future__ import annotations

from typing import Final

# safety.boundary.attrs values
SAFETY_BOUNDARY_INTENDED_USE: Final[tuple[str, ...]] = ("author_prototype",)
SAFETY_BOUNDARY_MODULE_CERTIFIED: Final[tuple[str, ...]] = ("certified",)
# Each hazard key must be declared as a bool on the safety.boundary node.
SAFETY_BOUNDARY_HAZARD_KEYS: Final[tuple[str, ...]] = (
    "battery",
    "charger",
    "motor_actuator_laser",
)

# electrical.net.attrs["width_basis"] values
NET_WIDTH_BASIS: Final[tuple[str, ...]] = (
    "current_ipc2221",
    "manufacturing_minimum",
)

__all__ = [
    "NET_WIDTH_BASIS",
    "SAFETY_BOUNDARY_HAZARD_KEYS",
    "SAFETY_BOUNDARY_INTENDED_USE",
    "SAFETY_BOUNDARY_MODULE_CERTIFIED",
]
