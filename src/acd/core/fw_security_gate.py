"""Compatibility re-export.

The implementation lives in ``acd.core.firmware.fw_security_gate``.
"""

from acd.core.firmware.fw_security_gate import (
    check_build_config_consistency,
    validate_security_gate_result,
)

__all__ = [
    "check_build_config_consistency",
    "validate_security_gate_result",
]
