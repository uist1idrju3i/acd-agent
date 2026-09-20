"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.router_diagnostics``.
"""

from acd.core.electrical.router_diagnostics import (
    OPEN_NET_LIMIT,
    RouterDiagnostics,
    read_router_diagnostics,
    router_diagnostics_hint,
)

__all__ = [
    "OPEN_NET_LIMIT",
    "RouterDiagnostics",
    "read_router_diagnostics",
    "router_diagnostics_hint",
]
