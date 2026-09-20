"""Firmware lane: declarations, capabilities, coverage, security gates."""

from acd.core.firmware.firmware import (
    FunctionalRunError,
    evaluate_functional_run,
    load_and_evaluate_functional_run,
)

__all__ = [
    "FunctionalRunError",
    "evaluate_functional_run",
    "load_and_evaluate_functional_run",
]
