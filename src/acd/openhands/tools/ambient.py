"""Detect whether an ambient conversation exposes the declared ACD tools.

``register_acd_tools()`` runs in the conversation that ``build_acd_conversation()``
constructs, but the ambient installed-plugin path can start a conversation that
only carries the generic SDK tools. A command that assumes its declared
``acd_*`` tools exist then silently degrades into ad-hoc shell work.

This module reads the tools a command declares, compares them against the tools
a conversation actually exposes, and reports the deterministic CLI path for every
missing tool. The report is an L3 observation: it never grants pass authority,
and an undiagnosable state is reported as ``unknown`` rather than as available.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from openhands.sdk.tool import list_registered_tools
from pydantic import ValidationError

from acd.openhands.tools.definitions import ACD_TOOL_DEFINITIONS, register_acd_tools
from acd.schema.tool_registration import AmbientToolAvailabilityReport, ToolFallback

ALLOWED_TOOLS_KEY: Final[str] = "allowed-tools"
_LIST_ITEM = re.compile(r"^\s+-\s*(\S+)\s*$")

# Deterministic CLI entry point that replaces each declared tool when the
# conversation does not expose it. A tool without a CLI equivalent must fail
# closed with an explicit reason instead of an approximate substitute.
TOOL_CLI_FALLBACKS: Final[dict[str, tuple[str, ...]]] = {
    "acd_aggregate_order_total": ("scripts/aggregate_order_total.py",),
    "acd_build_design_fixture": ("scripts/build_design_fixture.py",),
    "acd_check_order_readiness": ("scripts/pre_order_gate.py",),
    "acd_compile_requirement_change": ("scripts/compile_requirement_change.py",),
    "acd_explore_board_candidates": ("scripts/explore_board_candidates.py",),
    "acd_explore_enclosure_candidates": ("scripts/explore_enclosure_candidates.py",),
    "acd_probe_tools": ("scripts/probe_tools.py",),
    "acd_register_firmware_capability": ("scripts/register_firmware_capability.py",),
    "acd_register_functional_block": ("scripts/register_functional_block.py",),
    "acd_register_parts_catalog_entry": ("scripts/register_part_catalog_entry.py",),
    "acd_run_board_pipeline": ("scripts/run_gd1_pipeline.py",),
    "acd_run_design_loop": ("scripts/run_design_loop.py",),
    "acd_run_enclosure_pipeline": ("scripts/run_enclosure_pipeline.py",),
    "acd_validate_design_graph": ("scripts/validate_graph.py",),
}
NO_CLI_FALLBACK: Final[dict[str, str]] = {
    "acd_bootstrap_workspace": (
        "no CLI entry point exists; run the command inside a conversation built "
        "by acd.openhands.session.build_acd_conversation"
    ),
    "acd_diagnose_gate_failure": (
        "no CLI entry point exists; read the lane report under the run output "
        "directory and surface it with scripts/report_progress.py"
    ),
    "acd_run_firmware_pipeline": (
        "no CLI entry point exists; run the acd-firmware-esp32c3 Skill CLI via "
        "scripts/run_design_lanes.py"
    ),
}


class AmbientToolError(ValueError):
    """Raised when declared ACD tools are unavailable or undiagnosable."""


def declared_command_tools(command_path: Path) -> tuple[str, ...]:
    """Return the ``allowed-tools`` names declared by a command file."""
    try:
        text = command_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AmbientToolError(f"command file is unreadable: {command_path}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AmbientToolError(f"command front-matter is missing: {command_path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AmbientToolError(
            f"command front-matter is unterminated: {command_path}"
        ) from exc
    names: list[str] = []
    collecting = False
    for line in lines[1:end]:
        if line.startswith(f"{ALLOWED_TOOLS_KEY}:"):
            collecting = True
            continue
        if collecting:
            item = _LIST_ITEM.match(line)
            if item is None:
                collecting = False
                continue
            names.append(item.group(1))
    if not names:
        raise AmbientToolError(
            f"command declares no allowed tools: {command_path}"
        )
    unique = sorted(set(names))
    if len(unique) != len(names):
        raise AmbientToolError(
            f"command declares duplicate allowed tools: {command_path}"
        )
    return tuple(unique)


def _fallback(tool_name: str) -> ToolFallback:
    command = TOOL_CLI_FALLBACKS.get(tool_name)
    if command is not None:
        return ToolFallback(tool_name=tool_name, command=["uv", "run", "python", *command])
    reason = NO_CLI_FALLBACK.get(tool_name)
    if reason is not None:
        return ToolFallback(tool_name=tool_name, reason=reason)
    return ToolFallback(
        tool_name=tool_name,
        reason="tool is undeclared by the ACD registration contract",
    )


def check_ambient_tool_availability(
    command_path: Path, available_tools: Iterable[str]
) -> AmbientToolAvailabilityReport:
    """Compare the tools a command declares against those a conversation has."""
    declared = declared_command_tools(command_path)
    available = sorted({name for name in available_tools if name})
    missing = [name for name in declared if name not in set(available)]
    undeclared = [
        name for name in missing if name not in {item[0] for item in ACD_TOOL_DEFINITIONS}
    ]
    status = "pass" if not missing else ("unknown" if undeclared else "fail")
    reason: str | None = None
    if undeclared:
        reason = (
            "command declares tools outside the ACD registration contract: "
            + ", ".join(undeclared)
        )
    elif missing:
        reason = "conversation does not expose declared ACD tools: " + ", ".join(missing)
    try:
        return AmbientToolAvailabilityReport(
            status=status,
            command_path=str(command_path),
            declared_tools=list(declared),
            available_tools=available,
            missing_tools=missing,
            fallbacks=[_fallback(name) for name in missing],
            reason=reason,
        )
    except ValidationError as exc:
        raise AmbientToolError(f"tool availability report is invalid: {exc}") from exc


def registered_tool_names() -> tuple[str, ...]:
    """Return the registered tool names after ACD registration has run."""
    register_acd_tools()
    return tuple(sorted(list_registered_tools()))


def ensure_ambient_acd_tools(
    command_path: Path, available_tools: Sequence[str] | None = None
) -> AmbientToolAvailabilityReport:
    """Return the availability report or fail closed when tools are missing."""
    names = registered_tool_names() if available_tools is None else available_tools
    report = check_ambient_tool_availability(command_path, names)
    if report.status != "pass":
        raise AmbientToolError(report.reason or "declared ACD tools are unavailable")
    return report


def render_tool_availability(report: AmbientToolAvailabilityReport) -> str:
    """Render the report as conversation text with the deterministic next step."""
    lines = [
        "ACD tool availability (L3 observation, not pass evidence): "
        f"{report.status}",
        f"command: {report.command_path}",
    ]
    if report.reason is not None:
        lines.append(f"reason: {report.reason}")
    for fallback in report.fallbacks:
        if fallback.command:
            lines.append(f"- {fallback.tool_name}: run `{' '.join(fallback.command)}`")
        else:
            lines.append(f"- {fallback.tool_name}: {fallback.reason}")
    return "\n".join(lines)


__all__ = [
    "NO_CLI_FALLBACK",
    "TOOL_CLI_FALLBACKS",
    "AmbientToolError",
    "check_ambient_tool_availability",
    "declared_command_tools",
    "ensure_ambient_acd_tools",
    "registered_tool_names",
    "render_tool_availability",
]
