"""ESP-IDF build wrapper with a pinned, probed toolchain."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fw_project import FirmwareProject
from fw_run import run_command, sha256_paths


class ToolchainUnavailableError(RuntimeError):
    """Raised when the ESP-IDF toolchain cannot be verified."""


@dataclass(frozen=True)
class BuildInfo:
    toolchain_version: str
    source_hash: str
    artifact_hash: str


class EspIdfBuilder:
    """Runs ``idf.py`` inside the exported environment of a pinned ESP-IDF."""

    def __init__(self, idf_path: Path | None = None) -> None:
        env_path = os.environ.get("IDF_PATH")
        self._idf_path = idf_path or (Path(env_path) if env_path else None)
        if self._idf_path is None:
            raise ToolchainUnavailableError("IDF_PATH not set")
        self._export = self._idf_path / "export.sh"
        if not self._export.is_file():
            raise ToolchainUnavailableError(f"ESP-IDF export script missing: {self._export}")
        self._version = self._probe_version()

    def _idf_command(self, args: list[str]) -> list[str]:
        """Wrap idf.py so it runs with the ESP-IDF environment exported.

        The toolchain paths only exist after sourcing export.sh, and the
        calling interpreter (e.g. a uv venv) must not leak into the build.
        """
        quoted = " ".join(shlex.quote(arg) for arg in args)
        return [
            "bash",
            "-c",
            f". {shlex.quote(str(self._export))} >/dev/null && exec idf.py {quoted}",
        ]

    def _probe_version(self) -> str:
        result = subprocess.run(
            self._idf_command(["--version"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        match = re.search(r"v[0-9]+\.[0-9]+(\.[0-9]+)?", result.stdout + result.stderr)
        if result.returncode != 0 or match is None:
            raise ToolchainUnavailableError(
                f"idf.py --version failed or unparsable: {result.stdout!r} {result.stderr!r}"
            )
        return match.group(0)

    def version(self) -> str:
        return self._version

    def _source_paths(self, project: FirmwareProject) -> list[Path]:
        return [
            project.root / "CMakeLists.txt",
            project.root / "sdkconfig.defaults",
            project.root / "main" / "CMakeLists.txt",
            project.pins_header,
            project.main_source,
        ]

    def build(self, project: FirmwareProject) -> Path:
        """Build the firmware and return the application binary path."""
        binary = project.root / "build" / "acd_gd1_fw.bin"
        run_command(
            self._idf_command(["-C", str(project.root), "build"]),
            tool_version=self._version,
            input_paths=self._source_paths(project),
            output_paths=[binary],
            cwd=project.root,
        )
        return binary

    def merge_bin(self, project: FirmwareProject) -> Path:
        """Merge bootloader/partition-table/app into a single flash image."""
        app_binary = project.root / "build" / "acd_gd1_fw.bin"
        merged = project.root / "build" / "merged-binary.bin"
        run_command(
            self._idf_command(["-C", str(project.root), "merge-bin"]),
            tool_version=self._version,
            input_paths=[app_binary],
            output_paths=[merged],
            cwd=project.root,
        )
        return merged

    def source_hash(self, project: FirmwareProject) -> str:
        return sha256_paths(self._source_paths(project))

    def build_info(self, project: FirmwareProject, binary: Path) -> BuildInfo:
        return BuildInfo(
            toolchain_version=f"esp-idf {self._version}",
            source_hash=self.source_hash(project),
            artifact_hash=sha256_paths([binary]),
        )
