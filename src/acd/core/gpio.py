"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.gpio``.
"""

from acd.core.electrical.gpio import (
    GpioAssignmentError,
    apply_gpio_assignment,
    gpio_pad_map,
)

__all__ = [
    "GpioAssignmentError",
    "apply_gpio_assignment",
    "gpio_pad_map",
]
