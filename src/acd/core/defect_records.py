"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.defect_records``.
"""

from acd.core.manufacturing.defect_records import (
    DefectCheckResult,
    DefectFinding,
    DefectRecordError,
    LoadedDefectDocument,
    check_defect_records,
    compute_horizontal_scope,
    load_defect_document,
)

__all__ = [
    "DefectCheckResult",
    "DefectFinding",
    "DefectRecordError",
    "LoadedDefectDocument",
    "check_defect_records",
    "compute_horizontal_scope",
    "load_defect_document",
]
