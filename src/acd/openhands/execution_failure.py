"""Classify command failures so environment faults are not read as design faults.

A permission or environment fault means the deterministic gate never produced a
verdict: it stays fail-closed, but it is reported as ``environment`` rather than
``design`` so that a writable-path problem is not recorded as a design rejection.
"""

from __future__ import annotations

import re
from typing import Final, Literal

ExecutionFailureKind = Literal["none", "permission", "environment", "design", "unknown"]

_PERMISSION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"\[Errno 13\]"),
    re.compile(r"\bEACCES\b"),
    re.compile(r"read-only file system", re.IGNORECASE),
    re.compile(r"operation not permitted", re.IGNORECASE),
)
_ENVIRONMENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"no space left on device", re.IGNORECASE),
    re.compile(r"failed to create (?:cache|home) directory", re.IGNORECASE),
    re.compile(r"could not create .*(?:cache|home)", re.IGNORECASE),
    re.compile(r"\$HOME is not set", re.IGNORECASE),
    re.compile(r"uv_cache_dir", re.IGNORECASE),
)


def classify_execution_failure(exit_code: int, output: str) -> ExecutionFailureKind:
    """Classify a finished command by exit code and captured output."""
    if exit_code == 0:
        return "none"
    if any(pattern.search(output) for pattern in _PERMISSION_PATTERNS):
        return "permission"
    if any(pattern.search(output) for pattern in _ENVIRONMENT_PATTERNS):
        return "environment"
    if not output.strip():
        return "unknown"
    return "design"


__all__ = ["ExecutionFailureKind", "classify_execution_failure"]
