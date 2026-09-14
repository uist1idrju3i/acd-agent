"""Plain-text lane log contract: structured header, output, footer.

A lane log is written by the runner around a single command execution. The
header records the declared inputs before the command runs; the footer records
the observed result afterwards. Parsing is fail-closed: an interrupted run
(without the ``=== result ===`` footer) or an unknown header version is not a
lane log. The record is an L3 observation with no pass authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.core.log_summary import DEFAULT_TAIL_LINES, summarize_log

LANE_LOG_VERSION = "acd-lane-log 0.1"
_HEADER = f"=== {LANE_LOG_VERSION} ==="
_OUTPUT_MARK = "=== output ==="
_RESULT_MARK = "=== result ==="
_HEADER_KEYS = ("image", "revision", "command", "started_at")
_RESULT_KEYS = (
    "exit_code",
    "image_digest",
    "execution_context",
    "failure_kind",
    "finished_at",
)


class LaneLogError(ValueError):
    """Raised when a lane log is missing, malformed, or interrupted."""


@dataclass(frozen=True)
class LaneLogRecord:
    """One parsed lane log with the tail of its command output."""

    image: str
    revision: str
    command: str
    started_at: str
    output_tail: tuple[str, ...]
    exit_code: int
    image_digest: str
    execution_context: str
    failure_kind: str
    finished_at: str

    def to_execution_record(self) -> dict[str, object]:
        """Return the exportable execution-record view of this lane log.

        The raw image reference is deliberately omitted: registry hostnames
        trip the export leak detector, so only the resolved digest is kept.
        """
        return {
            "schema_version": "0.1",
            "log_type": "lane_log",
            "exit_code": self.exit_code,
            "fail_closed": self.exit_code != 0,
            "image_digest": self.image_digest,
            "target_revision": self.revision,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "failure_kind": self.failure_kind,
            "logs": list(self.output_tail),
        }


def write_lane_log_header(
    path: Path,
    *,
    image: str,
    revision: str,
    command: str,
    started_at: str,
) -> None:
    """Create the lane log with its structured header (truncates existing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{_HEADER}\n"
        f"image: {image}\n"
        f"revision: {revision}\n"
        f"command: {command}\n"
        f"started_at: {started_at}\n"
        f"{_OUTPUT_MARK}\n",
        encoding="utf-8",
    )


def append_lane_log_footer(
    path: Path,
    *,
    exit_code: int,
    image_digest: str,
    execution_context: str,
    failure_kind: str,
    finished_at: str,
) -> None:
    """Append the structured result footer to an existing lane log."""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            f"{_RESULT_MARK}\n"
            f"exit_code: {exit_code}\n"
            f"image_digest: {image_digest}\n"
            f"execution_context: {execution_context}\n"
            f"failure_kind: {failure_kind}\n"
            f"finished_at: {finished_at}\n"
        )


def _parse_fields(lines: list[str], *, section: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise LaneLogError(f"lane log {section} line is not 'key: value': {line!r}")
        fields[key.strip()] = value.strip()
    return fields


def parse_lane_log(text: str) -> LaneLogRecord:
    """Parse one lane log; any deviation fails closed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _HEADER:
        raise LaneLogError("lane log header version is missing or unknown")
    try:
        output_index = lines.index(_OUTPUT_MARK)
    except ValueError as exc:
        raise LaneLogError("lane log is missing the output section marker") from exc
    try:
        result_index = lines.index(_RESULT_MARK, output_index + 1)
    except ValueError as exc:
        raise LaneLogError(
            "lane log is missing the result footer (interrupted run)"
        ) from exc
    header = _parse_fields(lines[1:output_index], section="header")
    missing = [key for key in _HEADER_KEYS if key not in header]
    if missing:
        raise LaneLogError(f"lane log header is missing keys: {', '.join(missing)}")
    footer = _parse_fields(lines[result_index + 1 :], section="footer")
    missing = [key for key in _RESULT_KEYS if key not in footer]
    if missing:
        raise LaneLogError(f"lane log footer is missing keys: {', '.join(missing)}")
    try:
        exit_code = int(footer["exit_code"])
    except ValueError as exc:
        raise LaneLogError("lane log exit_code is not an integer") from exc
    output_lines = lines[output_index + 1 : result_index]
    summary = summarize_log("\n".join(output_lines), tail_lines=DEFAULT_TAIL_LINES)
    return LaneLogRecord(
        image=header["image"],
        revision=header["revision"],
        command=header["command"],
        started_at=header["started_at"],
        output_tail=tuple(summary.text.splitlines()) if summary.text else (),
        exit_code=exit_code,
        image_digest=footer["image_digest"],
        execution_context=footer["execution_context"],
        failure_kind=footer["failure_kind"],
        finished_at=footer["finished_at"],
    )


__all__ = [
    "LANE_LOG_VERSION",
    "LaneLogError",
    "LaneLogRecord",
    "append_lane_log_footer",
    "parse_lane_log",
    "write_lane_log_header",
]
