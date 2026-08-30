"""Host resource preflight tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from acd.openhands.host_resources import ResourceRequirement, check_host_resources

MIB = 1024 * 1024
GIB = 1024 * MIB


def _meminfo(
    path: Path,
    *,
    total_mib: int | None = 16 * 1024,
    available_mib: int | None = 16 * 1024,
    swap_total_mib: int | None = 2 * 1024,
    swap_free_mib: int | None = 2 * 1024,
) -> None:
    def line(name: str, value: int | None) -> str:
        return "" if value is None else f"{name}:       {value * 1024} kB"

    path.write_text(
        "\n".join(
            line(name, value)
            for name, value in (
                ("MemTotal", total_mib),
                ("MemAvailable", available_mib),
                ("SwapTotal", swap_total_mib),
                ("SwapFree", swap_free_mib),
            )
            if value is not None
        )
        + "\n"
    )


def _requirements(
    *,
    memory_limit_bytes: int = 8 * GIB,
    jvm_max_heap: str = "2g",
) -> ResourceRequirement:
    return ResourceRequirement(
        memory_limit_bytes=memory_limit_bytes,
        jvm_max_heap=jvm_max_heap,
    )


def _disk(monkeypatch: pytest.MonkeyPatch, free: int = 16 * GIB) -> None:
    def disk_usage(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=free)

    monkeypatch.setattr(
        "acd.openhands.host_resources.shutil.disk_usage",
        disk_usage,
    )

    def cpu_count() -> int:
        return 4

    monkeypatch.setattr("acd.openhands.host_resources.os.cpu_count", cpu_count)


def test_host_resource_preflight_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meminfo = tmp_path / "meminfo"
    _meminfo(meminfo)
    _disk(monkeypatch)

    report = check_host_resources(_requirements(), meminfo_path=meminfo, disk_path=tmp_path)

    assert report.status == "pass"
    assert report.findings == []
    assert report.declared_jvm_max_heap == "2g"


@pytest.mark.parametrize(
    (
        "code",
        "memory_limit_bytes",
        "jvm_max_heap",
        "meminfo_kwargs",
        "disk_free",
        "cpu_count",
    ),
    [
        (
            "host.memory.total_insufficient",
            8 * GIB,
            "2g",
            {"total_mib": 4096},
            16 * GIB,
            4,
        ),
        (
            "host.memory.available_insufficient",
            8 * GIB,
            "2g",
            {"available_mib": 4096},
            16 * GIB,
            4,
        ),
        (
            "host.swap.unknown",
            8 * GIB,
            "2g",
            {"swap_total_mib": None},
            16 * GIB,
            4,
        ),
        (
            "host.cpu.insufficient",
            8 * GIB,
            "2g",
            {},
            16 * GIB,
            1,
        ),
        (
            "host.disk.insufficient",
            8 * GIB,
            "2g",
            {},
            4 * GIB,
            4,
        ),
        (
            "runtime.jvm_heap.exceeds_container_limit",
            2 * GIB,
            "2g",
            {},
            16 * GIB,
            4,
        ),
    ],
)
def test_host_resource_preflight_reports_each_insufficient_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    memory_limit_bytes: int,
    jvm_max_heap: str,
    meminfo_kwargs: dict[str, int | None],
    disk_free: int,
    cpu_count: int,
) -> None:
    meminfo = tmp_path / "meminfo"
    _meminfo(meminfo, **meminfo_kwargs)
    def disk_usage(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=disk_free)

    monkeypatch.setattr("acd.openhands.host_resources.shutil.disk_usage", disk_usage)

    def observed_cpu_count() -> int:
        return cpu_count

    monkeypatch.setattr("acd.openhands.host_resources.os.cpu_count", observed_cpu_count)

    report = check_host_resources(
        _requirements(
            memory_limit_bytes=memory_limit_bytes,
            jvm_max_heap=jvm_max_heap,
        ),
        meminfo_path=meminfo,
        disk_path=tmp_path,
    )

    assert code in {finding.code for finding in report.findings}
    assert report.status == "fail"


def test_host_resource_preflight_reports_unknown_cpu_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meminfo = tmp_path / "meminfo"
    _meminfo(meminfo)
    def unknown_cpu_count() -> None:
        return None

    monkeypatch.setattr("acd.openhands.host_resources.os.cpu_count", unknown_cpu_count)

    def unavailable_disk(_path: Path) -> SimpleNamespace:
        raise OSError("disk unavailable")

    monkeypatch.setattr("acd.openhands.host_resources.shutil.disk_usage", unavailable_disk)

    report = check_host_resources(_requirements(), meminfo_path=meminfo, disk_path=tmp_path)

    assert {finding.code for finding in report.findings} >= {
        "host.cpu.unknown",
        "host.disk.unknown",
    }


@pytest.mark.parametrize("meminfo_contents", ["", "MemTotal: invalid kB\n", "not meminfo"])
def test_invalid_meminfo_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, meminfo_contents: str
) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(meminfo_contents)
    _disk(monkeypatch)

    report = check_host_resources(_requirements(), meminfo_path=meminfo, disk_path=tmp_path)

    assert report.status == "fail"
    assert "host.memory.unknown" in {finding.code for finding in report.findings}


def test_missing_meminfo_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _disk(monkeypatch)

    report = check_host_resources(
        _requirements(),
        meminfo_path=tmp_path / "missing-meminfo",
        disk_path=tmp_path,
    )

    assert report.status == "fail"
    assert "host.memory.unknown" in {finding.code for finding in report.findings}


def test_o2_incident_does_not_add_swap_to_memory_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meminfo = tmp_path / "meminfo"
    _meminfo(
        meminfo,
        total_mib=1641,
        available_mib=1200,
        swap_total_mib=5116,
        swap_free_mib=5116,
    )
    _disk(monkeypatch)

    report = check_host_resources(_requirements(), meminfo_path=meminfo, disk_path=tmp_path)

    codes = {finding.code for finding in report.findings}
    assert "host.memory.total_insufficient" in codes
    assert "host.memory.available_insufficient" in codes
    assert report.mem_total_bytes == 1641 * MIB
    assert report.swap_total_bytes == 5116 * MIB


def test_findings_are_sorted_by_code_and_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meminfo = tmp_path / "meminfo"
    _meminfo(meminfo, total_mib=1024, available_mib=512, swap_total_mib=0, swap_free_mib=0)
    monkeypatch.setattr("acd.openhands.host_resources.os.cpu_count", lambda: 1)
    def disk_usage(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=1)

    monkeypatch.setattr("acd.openhands.host_resources.shutil.disk_usage", disk_usage)

    report = check_host_resources(_requirements(), meminfo_path=meminfo, disk_path=tmp_path)

    assert [(finding.code, finding.detail) for finding in report.findings] == sorted(
        (finding.code, finding.detail) for finding in report.findings
    )
