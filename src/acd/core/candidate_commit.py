"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.candidate_commit``.
"""

from acd.core.knowledge.candidate_commit import (
    CandidateCommitError,
    commit_candidate_graph,
)

__all__ = [
    "CandidateCommitError",
    "commit_candidate_graph",
]
