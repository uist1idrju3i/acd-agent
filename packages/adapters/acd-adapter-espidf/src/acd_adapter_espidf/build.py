"""ESP-IDF build wrapper producing an enveloped, hashed FwPackage."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from acd_adapter_espidf.project import FirmwareProject
from acd_core.firmware import FirmwareLane
from acd_core.process import run_tool, sha256_paths
from acd_schema.fw_package import BuildInfo, FwPackage, PinAssignment


class ToolchainUnavailableError(RuntimeError):
    """Raised when the ESP-IDF toolchain cannot be verified (fail-closed)."""


def _function_for_net(net_id: str) -> str:
    return net_id.removeprefix("net.")


def fw_package_from_lane(
    lane: FirmwareLane, *, package_id: str, target_revision: str, build: BuildInfo
) -> FwPackage:
    assignments = [
        PinAssignment(
            pin=f"IO{pin.gpio}", net=pin.net_id, function=_function_for_net(pin.net_id)
        )
        for pin in lane.pins
    ]
    return FwPackage(
        package_id=package_id,
        target_revision=target_revision,
        modules=[pin.node_id for pin in lane.pins],
        pin_assignments=assignments,
        build=build,
    )


class EspIdfBuilder:
    """Runs ``idf.py`` with a pinned, probed ESP-IDF version."""

    def __init__(self, idf_path: Path | None = None) -> None:
        env_path = os.environ.get("IDF_PATH")
        self._idf_path = idf_path or (Path(env_path) if env_path else None)
        if self._idf_path is None or not (self._idf_path / "tools" / "idf.py").is_file():
            raise ToolchainUnavailableError("IDF_PATH not set or idf.py missing (fail-closed)")
        idf_python_env = os.environ.get("IDF_PYTHON_ENV_PATH")
        if idf_python_env is None:
            raise ToolchainUnavailableError("IDF_PYTHON_ENV_PATH not set (fail-closed)")
        idf_python = Path(idf_python_env) / "bin" / "python"
        if not idf_python.is_file():
            raise ToolchainUnavailableError(f"IDF python missing: {idf_python} (fail-closed)")
        # Invoke idf.py through the pinned IDF python env so the calling
        # interpreter (e.g. a uv venv) does not leak into the build.
        self._idf_py = [str(idf_python), str(self._idf_path / "tools" / "idf.py")]
        self._version = self._probe_version()

    def _probe_version(self) -> str:
        result = subprocess.run(
            [*self._idf_py, "--version"], capture_output=True, text=True, check=False, timeout=120
        )
        match = re.search(r"v[0-9]+\.[0-9]+(\.[0-9]+)?", result.stdout + result.stderr)
        if result.returncode != 0 or match is None:
            raise ToolchainUnavailableError(
                f"idf.py --version failed or unparsable: {result.stdout!r} {result.stderr!r}"
            )
        return match.group(0)

    def version(self) -> str:
        return self._version

    def build(self, project: FirmwareProject, envelope_path: Path, target_revision: str) -> Path:
        """Build the firmware and return the application binary path."""
        binary = project.root / "build" / "acd_gd1_fw.bin"
        inputs = [
            project.root / "CMakeLists.txt",
            project.root / "sdkconfig.defaults",
            project.root / "main" / "CMakeLists.txt",
            project.pins_header,
            project.main_source,
        ]
        run_tool(
            tool_name="idf.py",
            tool_version=self._version,
            format_version="esp-idf-build",
            command=[*self._idf_py, "-C", str(project.root), "build"],
            input_paths=inputs,
            output_paths=[binary],
            envelope_path=envelope_path,
            target_revision=target_revision,
            measurement_conditions="target=esp32c3; deterministic sources; host build",
            cwd=project.root,
        )
        return binary

    def merge_bin(
        self, project: FirmwareProject, envelope_path: Path, target_revision: str
    ) -> Path:
        """Merge bootloader/partition-table/app into a single flash image."""
        app_binary = project.root / "build" / "acd_gd1_fw.bin"
        merged = project.root / "build" / "merged-binary.bin"
        run_tool(
            tool_name="idf.py",
            tool_version=self._version,
            format_version="esp-idf-merge-bin",
            command=[*self._idf_py, "-C", str(project.root), "merge-bin"],
            input_paths=[app_binary],
            output_paths=[merged],
            envelope_path=envelope_path,
            target_revision=target_revision,
            measurement_conditions="target=esp32c3; merged flash image",
            cwd=project.root,
        )
        return merged

    def source_hash(self, project: FirmwareProject) -> str:
        return sha256_paths(
            [
                project.root / "CMakeLists.txt",
                project.root / "sdkconfig.defaults",
                project.root / "main" / "CMakeLists.txt",
                project.pins_header,
                project.main_source,
            ]
        )
