"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.evidence_declarations``.
"""

from acd.core.runtime.evidence_declarations import (
    EvidenceDeclarationCode,
    EvidenceDeclarationFinding,
    check_cpl_rotation_record,
    check_fab_profile_declaration,
    collect_evidence_declaration_findings,
    collect_producer_gaps,
    cpl_rotation_record_path,
)

__all__ = [
    "EvidenceDeclarationCode",
    "EvidenceDeclarationFinding",
    "check_cpl_rotation_record",
    "check_fab_profile_declaration",
    "collect_evidence_declaration_findings",
    "collect_producer_gaps",
    "cpl_rotation_record_path",
]
