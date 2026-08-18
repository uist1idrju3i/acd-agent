"""SDK tool definitions and external capability probes."""

from acd.openhands.tools.definitions import (
    AcdObservation,
    register_acd_tools,
)
from acd.openhands.tools.probe import (
    PROBES,
    ProbeReport,
    ToolProbeResult,
    probe_all,
    probe_cad_kernel,
    probe_executable,
    probe_freerouting,
    probe_kicad_cli,
)

__all__ = [
    "PROBES",
    "AcdObservation",
    "ProbeReport",
    "ToolProbeResult",
    "probe_all",
    "probe_cad_kernel",
    "probe_executable",
    "probe_freerouting",
    "probe_kicad_cli",
    "register_acd_tools",
]
