"""Compatibility re-export.

The implementation lives in ``acd.core.knowledge.naming``.
"""

from acd.core.knowledge.naming import (
    artifact_prefix,
    evidence_id,
    firmware_project_name,
    output_prefix,
    required_evidence_ids,
    subject_node_id,
)

__all__ = [
    "artifact_prefix",
    "evidence_id",
    "firmware_project_name",
    "output_prefix",
    "required_evidence_ids",
    "subject_node_id",
]
