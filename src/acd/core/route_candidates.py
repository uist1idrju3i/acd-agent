"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.route_candidates``.
"""

from acd.core.electrical.route_candidates import (
    CANDIDATE_ARTIFACT_KIND,
    COPPER_LAYERS,
    REQUIRED_OBSERVATION_KEYS,
    REQUIRED_PROVENANCE_KEYS,
    RouteCandidateError,
    RouteCandidateProvenance,
    load_route_candidates,
    parse_provenance,
    parse_route_candidates,
)

__all__ = [
    "CANDIDATE_ARTIFACT_KIND",
    "COPPER_LAYERS",
    "REQUIRED_OBSERVATION_KEYS",
    "REQUIRED_PROVENANCE_KEYS",
    "RouteCandidateError",
    "RouteCandidateProvenance",
    "load_route_candidates",
    "parse_provenance",
    "parse_route_candidates",
]
