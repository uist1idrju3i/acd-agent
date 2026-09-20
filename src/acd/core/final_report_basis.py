"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.final_report_basis``.
"""

from acd.core.runtime.final_report_basis import (
    collect_design_values,
    collect_final_report_basis,
    collect_source_changes,
    render_final_report_basis,
)

__all__ = [
    "collect_design_values",
    "collect_final_report_basis",
    "collect_source_changes",
    "render_final_report_basis",
]
