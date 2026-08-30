"""Fail-closed host resource checks required before container startup."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from acd.schema.host_resources import (
    HostResourceCode,
    HostResourceFinding,
    HostResourceReport,
)

DEFAULT_FREEROUTING_MAX_HEAP: Final = "2g"
_MEMORY_VALUE = re.compile(r"^(?P<value>[1-9][0-9]*)(?P<unit>[bkmg])$")
_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB


@dataclass(frozen=True)
class ResourceRequirement:
    memory_limit_bytes: int
    jvm_max_heap_bytes: int
    host_memory_headroom_bytes: int = 512 * _MIB
    jvm_non_heap_reserve_bytes: int = 1024 * _MIB
    min_cpu_count: int = 2
    min_disk_free_bytes: int = 8 * _GIB


def parse_memory_bytes(value: str) -> int:
    """Parse a Docker/JVM memory value using binary units."""
    match = _MEMORY_VALUE.fullmatch(value.strip().lower())
    if match is None:
        raise ValueError("memory value must look like '2g', '512m', or '1024k'")
    multiplier = {
        "b": 1,
        "k": _KIB,
        "m": _MIB,
        "g": _GIB,
    }[match.group("unit")]
    return int(match.group("value")) * multiplier


def _mib(value: int | None) -> str:
    return "unknown" if value is None else f"{value / _MIB:.2f} MiB"


def _finding(code: str, detail: str) -> HostResourceFinding:
    return HostResourceFinding(code=cast(HostResourceCode, code), detail=detail)


def _read_meminfo(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return values
    for line in lines:
        name, separator, raw = line.partition(":")
        if not separator:
            continue
        fields = raw.strip().split()
        if len(fields) not in (1, 2) or not fields[0].isdigit():
            continue
        multiplier = _KIB if len(fields) == 2 and fields[1].lower() == "kb" else 1
        if len(fields) == 2 and fields[1].lower() != "kb":
            continue
        values[name] = int(fields[0]) * multiplier
    return values


def check_host_resources(
    requirement: ResourceRequirement,
    *,
    meminfo_path: Path = Path("/proc/meminfo"),
    disk_path: Path = Path("."),
    cpu_count: int | None = None,
    declared_jvm_max_heap: str = DEFAULT_FREEROUTING_MAX_HEAP,
) -> HostResourceReport:
    """Return all host resource findings without raising on probe failures."""
    meminfo = _read_meminfo(meminfo_path)
    mem_total = meminfo.get("MemTotal")
    mem_available = meminfo.get("MemAvailable")
    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")
    findings: list[HostResourceFinding] = []

    if mem_total is None or mem_available is None:
        findings.append(
            _finding(
                "host.memory.unknown",
                (
                    f"host memory could not be parsed; observed total={_mib(mem_total)}, "
                    f"available={_mib(mem_available)}; requested "
                    f"--memory-limit={_mib(requirement.memory_limit_bytes)}"
                ),
            )
        )
    else:
        usable_total = mem_total - requirement.host_memory_headroom_bytes
        if requirement.memory_limit_bytes > usable_total:
            findings.append(
                _finding(
                    "host.memory.total_insufficient",
                    (
                        f"MemTotal={_mib(mem_total)} minus headroom="
                        f"{_mib(requirement.host_memory_headroom_bytes)} leaves "
                        f"{_mib(usable_total)}; requested "
                        f"--memory-limit={_mib(requirement.memory_limit_bytes)} exceeds "
                        f"this limit, lower --memory-limit to at most "
                        f"{_mib(usable_total)}"
                    ),
                )
            )
        if requirement.memory_limit_bytes > mem_available:
            findings.append(
                _finding(
                    "host.memory.available_insufficient",
                    (
                        f"MemAvailable={_mib(mem_available)}; requested "
                        f"--memory-limit={_mib(requirement.memory_limit_bytes)} exceeds "
                        f"available memory, lower --memory-limit to at most "
                        f"{_mib(mem_available)}"
                    ),
                )
            )

    if swap_total is None or swap_free is None:
        findings.append(
            _finding(
                "host.swap.unknown",
                (
                    f"SwapTotal={_mib(swap_total)}, SwapFree={_mib(swap_free)} "
                    "could not be observed; swap is not added to the memory limit "
                    f"requirement of {_mib(requirement.memory_limit_bytes)}"
                ),
            )
        )

    observed_cpu = os.cpu_count() if cpu_count is None else cpu_count
    if observed_cpu is None:
        findings.append(
            _finding(
                "host.cpu.unknown",
                (
                    f"host CPU count is unknown; required at least "
                    f"{requirement.min_cpu_count} cores"
                ),
            )
        )
    elif observed_cpu < requirement.min_cpu_count:
        findings.append(
            _finding(
                "host.cpu.insufficient",
                (
                    f"observed CPU count={observed_cpu}; required at least "
                    f"{requirement.min_cpu_count} cores"
                ),
            )
        )

    disk_free: int | None
    try:
        disk_free = shutil.disk_usage(disk_path).free
    except OSError:
        disk_free = None
    if disk_free is None:
        findings.append(
            _finding(
                "host.disk.unknown",
                (
                    f"free disk space at {disk_path} is unknown; required at least "
                    f"{_mib(requirement.min_disk_free_bytes)}"
                ),
            )
        )
    elif disk_free < requirement.min_disk_free_bytes:
        findings.append(
            _finding(
                "host.disk.insufficient",
                (
                    f"observed free disk={_mib(disk_free)}; required at least "
                    f"{_mib(requirement.min_disk_free_bytes)}"
                ),
            )
        )

    if (
        requirement.jvm_max_heap_bytes + requirement.jvm_non_heap_reserve_bytes
        > requirement.memory_limit_bytes
    ):
        findings.append(
            _finding(
                "runtime.jvm_heap.exceeds_container_limit",
                (
                    f"declared JVM max heap={_mib(requirement.jvm_max_heap_bytes)} "
                    f"plus non-heap reserve={_mib(requirement.jvm_non_heap_reserve_bytes)} "
                    f"exceeds container --memory-limit="
                    f"{_mib(requirement.memory_limit_bytes)}; lower "
                    f"--jvm-max-heap or raise --memory-limit"
                ),
            )
        )

    findings.sort(key=lambda item: (item.code, item.detail))
    return HostResourceReport(
        status="pass" if not findings else "fail",
        mem_total_bytes=mem_total,
        mem_available_bytes=mem_available,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        cpu_count=observed_cpu,
        disk_free_bytes=disk_free,
        requested_memory_limit_bytes=requirement.memory_limit_bytes,
        declared_jvm_max_heap=declared_jvm_max_heap,
        findings=findings,
    )


__all__ = [
    "DEFAULT_FREEROUTING_MAX_HEAP",
    "ResourceRequirement",
    "check_host_resources",
    "parse_memory_bytes",
]
