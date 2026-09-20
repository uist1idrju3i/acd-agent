"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.bom_compliance``.
"""

from acd.core.manufacturing.bom_compliance import (
    compliance_summary_markdown,
    summarize_bom_compliance,
)

__all__ = [
    "compliance_summary_markdown",
    "summarize_bom_compliance",
]
