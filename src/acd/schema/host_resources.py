"""Contracts for host resource preflight observations."""

from __future__ import annotations

from typing import Literal

from pydantic import StrictInt

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NonEmptyStr,
    SchemaVersion,
)

HostResourceCode = Literal[
    "host.memory.unknown",
    "host.memory.total_insufficient",
    "host.memory.available_insufficient",
    "host.swap.unknown",
    "host.cpu.unknown",
    "host.cpu.insufficient",
    "host.disk.unknown",
    "host.disk.insufficient",
    "runtime.jvm_heap.exceeds_container_limit",
]


class HostResourceFinding(AcdModel):
    """One deterministic host resource preflight finding."""

    code: HostResourceCode
    detail: NonEmptyStr


class HostResourceReport(AcdModel):
    """Host prerequisites, not an L3 observation or lane acceptance record.

    This is a container-start prerequisite check. A pass does not mean that a
    lane gate passes and does not create authoritative Evidence.
    """

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    status: Literal["pass", "fail"]
    mem_total_bytes: StrictInt | None
    mem_available_bytes: StrictInt | None
    swap_total_bytes: StrictInt | None
    swap_free_bytes: StrictInt | None
    cpu_count: StrictInt | None
    disk_free_bytes: StrictInt | None
    requested_memory_limit_bytes: StrictInt
    declared_jvm_max_heap: NonEmptyStr
    findings: list[HostResourceFinding]
