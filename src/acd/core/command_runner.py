"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.command_runner``.
"""

from acd.core.runtime.command_runner import (
    Command,
    CommandResult,
    CommandSpec,
    run_stage,
)

__all__ = [
    "Command",
    "CommandResult",
    "CommandSpec",
    "run_stage",
]
