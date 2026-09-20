"""Deterministic CalculiX input generation and estimate evaluation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from acd.core.runtime.process import ExternalToolError, run_tool
from acd.schema import (
    DesignGraph,
    FemRequest,
    FemResult,
    FemStatus,
    canonical_sha256,
)

CCX_FORMAT_VERSION = "1"
_VERSION_RE = re.compile(r"(?:CalculiX|ccx)[^\d]*([0-9]+\.[0-9]+)", re.IGNORECASE)
_NUMBER_RE = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


class FemAnalysisError(ValueError):
    """Raised when FEM identity or generated geometry input is invalid."""


@dataclass(frozen=True)
class FemRawResult:
    status: FemStatus
    ccx_version: str | None
    dat_text: str
    findings: tuple[str, ...] = ()


def _check_identity(graph: DesignGraph, request: FemRequest) -> None:
    if request.graph_id != graph.graph_id or request.revision != graph.revision:
        raise FemAnalysisError("graph/request graph_id or revision mismatch")


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise FemAnalysisError("FEM geometry values must be finite")
    return f"{value:.9g}"


def generate_ccx_input(
    request: FemRequest,
    enclosure_dims: tuple[float, float, float, float],
) -> str:
    """Generate a fixed-node-numbering hexahedral enclosure approximation.

    ``enclosure_dims`` is ``(width_mm, depth_mm, height_mm, wall_mm)``.
    A drop is represented by equivalent static acceleration
    ``a = v² / (2 * crush_distance)``; this is deliberately not a transient
    impact model.
    """
    width, depth, height, wall = enclosure_dims
    if min(width, depth, height, wall) <= 0:
        raise FemAnalysisError("enclosure dimensions must be positive")
    nodes = (
        (1, 0.0, 0.0, 0.0),
        (2, width, 0.0, 0.0),
        (3, width, depth, 0.0),
        (4, 0.0, depth, 0.0),
        (5, 0.0, 0.0, height),
        (6, width, 0.0, height),
        (7, width, depth, height),
        (8, 0.0, depth, height),
    )
    lines = [
        "*HEADING",
        "ACD deterministic generated enclosure approximation",
        f"** wall_thickness_mm={_fmt(wall)}",
        f"** element_size_mm={_fmt(request.mesh.element_size_mm)}",
        "*NODE",
    ]
    lines.extend(f"{index}, {_fmt(x)}, {_fmt(y)}, {_fmt(z)}" for index, x, y, z in nodes)
    lines.extend(
        [
            "*ELEMENT, TYPE=C3D8R, ELSET=BOX",
            "1, 1, 2, 3, 4, 5, 6, 7, 8",
            "*NSET, NSET=FIXED",
            "1, 2, 3, 4",
            "*ELSET, ELSET=BOX",
            "1",
            "*MATERIAL, NAME=DECLARED",
            "*ELASTIC",
            f"{_fmt(request.material.e_pa)}, {_fmt(request.material.nu)}",
            "*DENSITY",
            _fmt(request.material.rho_kg_m3),
        ]
    )
    if request.material.k_w_per_mk is not None:
        lines.extend(["*CONDUCTIVITY", _fmt(request.material.k_w_per_mk)])
    lines.extend(["*SOLID SECTION, ELSET=BOX, MATERIAL=DECLARED", ""])
    if request.analysis == "thermal":
        assert request.loads.thermal is not None
        lines.extend(
            [
                "*STEP",
                "*HEAT TRANSFER",
                "1., 1.",
                "*BOUNDARY",
                "FIXED, 11, 11, " + _fmt(request.loads.thermal.ambient_c),
                "*CFLUX",
                f"1, {_fmt(request.loads.thermal.heat_w)}",
                "*NODE PRINT, NSET=FIXED",
                "NT",
                "*END STEP",
            ]
        )
    else:
        force_n = request.loads.static.force_n if request.loads.static else None
        if request.loads.drop is not None:
            velocity = math.sqrt(2.0 * 9.80665 * request.loads.drop.height_m)
            crush_m = request.loads.drop.crush_distance_mm / 1000.0
            acceleration = velocity * velocity / (2.0 * crush_m)
            force_n = request.loads.drop.mass_kg * acceleration
            lines.append(f"** equivalent_drop_acceleration_m_s2={_fmt(acceleration)}")
        assert force_n is not None
        lines.extend(
            [
                "*STEP",
                "*STATIC",
                "1., 1.",
                "*BOUNDARY",
                "FIXED, 1, 3",
                "*CLOAD",
                f"7, 3, {_fmt(force_n)}",
                "*NODE PRINT, NSET=FIXED",
                "U",
                "*EL PRINT, ELSET=BOX",
                "S",
                "*END STEP",
            ]
        )
    return "\n".join(lines) + "\n"


def _version(text: str) -> str | None:
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def run_ccx(inp: Path, workdir: Path, *, version_pin: str = "2.21") -> FemRawResult:
    """Run CalculiX only through the process adapter and read its ``.dat`` file."""
    workdir.mkdir(parents=True, exist_ok=True)
    envelope = workdir / "ccx-version-envelope.json"
    try:
        version_run = run_tool(
            tool_name="ccx",
            tool_version=version_pin,
            format_version=CCX_FORMAT_VERSION,
            command=["ccx", "-v"],
            input_paths=[],
            output_paths=[],
            envelope_path=envelope,
            target_revision="r0",
            measurement_conditions="version probe",
        )
    except (ExternalToolError, OSError) as exc:
        return FemRawResult("unknown", None, "", (f"ccx tool unavailable: {exc}",))
    version = _version(version_run.stdout + version_run.stderr)
    if version is None:
        return FemRawResult("unknown", None, "", ("ccx version output is malformed",))
    if version != version_pin:
        return FemRawResult("unknown", version, "", ("tool_version_mismatch",))
    jobname = inp.stem
    dat_path = workdir / f"{jobname}.dat"
    try:
        run_tool(
            tool_name="ccx",
            tool_version=version,
            format_version=CCX_FORMAT_VERSION,
            command=["ccx", jobname],
            input_paths=[inp],
            output_paths=[dat_path],
            envelope_path=workdir / "ccx-envelope.json",
            target_revision="r0",
            measurement_conditions="deterministic generated enclosure model",
            cwd=workdir,
        )
    except (ExternalToolError, OSError) as exc:
        return FemRawResult("unknown", version, "", (f"ccx execution failed: {exc}",))
    return FemRawResult("pass", version, dat_path.read_text(encoding="utf-8"), ())


def _parse_dat(text: str) -> tuple[float | None, float | None, float | None]:
    max_deflection = 0.0
    max_stress = 0.0
    max_temp: float | None = None
    displacement_seen = False
    stress_seen = False
    section: str | None = None
    for line in text.splitlines():
        upper = line.upper()
        numbers = [float(value) for value in re.findall(_NUMBER_RE, line)]
        if "DISPLACEMENTS" in upper or "DISPLACEMENT" in upper:
            section = "u"
            continue
        if "STRESSES" in upper or "STRESS" in upper:
            section = "s"
            continue
        if upper.strip() in {"U", "NT"}:
            section = "u" if upper.strip() == "U" else "t"
            continue
        if upper.strip() == "S":
            section = "s"
            continue
        if " U " in f" {upper} " or upper.lstrip().startswith(("U1", "U2", "U3")):
            values = numbers[1:] if numbers and numbers[0].is_integer() else numbers
            if len(values) >= 3:
                max_deflection = max(max_deflection, math.sqrt(sum(v * v for v in values[:3])))
                displacement_seen = True
        elif section == "u" and len(numbers) >= 4:
            max_deflection = max(
                max_deflection,
                math.sqrt(sum(v * v for v in numbers[-3:])),
            )
            displacement_seen = True
        if " S " in f" {upper} " or upper.lstrip().startswith("S"):
            values = numbers[1:] if numbers and numbers[0].is_integer() else numbers
            if len(values) >= 6:
                s11, s22, s33, s12, s13, s23 = values[:6]
                von_mises = math.sqrt(
                    0.5
                    * (
                        (s11 - s22) ** 2
                        + (s22 - s33) ** 2
                        + (s33 - s11) ** 2
                        + 6.0 * (s12**2 + s13**2 + s23**2)
                    )
                )
                max_stress = max(max_stress, von_mises)
                stress_seen = True
        elif section == "s" and len(numbers) >= 7:
            values = numbers[-6:]
            s11, s22, s33, s12, s13, s23 = values
            von_mises = math.sqrt(
                0.5
                * (
                    (s11 - s22) ** 2
                    + (s22 - s33) ** 2
                    + (s33 - s11) ** 2
                    + 6.0 * (s12**2 + s13**2 + s23**2)
                )
            )
            max_stress = max(max_stress, von_mises)
            stress_seen = True
        if " NT " in f" {upper} " or upper.lstrip().startswith("NT"):
            values = numbers[1:] if numbers and numbers[0].is_integer() else numbers
            if values:
                max_temp = max(max_temp or values[0], max(values))
        elif section == "t" and numbers:
            max_temp = max(max_temp or numbers[-1], max(numbers))
    return (
        max_deflection if displacement_seen else None,
        max_stress if stress_seen else None,
        max_temp,
    )


def evaluate_fem(
    graph: DesignGraph,
    request: FemRequest,
    raw: FemRawResult,
) -> FemResult:
    _check_identity(graph, request)
    findings = list(raw.findings)
    deflection, stress, temperature = (
        _parse_dat(raw.dat_text) if raw.dat_text else (None, None, None)
    )
    if raw.status != "pass":
        status: FemStatus = "unknown"
    elif (
        not raw.dat_text
        or (request.analysis == "thermal" and temperature is None)
        or (request.analysis != "thermal" and stress is None and deflection is None)
    ):
        findings.append("CalculiX output parse failed")
        status = "unknown"
    else:
        violations = (
            request.limits.max_von_mises_pa is not None
            and stress is not None
            and stress > request.limits.max_von_mises_pa,
            request.limits.max_deflection_mm is not None
            and deflection is not None
            and deflection > request.limits.max_deflection_mm,
            request.limits.max_temp_c is not None
            and temperature is not None
            and temperature > request.limits.max_temp_c,
        )
        status = "fail" if any(violations) else "pass"
        if status == "fail":
            findings.append("FEM limit exceeded")
    return FemResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        analysis=request.analysis,
        status=status,
        max_von_mises_pa=stress,
        max_deflection_mm=deflection,
        max_temp_c=temperature,
        input_hashes={
            "graph": canonical_sha256(graph),
            "request": canonical_sha256(request),
        },
        tool_versions={"ccx": raw.ccx_version or "unknown"},
        findings=findings,
    )


def fem_markdown(result: FemResult) -> str:
    lines = [
        "# CalculiX FEM推定",
        "",
        "見積（estimate）・発注権限なし。落下・応力・熱の簡易経路です。",
        "",
        f"- status: `{result.status}`",
        f"- analysis: `{result.analysis}`",
        f"- authority: `{result.authority}`",
        f"- ccx: `{result.tool_versions['ccx']}`",
        f"- max von Mises (Pa): `{result.max_von_mises_pa}`",
        f"- max deflection (mm): `{result.max_deflection_mm}`",
        f"- max temperature (C): `{result.max_temp_c}`",
    ]
    if result.findings:
        lines.extend(["", "## Findings", ""])
        lines.extend(f"- {finding}" for finding in result.findings)
    return "\n".join(lines) + "\n"


__all__ = [
    "FemAnalysisError",
    "FemRawResult",
    "evaluate_fem",
    "fem_markdown",
    "generate_ccx_input",
    "run_ccx",
]
