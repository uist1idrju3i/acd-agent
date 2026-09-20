"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.qr_geometry``.
"""

from acd.core.electrical.qr_geometry import (
    QR_DATA_MODULES,
    QR_QUIET_ZONE_MODULES,
    qr_module_matrix_from_svg,
)

__all__ = [
    "QR_DATA_MODULES",
    "QR_QUIET_ZONE_MODULES",
    "qr_module_matrix_from_svg",
]
