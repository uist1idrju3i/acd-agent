"""External tool capability probes.

Each probe detects presence and version of one external tool. Absence or an
unparsable version is recorded as ``unknown`` — never as a success — so the
result can gate session start and evidence validity (fail-closed).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from acd_schema import AcdModel
from acd_schema.common import NonEmptyStr


class CadFormatProbe(AcdModel):
    """Measured determinism and normalization result for one CAD format."""

    format: NonEmptyStr
    raw_equal: bool
    normalized_equal: bool
    raw_hashes: list[NonEmptyStr]
    normalized_hashes: list[NonEmptyStr]
    differences: list[str] = Field(default_factory=list)
    normalization_rule: NonEmptyStr


def _empty_cad_formats() -> list[CadFormatProbe]:
    return []


class ToolProbeResult(AcdModel):
    """Structured result of probing one external tool."""

    tool_name: NonEmptyStr
    present: bool
    version: NonEmptyStr  # concrete version or "unknown"
    path: str | None = None
    detail: str = ""
    cad_formats: list[CadFormatProbe] = Field(default_factory=_empty_cad_formats)

    @property
    def is_known(self) -> bool:
        return self.present and self.version != "unknown"


def _run_version_command(
    executable: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unknown", f"version command failed: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    match = re.search(version_pattern, output)
    exit_ok = completed.returncode == 0 or allow_nonzero_exit
    if not exit_ok or match is None:
        return "unknown", f"unparsable version output (exit={completed.returncode})"
    return match.group(1), f"version detected (exit={completed.returncode})"


def probe_executable(
    tool_name: str,
    executable: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> ToolProbeResult:
    path = shutil.which(executable)
    if path is None:
        return ToolProbeResult(
            tool_name=tool_name,
            present=False,
            version="unknown",
            path=None,
            detail="executable not found on PATH",
        )
    version, detail = _run_version_command(
        path, args, version_pattern, allow_nonzero_exit=allow_nonzero_exit
    )
    return ToolProbeResult(
        tool_name=tool_name, present=True, version=version, path=path, detail=detail
    )


def probe_kicad_cli() -> ToolProbeResult:
    return probe_executable("kicad-cli", "kicad-cli", ["version"], r"([0-9]+\.[0-9]+\.[0-9]+)")


def probe_freerouting() -> ToolProbeResult:
    # freerouting v2 prints its version banner but exits nonzero when invoked
    # without an input/output pair, so a nonzero exit is tolerated here as long
    # as the banner is parsable.
    return probe_executable(
        "freerouting",
        "freerouting",
        ["--version"],
        r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)",
        allow_nonzero_exit=True,
    )


def probe_cad_kernel() -> ToolProbeResult:
    """Probe the Python CAD kernel (build123d on OCP) without requiring it."""
    versions: dict[str, str] = {}
    for dist_name in ("build123d", "cadquery-ocp"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            versions[dist_name] = importlib.metadata.version(dist_name)
    if not versions:
        return ToolProbeResult(
            tool_name="cad-kernel",
            present=False,
            version="unknown",
            path=None,
            detail="no CAD kernel distribution installed (build123d / cadquery-ocp)",
        )
    try:
        formats = _probe_cad_exports()
    except Exception as exc:
        return ToolProbeResult(
            tool_name="cad-kernel",
            present=True,
            version=versions.get("build123d", versions.get("cadquery-ocp", "unknown")),
            path=None,
            detail=f"CAD export probe failed: {type(exc).__name__}: {exc}",
        )
    return ToolProbeResult(
        tool_name="cad-kernel",
        present=True,
        version=versions.get("build123d", versions["cadquery-ocp"]),
        path=None,
        detail="python distributions " + ", ".join(f"{k}={v}" for k, v in versions.items()),
        cad_formats=formats,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_step(data: bytes) -> bytes:
    text = data.decode("utf-8")
    text = re.sub(
        r"(FILE_NAME\('Open CASCADE Shape Model',')[^']+(')",
        r"\g<1>1970-01-01T00:00:00\g<2>",
        text,
    )
    return text.encode("utf-8")


def normalize_3mf(data: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "3D/3dmodel.model":
                content = re.sub(
                    rb' p:UUID="[0-9a-fA-F-]+"',
                    b' p:UUID="00000000-0000-0000-0000-000000000000"',
                    content,
                )
            info = zipfile.ZipInfo(entry.filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = entry.external_attr
            target.writestr(info, content)
    return output.getvalue()


def _export_3mf(shape: Any, path: Path) -> None:
    import ctypes
    import importlib

    lib3mf: Any = importlib.import_module("lib3mf")

    vertices, triangles = shape.tessellate(0.01)
    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    mesh = model.AddMeshObject()

    def position(vertex: Any) -> Any:
        coordinates = (ctypes.c_float * 3)(vertex.X, vertex.Y, vertex.Z)
        return lib3mf.Position(coordinates)

    def triangle(indices: tuple[int, int, int]) -> Any:
        return lib3mf.Triangle((ctypes.c_uint32 * 3)(*indices))

    mesh.SetGeometry([position(vertex) for vertex in vertices], [triangle(t) for t in triangles])
    mesh.SetName("box")
    model.AddBuildItem(mesh, wrapper.GetIdentityTransform())
    model.QueryWriter("3mf").WriteToFile(str(path))


def _probe_cad_exports() -> list[CadFormatProbe]:
    import importlib

    build123d: Any = importlib.import_module("build123d")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shape = build123d.Box(10, 10, 10)
        build123d.export_step(shape, root / "first.step")
        time.sleep(1.1)
        build123d.export_step(shape, root / "second.step")
        step_a = (root / "first.step").read_bytes()
        step_b = (root / "second.step").read_bytes()
        _export_3mf(shape, root / "first.3mf")
        _export_3mf(shape, root / "second.3mf")
        mf_a = (root / "first.3mf").read_bytes()
        mf_b = (root / "second.3mf").read_bytes()

    normalized_step_a = normalize_step(step_a)
    normalized_step_b = normalize_step(step_b)
    normalized_mf_a = normalize_3mf(mf_a)
    normalized_mf_b = normalize_3mf(mf_b)
    return [
        CadFormatProbe(
            format="STEP",
            raw_equal=step_a == step_b,
            normalized_equal=normalized_step_a == normalized_step_b,
            raw_hashes=[_sha256(step_a), _sha256(step_b)],
            normalized_hashes=[_sha256(normalized_step_a), _sha256(normalized_step_b)],
            differences=["FILE_NAME timestamp"] if step_a != step_b else [],
            normalization_rule="Replace FILE_NAME timestamp with 1970-01-01T00:00:00.",
        ),
        CadFormatProbe(
            format="3MF",
            raw_equal=mf_a == mf_b,
            normalized_equal=normalized_mf_a == normalized_mf_b,
            raw_hashes=[_sha256(mf_a), _sha256(mf_b)],
            normalized_hashes=[_sha256(normalized_mf_a), _sha256(normalized_mf_b)],
            differences=["3D/3dmodel.model p:UUID attributes"] if mf_a != mf_b else [],
            normalization_rule=(
                "Replace all 3D/3dmodel.model p:UUID values and canonicalize ZIP entry timestamps."
            ),
        ),
    ]


PROBES: dict[str, Callable[[], ToolProbeResult]] = {
    "kicad-cli": probe_kicad_cli,
    "freerouting": probe_freerouting,
    "cad-kernel": probe_cad_kernel,
}


class ProbeReport(AcdModel):
    results: list[ToolProbeResult] = Field(default_factory=list[ToolProbeResult])

    def versions(self) -> dict[str, str]:
        """Tool-name to version map for SessionStart validation."""
        return {result.tool_name: result.version for result in self.results}


def probe_all() -> ProbeReport:
    return ProbeReport(results=[probe() for probe in PROBES.values()])
