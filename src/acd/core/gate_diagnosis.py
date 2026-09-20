"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.gate_diagnosis``.
"""

from acd.core.runtime.gate_diagnosis import (
    GateDiagnosisError,
    diagnose_gate_failure,
)

__all__ = [
    "GateDiagnosisError",
    "diagnose_gate_failure",
]
