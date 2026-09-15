"""Checks over the host runtime, Docker, locked images and host resources.

This package is part of the install doctor L3 observation and uses only the
standard library; it never imports ``acd``.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from install_doctor_checks.common import (
    HOST_JVM_MAX_HEAP_BYTES,
    HOST_JVM_NON_HEAP_RESERVE_BYTES,
    HOST_MEMORY_HEADROOM_BYTES,
    HOST_MEMORY_LIMIT_BYTES,
    HOST_MIN_CPU_COUNT,
    HOST_MIN_DISK_FREE_BYTES,
    MIB,
    check_result,
    docker_image_command,
    image_section,
    in_container,
    locked_server_image,
    pull_timeout,
    run_version,
)


def runtime_check() -> dict[str, Any]:
    version = ".".join(str(value) for value in sys.version_info[:3])
    errors: list[str] = []
    if (sys.version_info.major, sys.version_info.minor) < (3, 12):
        errors.append(f"Python {version} is below required 3.12")
    uv_path = shutil.which("uv")
    if uv_path is None:
        errors.append("uv is not present on PATH")
    else:
        try:
            completed = subprocess.run(
                [uv_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
            if completed.returncode != 0:
                errors.append("uv --version failed")
            else:
                uv_version = (
                    completed.stdout.strip().splitlines()[0] if completed.stdout else "unknown"
                )
                version = f"Python {version}; {uv_version}"
        except (OSError, subprocess.TimeoutExpired):
            errors.append("uv --version could not be executed")
    if errors:
        return check_result(
            "runtime prerequisites", True, "fail", "; ".join(errors), version, path="plugin"
        )
    return check_result(
        "runtime prerequisites",
        True,
        "pass",
        "Python >=3.12 and uv are available",
        version,
        path="plugin",
    )


def docker_check() -> dict[str, Any]:
    if in_container():
        return check_result(
            "docker capability",
            True,
            "pass",
            "running inside the locked ACD image; docker-in-docker is not required",
            "container runtime",
            path="authoritative-path",
        )
    docker = shutil.which("docker")
    if docker is None:
        return check_result(
            "docker capability",
            True,
            "fail",
            "docker CLI is absent; authoritative Evidence from a digest-fixed container "
            "cannot be generated. Host execution must not be used as a passing substitute.",
            "not installed",
            path="authoritative-path",
        )
    version = run_version("docker", ["--version"], r"Docker version ([^,\s]+)") or "unknown"
    try:
        completed = subprocess.run(
            [docker, "info"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed is None or completed.returncode != 0:
        return check_result(
            "docker capability",
            True,
            "fail",
            "docker info is not reachable; authoritative Evidence from a digest-fixed "
            "container cannot be generated. Host execution must not be used as a "
            "passing substitute.",
            version,
            path="authoritative-path",
        )
    return check_result(
        "docker capability",
        True,
        "pass",
        "docker CLI and docker info are reachable; this does not itself run a gate",
        version,
        path="authoritative-path",
    )


def server_image_check(workspace: Path | None, *, pull: bool) -> dict[str, Any]:
    if in_container():
        return check_result(
            "locked ACD server image",
            True,
            "pass",
            "running inside the locked ACD server image",
            path="authoritative-path",
        )
    reference, error = locked_server_image(workspace)
    if reference is None:
        return check_result(
            "locked ACD server image",
            True,
            "unknown",
            error or "unknown",
            path="authoritative-path",
        )
    docker = shutil.which("docker")
    if docker is None:
        return check_result(
            "locked ACD server image",
            True,
            "fail",
            f"docker CLI is absent; cannot inspect {reference}",
            reference,
            path="authoritative-path",
        )
    try:
        inspected = subprocess.run(
            [docker, "image", "inspect", reference],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result(
            "locked ACD server image", True, "fail", str(exc), reference, path="authoritative-path"
        )
    if inspected.returncode == 0:
        return check_result(
            "locked ACD server image",
            True,
            "pass",
            f"locked server image is available locally: {reference}",
            reference,
            path="authoritative-path",
        )
    if not pull:
        return check_result(
            "locked ACD server image",
            True,
            "fail",
            f"{reference} is not available locally and --no-pull was requested",
            reference,
            path="authoritative-path",
            next_step=f"docker pull {reference}",
        )
    try:
        pulled = subprocess.run(
            [docker, "pull", reference],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=pull_timeout(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result(
            "locked ACD server image",
            True,
            "fail",
            str(exc),
            reference,
            path="authoritative-path",
            next_step=f"docker pull {reference}",
        )
    if pulled.returncode != 0:
        detail = pulled.stderr.strip() or pulled.stdout.strip() or "docker pull failed"
        return check_result(
            "locked ACD server image",
            True,
            "fail",
            detail,
            reference,
            path="authoritative-path",
            next_step=f"docker pull {reference}",
        )
    return check_result(
        "locked ACD server image",
        True,
        "pass",
        f"pulled locked server image: {reference}",
        reference,
        path="authoritative-path",
    )


def eda_check(workspace: Path | None = None) -> dict[str, Any]:
    probes = {
        "kicad-cli": (["version"], r"([0-9]+\.[0-9]+\.[0-9]+)", False),
        "freerouting": (["--version"], r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)", True),
    }
    if in_container():
        observations = {
            tool: run_version(tool, args, pattern, allow_nonzero_exit=allow_nonzero)
            for tool, (args, pattern, allow_nonzero) in probes.items()
        }
        detail_prefix = "EDA capabilities are observed from the locked ACD image"
    else:
        reference, error = locked_server_image(workspace)
        if reference is None:
            return check_result(
                "EDA capabilities", False, "fail", error or "unknown", path="authoritative-path"
            )
        script = (
            "printf '%s\\n' '=== kicad-cli ==='; "
            "kicad-cli version 2>&1 || true; "
            "printf '%s\\n' '=== freerouting ==='; "
            "freerouting --version 2>&1 || true"
        )
        output, error = docker_image_command(reference, script, timeout=30)
        if output is None:
            return check_result(
                "EDA capabilities",
                False,
                "fail",
                error or "docker probe failed",
                path="authoritative-path",
            )
        observations = {}
        for tool, (_, pattern, _) in probes.items():
            match = re.search(pattern, image_section(output, tool))
            observations[tool] = match.group(1) if match else None
        detail_prefix = f"EDA capabilities observed inside {reference}"
    present = [
        f"{tool}={version}"
        for tool, version in observations.items()
        if version not in (None, "unknown")
    ]
    missing = [tool for tool, version in observations.items() if version in (None, "unknown")]
    detail = (
        f"present: {', '.join(present) if present else 'none'}; "
        f"missing: {', '.join(missing) if missing else 'none'}. {detail_prefix}."
    )
    if missing:
        detail += " One or more image tools could not be observed."
    result = "fail" if missing else "pass"
    observed_version = ", ".join(
        f"{tool}={version or 'unavailable'}" for tool, version in observations.items()
    )
    return check_result(
        "EDA capabilities", False, result, detail, observed_version, path="authoritative-path"
    )


def _resource_mib(value: int | None) -> str:
    return "unknown" if value is None else f"{value / MIB:.2f} MiB"


def _read_host_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return values
    for line in lines:
        name, separator, raw = line.partition(":")
        if not separator:
            continue
        fields = raw.strip().split()
        if len(fields) not in (1, 2) or not fields[0].isdigit():
            continue
        if len(fields) == 2 and fields[1].lower() != "kb":
            continue
        values[name] = int(fields[0]) * (1024 if len(fields) == 2 else 1)
    return values


def host_resource_check() -> dict[str, Any]:
    """Check optional host prerequisites without importing the ACD package."""
    meminfo = _read_host_meminfo()
    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")
    findings: list[tuple[str, str]] = []
    if total is None or available is None:
        findings.append(
            (
                "host.memory.unknown",
                (
                    f"host memory could not be parsed; observed total={_resource_mib(total)}, "
                    f"available={_resource_mib(available)}; requested "
                    f"--memory-limit={_resource_mib(HOST_MEMORY_LIMIT_BYTES)}"
                ),
            )
        )
    else:
        usable_total = total - HOST_MEMORY_HEADROOM_BYTES
        if usable_total < HOST_MEMORY_LIMIT_BYTES:
            findings.append(
                (
                    "host.memory.total_insufficient",
                    (
                        f"MemTotal={_resource_mib(total)} minus headroom="
                        f"{_resource_mib(HOST_MEMORY_HEADROOM_BYTES)} leaves "
                        f"{_resource_mib(usable_total)}; requested "
                        f"--memory-limit={_resource_mib(HOST_MEMORY_LIMIT_BYTES)} exceeds "
                        f"this limit, lower --memory-limit to at most "
                        f"{_resource_mib(usable_total)}"
                    ),
                )
            )
        if available < HOST_MEMORY_LIMIT_BYTES:
            findings.append(
                (
                    "host.memory.available_insufficient",
                    (
                        f"MemAvailable={_resource_mib(available)}; requested "
                        f"--memory-limit={_resource_mib(HOST_MEMORY_LIMIT_BYTES)} exceeds "
                        f"available memory, lower --memory-limit to at most "
                        f"{_resource_mib(available)}"
                    ),
                )
            )
    if swap_total is None or swap_free is None:
        findings.append(
            (
                "host.swap.unknown",
                (
                    f"SwapTotal={_resource_mib(swap_total)}, SwapFree={_resource_mib(swap_free)} "
                    "could not be observed; swap is not added to the memory limit "
                    f"requirement of {_resource_mib(HOST_MEMORY_LIMIT_BYTES)}"
                ),
            )
        )
    cpu_count = os.cpu_count()
    if cpu_count is None:
        findings.append(
            (
                "host.cpu.unknown",
                f"host CPU count is unknown; required at least {HOST_MIN_CPU_COUNT} cores",
            )
        )
    elif cpu_count < HOST_MIN_CPU_COUNT:
        findings.append(
            (
                "host.cpu.insufficient",
                f"observed CPU count={cpu_count}; required at least {HOST_MIN_CPU_COUNT} cores",
            )
        )
    try:
        disk_free = shutil.disk_usage(Path.cwd()).free
    except OSError:
        disk_free = None
    if disk_free is None:
        findings.append(
            (
                "host.disk.unknown",
                f"free disk space at {Path.cwd()} is unknown; required at least "
                f"{_resource_mib(HOST_MIN_DISK_FREE_BYTES)}",
            )
        )
    elif disk_free < HOST_MIN_DISK_FREE_BYTES:
        findings.append(
            (
                "host.disk.insufficient",
                f"observed free disk={_resource_mib(disk_free)}; required at least "
                f"{_resource_mib(HOST_MIN_DISK_FREE_BYTES)}",
            )
        )
    if HOST_JVM_MAX_HEAP_BYTES + HOST_JVM_NON_HEAP_RESERVE_BYTES > HOST_MEMORY_LIMIT_BYTES:
        findings.append(
            (
                "runtime.jvm_heap.exceeds_container_limit",
                (
                    f"declared JVM max heap={_resource_mib(HOST_JVM_MAX_HEAP_BYTES)} "
                    f"plus non-heap reserve={_resource_mib(HOST_JVM_NON_HEAP_RESERVE_BYTES)} "
                    f"exceeds container --memory-limit={_resource_mib(HOST_MEMORY_LIMIT_BYTES)}; "
                    "lower --jvm-max-heap or raise --memory-limit"
                ),
            )
        )
    findings.sort()
    if not findings:
        return check_result(
            "host resource preflight",
            False,
            "pass",
            "host resource limits satisfy the optional 8 GiB container profile",
            "8g memory / 2g JVM heap",
            path="authoritative-path",
        )
    result = "unknown" if any(code.endswith(".unknown") for code, _ in findings) else "fail"
    detail = "; ".join(f"{code}: {message}" for code, message in findings)
    return check_result("host resource preflight", False, result, detail, path="authoritative-path")


def resolve_firmware_tool(binary: str) -> str | None:
    path = shutil.which(binary)
    if path is not None:
        return path
    idf_path = os.environ.get("IDF_PATH")
    if not idf_path:
        return None
    export = Path(idf_path) / "export.sh"
    if not export.is_file():
        return None
    try:
        completed = subprocess.run(
            [
                "bash",
                "-c",
                f". {shlex.quote(str(export))} >/dev/null && command -v {shlex.quote(binary)}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    resolved = completed.stdout.strip()
    return resolved if completed.returncode == 0 and resolved else None


def host_firmware_toolchain_check() -> dict[str, Any]:
    """Observe the host firmware toolchain on the provisional path only."""
    idf_path = os.environ.get("IDF_PATH")
    idf_export = Path(idf_path) / "export.sh" if idf_path else None
    idf_ok = bool(idf_export and idf_export.is_file() and os.access(idf_export, os.R_OK))
    qemu = resolve_firmware_tool("qemu-system-riscv32")
    cmake = shutil.which("cmake")
    missing = [
        name
        for name, present in (
            ("IDF_PATH/export.sh", idf_ok),
            ("qemu-system-riscv32", qemu is not None),
            ("cmake", cmake is not None),
        )
        if not present
    ]
    observed = (
        f"IDF_PATH={idf_path or 'unset'}, "
        f"qemu-system-riscv32={qemu or 'unavailable'}, cmake={cmake or 'unavailable'}"
    )
    if missing:
        return check_result(
            "host firmware toolchain",
            False,
            "unavailable",
            f"host toolchain is provisional only; missing: {', '.join(missing)}; {observed}",
            observed,
            path="provisional-path",
        )
    return check_result(
        "host firmware toolchain",
        False,
        "pass",
        f"host firmware toolchain is available; {observed}",
        observed,
        path="provisional-path",
    )
