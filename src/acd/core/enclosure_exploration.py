"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.enclosure_exploration``.
"""

from acd.core.mechanical.enclosure_exploration import (
    DEFAULT_JOBS,
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_SAMPLING_POINTS,
    ENCLOSURE_EXPLORATION_ARTIFACT_KIND,
    EnclosureExplorationCandidate,
    EnclosureExplorationError,
    EnclosureExplorationResult,
    enumerate_enclosure_candidates,
    explore_enclosure_candidates,
    validate_enclosure_dimensions,
)

__all__ = [
    "DEFAULT_JOBS",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_SAMPLING_POINTS",
    "ENCLOSURE_EXPLORATION_ARTIFACT_KIND",
    "EnclosureExplorationCandidate",
    "EnclosureExplorationError",
    "EnclosureExplorationResult",
    "enumerate_enclosure_candidates",
    "explore_enclosure_candidates",
    "validate_enclosure_dimensions",
]
