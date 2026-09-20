"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.fem``.
"""

from acd.core.mechanical.fem import (
    FemAnalysisError,
    FemRawResult,
    evaluate_fem,
    fem_markdown,
    generate_ccx_input,
    run_ccx,
)

__all__ = [
    "FemAnalysisError",
    "FemRawResult",
    "evaluate_fem",
    "fem_markdown",
    "generate_ccx_input",
    "run_ccx",
]
