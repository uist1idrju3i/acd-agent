"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.exploration``.
"""

from acd.core.knowledge.exploration import (
    EXPLORATION_ARTIFACT_KIND,
    FIRMWARE_EXPLORATION_ARTIFACT_KIND,
    ExplorationCandidate,
    ExplorationError,
    ExplorationResult,
    RemediationRequest,
    enumerate_gpio_assignment_candidates,
    explore_board_candidates,
    load_exploration_graph,
    load_exploration_rationale,
    load_remediation_requests,
    run_candidate_search,
    validate_candidate_dimensions,
)

__all__ = [
    "EXPLORATION_ARTIFACT_KIND",
    "FIRMWARE_EXPLORATION_ARTIFACT_KIND",
    "ExplorationCandidate",
    "ExplorationError",
    "ExplorationResult",
    "RemediationRequest",
    "enumerate_gpio_assignment_candidates",
    "explore_board_candidates",
    "load_exploration_graph",
    "load_exploration_rationale",
    "load_remediation_requests",
    "run_candidate_search",
    "validate_candidate_dimensions",
]
