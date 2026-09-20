"""Compatibility re-export.

The implementation lives in ``acd.core.mechanical.cad_normalize``.
"""

from acd.core.mechanical.cad_normalize import (
    CadNormalizationError,
    normalize_3mf,
    normalize_step,
    normalize_stl,
    parse_stl,
)

__all__ = [
    "CadNormalizationError",
    "normalize_3mf",
    "normalize_step",
    "normalize_stl",
    "parse_stl",
]
