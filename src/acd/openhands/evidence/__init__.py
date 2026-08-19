"""Evidence validation, git freshness checks, and revision resolution."""

from acd.openhands.evidence.check import check
from acd.openhands.evidence.git import check_evidence_with_git, design_input_changes
from acd.openhands.evidence.revision import resolve

__all__ = ["check", "check_evidence_with_git", "design_input_changes", "resolve"]
