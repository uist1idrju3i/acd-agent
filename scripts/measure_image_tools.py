#!/usr/bin/env python3
"""Measure and serialize tool versions from a digest-pinned container image."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

_IMAGE_REF = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}\Z")
_Runner = Callable[[list[str]], str]

_COMMANDS: dict[str, list[str]] = {
    "ccache": ["ccache", "--version"],
    "cmake": ["cmake", "--version"],
    "esp-idf": [
        "bash",
        "-lc",
        '. "${IDF_PATH}/export.sh" >/dev/null 2>&1 && idf.py --version',
    ],
    "freerouting": ["freerouting", "--version"],
    "git": ["git", "--version"],
    "java": ["java", "-version"],
    "kicad-cli": ["kicad-cli", "--version"],
    "libcairo2": ["dpkg-query", "-W", "-f=${Version}", "libcairo2"],
    "ngspice": ["ngspice", "--version"],
    "ninja": ["ninja", "--version"],
    "python3.14": ["python3.14", "--version"],
    "qemu-system-riscv32": ["qemu-system-riscv32", "--version"],
    "uv": ["uv", "--version"],
}


def _docker_prefix(image_ref: str) -> list[str]:
    # The server image sets an agent-server ENTRYPOINT, so it is bypassed here.
    return ["docker", "run", "--rm", "--entrypoint", "", image_ref]


def _docker_run(command: list[str], argv: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        # freerouting --version prints a valid banner and then exits nonzero.
        if argv == ["freerouting", "--version"] and re.search(
            r"Freerouting v[0-9]+\.[0-9]+\.[0-9]+", output
        ):
            return output
        raise RuntimeError(f"command failed: {' '.join(argv)}")
    return output


def _runner_for_image(image_ref: str) -> _Runner:
    def run(argv: list[str]) -> str:
        return _docker_run([*_docker_prefix(image_ref), *argv], argv)

    return run


def _single_line(output: str, key: str) -> str:
    value = output.strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{key}: expected one output line")
    return value


def _first_line(output: str, key: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{key}: output is empty")
    return lines[0]


def _java_version(output: str) -> str:
    match = re.search(r'openjdk version "([^"]+)" (\S+)', output)
    semeru = re.search(r"IBM Semeru Runtime Open Edition (\S+)", output)
    openj9 = re.search(r"openj9-([0-9]+\.[0-9]+\.[0-9]+)", output)
    if match is None or semeru is None or openj9 is None:
        raise ValueError("java: version output is unparsable")
    version, release_date = match.groups()
    return (
        f"openjdk {version} {release_date} "
        f"(IBM Semeru Runtime Open Edition {semeru.group(1)}, "
        f"Eclipse OpenJ9 {openj9.group(1)})"
    )


def _measure(key: str, output: str) -> str:
    if key == "kicad-cli":
        return _single_line(output, key)
    if key == "freerouting":
        match = re.search(r"Freerouting v([0-9]+\.[0-9]+\.[0-9]+)", output)
        if match is None:
            raise ValueError(f"{key}: version output is unparsable")
        return match.group(1)
    if key == "ngspice":
        match = re.search(r"ngspice-(\S+)\s*:", output)
        if match is None:
            raise ValueError(f"{key}: version output is unparsable")
        return match.group(1)
    if key in {"python3.14", "uv", "git", "qemu-system-riscv32", "ccache", "cmake"}:
        return _first_line(output, key)
    if key == "java":
        return _java_version(output)
    if key == "libcairo2" or key == "ninja":
        return _single_line(output, key)
    if key == "esp-idf":
        match = re.search(r"ESP-IDF v[^\s]+", output)
        if match is None:
            raise ValueError(f"{key}: version output is unparsable")
        return match.group(0)
    raise ValueError(f"unknown tool: {key}")


def measure_image_tools(
    image_ref: str,
    out: Path,
    *,
    run: _Runner | None = None,
) -> dict[str, str]:
    """Measure all supported tools and write the result only after success."""
    if _IMAGE_REF.fullmatch(image_ref) is None:
        raise ValueError("image ref must be digest-pinned")
    runner = run or _runner_for_image(image_ref)
    measured: dict[str, str] = {}
    for key, argv in _COMMANDS.items():
        try:
            output = runner(argv)
            measured[key] = _measure(key, output)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"{key}: {exc}") from exc
    serialized = json.dumps(measured, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out.write_text(serialized, encoding="utf-8")
    return measured


def main(argv: list[str] | None = None, *, run: _Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        measure_image_tools(args.image_ref, args.out, run=run)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
