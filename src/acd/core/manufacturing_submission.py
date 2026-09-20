"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.manufacturing_submission``.
"""

from acd.core.manufacturing.manufacturing_submission import (
    ManufacturingSubmissionError,
    evaluate_manufacturing_submission,
    manufacturing_submission_content_hash_payload,
)

__all__ = [
    "ManufacturingSubmissionError",
    "evaluate_manufacturing_submission",
    "manufacturing_submission_content_hash_payload",
]
