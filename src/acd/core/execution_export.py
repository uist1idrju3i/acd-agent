"""Collect a publishable minimum set from execution records.

Execution records are written on the machine that ran the hardware or container
work, so they carry host paths, endpoints, and account names that must not leave
the machine. The export keeps an explicit allowlist of publishable fields,
redacts the remaining text by default, and fails closed when a leak pattern
survives redaction: an unverifiable export is not published.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final, cast

PUBLIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "acquired_at",
        "app_flash_offset",
        "artifact_type",
        "attempts",
        "build_artifacts",
        "build_at",
        "content_hash",
        "digest",
        "duration_s",
        "duty_max",
        "duty_min",
        "esp_idf_version",
        "exit_code",
        "expectations",
        "fail_closed",
        "failed_stage",
        "failures",
        "finished_at",
        "flash_at",
        "frequency_hz",
        "graph_id",
        "humidity_max_rh",
        "humidity_min_rh",
        "image_digest",
        "led",
        "log_type",
        "logs",
        "measurement_class",
        "minimum_cycles",
        "minimum_samples",
        "ok",
        "period_s",
        "period_tolerance_s",
        "project_git_commit",
        "recorded_at",
        "returncode",
        "run_id",
        "schema_version",
        "serial",
        "stage",
        "stage_id",
        "stages",
        "started_at",
        "status",
        "target_revision",
        "temperature_max_deg_c",
        "temperature_min_deg_c",
        "timeout_s",
        "tolerance_hz",
        "tool_name",
        "tool_version",
        "toolchain_version",
    }
)

REDACTED: Final = "[redacted]"

# Host-looking tokens are only redacted when they end in a network suffix, so
# tool and toolchain versions such as "5.2.1" stay publishable.
_HOSTNAME_SOURCE: Final = (
    r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*"
    r"\.(?:com|net|org|io|dev|ai|jp|local|internal|lan|localdomain)\b(?::\d+)?"
)

_REDACTIONS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"']+"), REDACTED),
    (re.compile(r"/(?:home|Users)/[^/\s\"']+"), f"/{REDACTED}"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), REDACTED),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\b"), REDACTED),
    (re.compile(_HOSTNAME_SOURCE), REDACTED),
    (re.compile(r"\b[a-zA-Z][a-zA-Z0-9-]*:\d{2,5}\b"), REDACTED),
)

_LEAK_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("endpoint", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")),
    ("ip_address", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("home_path", re.compile(r"/(?:home|Users)/[^/\s\"']+")),
    ("account", re.compile(r"\b[\w.+-]+@[\w.-]+\b")),
    ("hostname", re.compile(_HOSTNAME_SOURCE)),
)


def redact_text(value: str) -> str:
    """Redact endpoints, hostnames, addresses, and account names."""
    redacted = value
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _sanitize(item)
            for key, item in mapping.items()
            if str(key) in PUBLIC_FIELDS
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        items = cast(Sequence[object], value)
        return [_sanitize(item) for item in items]
    return value


def find_leaks(value: object, *, path: str = "") -> tuple[str, ...]:
    """Report every remaining leak pattern with its location."""
    findings: list[str] = []
    if isinstance(value, str):
        for name, pattern in _LEAK_PATTERNS:
            if pattern.search(value):
                findings.append(f"{path or '<root>'}: {name}")
    elif isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for key, item in mapping.items():
            findings.extend(find_leaks(item, path=f"{path}.{key}" if path else str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        items = cast(Sequence[object], value)
        for index, item in enumerate(items):
            findings.extend(find_leaks(item, path=f"{path}[{index}]"))
    return tuple(findings)


class ExecutionExportError(RuntimeError):
    """Raised when an execution record cannot be exported safely."""


def export_execution_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return the publishable minimum set of one execution record."""
    sanitized = _sanitize(record)
    if not isinstance(sanitized, dict):
        raise ExecutionExportError("execution record must be an object")
    exported = cast(dict[str, object], sanitized)
    leaks = find_leaks(exported)
    if leaks:
        raise ExecutionExportError(
            "export refused because redaction is incomplete: " + ", ".join(leaks)
        )
    return exported


__all__ = [
    "PUBLIC_FIELDS",
    "REDACTED",
    "ExecutionExportError",
    "export_execution_record",
    "find_leaks",
    "redact_text",
]
