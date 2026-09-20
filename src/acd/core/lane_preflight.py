"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.lane_preflight``.
"""

from acd.core.runtime.lane_preflight import (
    LANE_IDS,
    LANE_NODE_EXACT_COUNTS,
    LANE_REQUIREMENTS,
    LANE_VALUE_RULES,
    PREFLIGHT_CHECKED_PREDICATES,
    PREFLIGHT_UNCHECKED_PREDICATES,
    SPEC_DECLARATION_PATHS,
    UNDECLARABLE_SPEC_PATH,
    LaneAttrValueRule,
    LaneNodeRequirement,
    missing_declaration_action,
    missing_declarations,
    run_lane_preflight,
)

__all__ = [
    "LANE_IDS",
    "LANE_NODE_EXACT_COUNTS",
    "LANE_REQUIREMENTS",
    "LANE_VALUE_RULES",
    "PREFLIGHT_CHECKED_PREDICATES",
    "PREFLIGHT_UNCHECKED_PREDICATES",
    "SPEC_DECLARATION_PATHS",
    "UNDECLARABLE_SPEC_PATH",
    "LaneAttrValueRule",
    "LaneNodeRequirement",
    "missing_declaration_action",
    "missing_declarations",
    "run_lane_preflight",
]
