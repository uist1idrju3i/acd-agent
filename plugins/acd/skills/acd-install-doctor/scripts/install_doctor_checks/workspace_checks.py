"""Checks over an optional workspace checkout (git, lock, digests, firmware).

This package is part of the install doctor L3 observation and uses only the
standard library; it never imports ``acd``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from install_doctor_checks.common import (
    check_result,
    docker_image_command,
    image_section,
    in_container,
    locked_server_image,
)
from install_doctor_checks.host_checks import (
    host_firmware_toolchain_check,
    resolve_firmware_tool,
)


def workspace_repository_check(workspace: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result("workspace repository", True, "unknown", str(exc), path="plugin")
    if completed.returncode != 0:
        return check_result(
            "workspace repository",
            True,
            "fail",
            "git rev-parse could not identify a repository",
            path="plugin",
        )
    try:
        root = Path(completed.stdout.strip()).resolve()
        expected = workspace.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return check_result("workspace repository", True, "unknown", str(exc), path="plugin")
    if root != expected:
        return check_result(
            "workspace repository",
            True,
            "fail",
            f"Git root is {root}, expected {expected}",
            path="plugin",
        )
    return check_result(
        "workspace repository",
        True,
        "pass",
        "workspace is a Git repository",
        str(root),
        path="plugin",
    )


def workspace_submodule_check(workspace: Path) -> dict[str, Any]:
    submodule = workspace / "vendor" / "software-agent-sdk"
    if not (submodule / "pyproject.toml").is_file():
        return check_result(
            "workspace submodules",
            True,
            "fail",
            f"submodule is not populated: {submodule}",
            path="plugin",
        )
    try:
        completed = subprocess.run(
            ["git", "submodule", "status", "--", "vendor/software-agent-sdk"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result("workspace submodules", True, "unknown", str(exc), path="plugin")
    status = completed.stdout.strip()
    if completed.returncode != 0 or not status or status[0] in "-?":
        return check_result(
            "workspace submodules",
            True,
            "fail",
            f"submodule status is not initialized: {status or completed.stderr.strip()}",
            path="plugin",
        )
    return check_result(
        "workspace submodules",
        True,
        "pass",
        "vendor/software-agent-sdk is initialized",
        status.split()[0].lstrip("+"),
        path="plugin",
    )


def workspace_lock_check(workspace: Path) -> dict[str, Any]:
    if not (workspace / "pyproject.toml").is_file() or not (workspace / "uv.lock").is_file():
        return check_result(
            "workspace lock synchronization",
            True,
            "fail",
            "pyproject.toml or uv.lock is missing",
            path="plugin",
        )
    uv = shutil.which("uv")
    if uv is None:
        return check_result(
            "workspace lock synchronization",
            True,
            "unknown",
            "uv is not present on PATH; lock synchronization cannot be checked",
            path="plugin",
        )
    try:
        completed = subprocess.run(
            [uv, "lock", "--check"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result(
            "workspace lock synchronization", True, "unknown", str(exc), path="plugin"
        )
    if completed.returncode != 0:
        return check_result(
            "workspace lock synchronization",
            True,
            "fail",
            completed.stderr.strip() or completed.stdout.strip() or "uv lock --check failed",
            path="plugin",
        )
    return check_result(
        "workspace lock synchronization",
        True,
        "pass",
        "uv.lock is synchronized with pyproject.toml",
        path="plugin",
    )


def workspace_digest_check(workspace: Path) -> dict[str, Any]:
    if in_container():
        return check_result(
            "workspace lock digest",
            True,
            "pass",
            "running inside the locked ACD server image",
            path="authoritative-path",
        )
    reference, error = locked_server_image(workspace)
    if reference is None:
        return check_result(
            "workspace lock digest", True, "unknown", error or "unknown", path="authoritative-path"
        )
    digest = reference.rsplit("@", 1)[-1]
    docker = shutil.which("docker")
    if docker is None:
        return check_result(
            "workspace lock digest",
            True,
            "fail",
            f"docker is unavailable; cannot inspect {reference}",
            digest,
            path="authoritative-path",
        )
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", reference],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        return check_result(
            "workspace lock digest", True, "fail", str(exc), digest, path="authoritative-path"
        )
    if completed.returncode != 0:
        return check_result(
            "workspace lock digest",
            True,
            "fail",
            f"{reference} is not available locally; network pull is not attempted",
            digest,
            path="authoritative-path",
        )
    return check_result(
        "workspace lock digest",
        True,
        "pass",
        f"locked image is available locally: {reference}",
        digest,
        path="authoritative-path",
    )


def _workspace_firmware_check(workspace: Path) -> dict[str, Any]:
    if not in_container():
        reference, error = locked_server_image(workspace)
        if reference is None:
            return check_result(
                "workspace firmware prerequisites",
                True,
                "fail",
                error or "locked server image is unavailable",
                path="authoritative-path",
            )
        script = (
            "printf '%s\\n' '=== IDF_PATH/export.sh ==='; "
            'if test -n "${IDF_PATH:-}" && test -f "$IDF_PATH/export.sh" '
            '&& test -r "$IDF_PATH/export.sh"; '
            "then printf '%s\\n' present; else printf '%s\\n' missing; fi; "
            "printf '%s\\n' '=== qemu-system-riscv32 ==='; "
            "qemu-system-riscv32 --version 2>&1 || true; "
            "printf '%s\\n' '=== cmake ==='; "
            "cmake --version 2>&1 || true"
        )
        output, error = docker_image_command(reference, script, timeout=30)
        if output is None:
            return check_result(
                "workspace firmware prerequisites",
                True,
                "fail",
                error or "docker probe failed",
                reference,
                path="authoritative-path",
            )
        idf_output = image_section(output, "IDF_PATH/export.sh")
        qemu_output = image_section(output, "qemu-system-riscv32")
        cmake_output = image_section(output, "cmake")
        idf_ok = "present" in idf_output.split()
        qemu_match = re.search(r"QEMU emulator version ([^\s]+)", qemu_output)
        cmake_match = re.search(r"cmake version ([^\s]+)", cmake_output)
        missing = [
            name
            for name, present in (
                ("IDF_PATH/export.sh", idf_ok),
                ("qemu-system-riscv32", qemu_match is not None),
                ("cmake", cmake_match is not None),
            )
            if not present
        ]
        observed = (
            f"IDF_PATH/export.sh={'present' if idf_ok else 'missing'}, "
            f"qemu-system-riscv32={qemu_match.group(1) if qemu_match else 'unavailable'}, "
            f"cmake={cmake_match.group(1) if cmake_match else 'unavailable'}"
        )
        if missing:
            return check_result(
                "workspace firmware prerequisites",
                True,
                "fail",
                f"missing: {', '.join(missing)}; observed inside {reference}: {observed}",
                observed,
                path="authoritative-path",
            )
        return check_result(
            "workspace firmware prerequisites",
            True,
            "pass",
            f"ESP-IDF export, QEMU, and CMake are available inside {reference}: {observed}",
            observed,
            path="authoritative-path",
        )
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
            "workspace firmware prerequisites",
            True,
            "fail",
            f"missing: {', '.join(missing)}; {observed}",
            observed,
            path="authoritative-path",
        )
    return check_result(
        "workspace firmware prerequisites",
        True,
        "pass",
        f"ESP-IDF export, QEMU, and CMake are available; {observed}",
        observed,
        path="authoritative-path",
    )


def workspace_checks(workspace: Path) -> list[dict[str, Any]]:
    checks = [
        workspace_repository_check(workspace),
        workspace_submodule_check(workspace),
        workspace_lock_check(workspace),
        workspace_digest_check(workspace),
        _workspace_firmware_check(workspace),
    ]
    if not in_container():
        checks.append(host_firmware_toolchain_check())
    return checks
