"""Tests for digest-pinned image tool measurement."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.measure_image_tools import main

_IMAGE = "ghcr.io/example/acd-tools@sha256:" + "a" * 64


def _outputs() -> dict[tuple[str, ...], str]:
    return {
        ("ccache", "--version"): "ccache version 4.12.3\n",
        ("cmake", "--version"): "cmake version 4.2.3\n",
        (
            "bash",
            "-lc",
            '. "${IDF_PATH}/export.sh" >/dev/null 2>&1 && idf.py --version',
        ): "ESP-IDF v6.1\n",
        ("freerouting", "--version"): "INFO Freerouting v2.3.0 (build-date: 2026-08-07)\n",
        ("git", "--version"): "git version 2.53.0\n",
        (
            "java",
            "-version",
        ): (
            'openjdk version "26.0.2.1" 2026-08-18\n'
            "IBM Semeru Runtime Open Edition 26.0.2.10 (build 26.0.2.1+1)\n"
            "Eclipse OpenJ9 VM 26.0.2.10 "
            "(build 26.0.2.1+1-openj9-0.61.0, JRE 26 Linux amd64-64-Bit)\n"
        ),
        ("kicad-cli", "--version"): "10.0.6\n",
        ("dpkg-query", "-W", "-f=${Version}", "libcairo2"): "1.18.4-3\n",
        ("ngspice", "--version"): "ngspice-45.2 : circuit simulator\n",
        ("ninja", "--version"): "1.13.2\n",
        ("python3.14", "--version"): "Python 3.14.4\n",
        (
            "qemu-system-riscv32",
            "--version",
        ): "QEMU emulator version 9.2.2 (esp_develop_9.2.2_20260417)\n",
        ("uv", "--version"): "uv 0.12.7 (x86_64-unknown-linux-gnu)\n",
    }


def test_measurement_extracts_expected_versions(tmp_path: Path) -> None:
    outputs = _outputs()

    def fake_run(argv: list[str]) -> str:
        return outputs[tuple(argv)]

    out = tmp_path / "tools.json"
    assert main(["--image-ref", _IMAGE, "--out", str(out)], run=fake_run) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "ccache": "ccache version 4.12.3",
        "cmake": "cmake version 4.2.3",
        "esp-idf": "ESP-IDF v6.1",
        "freerouting": "2.3.0",
        "git": "git version 2.53.0",
        "java": (
            "openjdk 26.0.2.1 2026-08-18 "
            "(IBM Semeru Runtime Open Edition 26.0.2.10, Eclipse OpenJ9 0.61.0)"
        ),
        "kicad-cli": "10.0.6",
        "libcairo2": "1.18.4-3",
        "ngspice": "45.2",
        "ninja": "1.13.2",
        "python3.14": "Python 3.14.4",
        "qemu-system-riscv32": "QEMU emulator version 9.2.2 (esp_develop_9.2.2_20260417)",
        "uv": "uv 0.12.7 (x86_64-unknown-linux-gnu)",
    }


def test_measurement_command_failure_is_fail_closed(tmp_path: Path) -> None:
    outputs = _outputs()

    def fake_run(argv: list[str]) -> str:
        if argv == ["ninja", "--version"]:
            raise RuntimeError("command failed")
        return outputs[tuple(argv)]

    out = tmp_path / "tools.json"
    assert main(["--image-ref", _IMAGE, "--out", str(out)], run=fake_run) == 1
    assert not out.exists()


def test_measurement_parse_failure_is_fail_closed(tmp_path: Path) -> None:
    outputs = _outputs()
    outputs[("freerouting", "--version")] = "unknown\n"

    def fake_run(argv: list[str]) -> str:
        return outputs[tuple(argv)]

    out = tmp_path / "tools.json"
    assert main(["--image-ref", _IMAGE, "--out", str(out)], run=fake_run) == 1
    assert not out.exists()


def test_measurement_rejects_non_digest_image(tmp_path: Path) -> None:
    out = tmp_path / "tools.json"
    assert main(["--image-ref", "ghcr.io/example/acd-tools:latest", "--out", str(out)]) == 1
    assert not out.exists()
