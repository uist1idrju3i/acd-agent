"""Toolchain probing tests.

The ESP-IDF and QEMU probes must fail loudly when a tool is absent, and must
report a parsed version when present. Tests that need the real tools skip when
they are unavailable so the skill stays testable on a bare machine.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fw_build import EspIdfBuilder, ToolchainUnavailableError
from fw_qemu import QemuRunner, QemuUnavailableError
from fw_run import resolve_tool

_IDF_PATH = os.environ.get("IDF_PATH")
IDF_AVAILABLE = _IDF_PATH is not None and (Path(_IDF_PATH) / "export.sh").is_file()
QEMU_AVAILABLE = resolve_tool("qemu-system-riscv32") is not None


def test_builder_fails_when_idf_path_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IDF_PATH", raising=False)
    with pytest.raises(ToolchainUnavailableError, match="IDF_PATH"):
        EspIdfBuilder()


def test_builder_fails_when_export_script_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IDF_PATH", str(tmp_path))
    with pytest.raises(ToolchainUnavailableError, match="export script missing"):
        EspIdfBuilder()


def test_qemu_fails_when_binary_missing() -> None:
    with pytest.raises(QemuUnavailableError, match="not found"):
        QemuRunner(binary="qemu-system-does-not-exist")


@pytest.mark.skipif(not IDF_AVAILABLE, reason="ESP-IDF toolchain not installed")
def test_idf_version_is_parsed() -> None:
    assert EspIdfBuilder().version().startswith("v")


@pytest.mark.skipif(not QEMU_AVAILABLE, reason="qemu-system-riscv32 not installed")
def test_qemu_version_is_parsed() -> None:
    assert QemuRunner().version()
