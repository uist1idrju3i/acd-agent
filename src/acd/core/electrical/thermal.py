"""Deterministic simplified thermal resistance estimates."""

from __future__ import annotations

from acd.core.electrical.electrical import GraphExtractionError, extract_electrical_lane
from acd.core.mechanical.mechanical import MechanicalLane, extract_mechanical_lane
from acd.schema import (
    DesignGraph,
    ThermalRequest,
    ThermalResult,
    ThermalSourceResult,
    ThermalStatus,
    UseEnvironment,
    canonical_sha256,
)

NATURAL_CONVECTION_H_W_PER_M2K = 5.0
PAD_SPREADING_H_W_PER_M2K = 100.0


class ThermalAnalysisError(ValueError):
    """Raised when thermal input identity or graph extraction is invalid."""


def _check_identity(graph: DesignGraph, request: ThermalRequest) -> None:
    if request.graph_id != graph.graph_id or request.revision != graph.revision:
        raise ThermalAnalysisError("graph/request graph_id or revision mismatch")


def _ambient(
    request: ThermalRequest,
    environment: UseEnvironment | None,
) -> tuple[float | None, str | None]:
    if request.environment_ref is not None:
        if environment is None:
            return None, "declared environment is unavailable"
        if environment.graph_id != request.graph_id or environment.revision != request.revision:
            raise ThermalAnalysisError("graph/environment graph_id or revision mismatch")
        return environment.temperature_c.max, None
    return request.ambient_c, None


def _enclosure_area_m2(lane: MechanicalLane) -> float:
    width = lane.outline.width_mm + 2.0 * (
        lane.enclosure.internal_clearance_mm + lane.enclosure.wall_thickness_mm
    )
    depth = lane.outline.depth_mm + 2.0 * (
        lane.enclosure.internal_clearance_mm + lane.enclosure.wall_thickness_mm
    )
    height = (
        lane.outline.thickness_mm
        + lane.enclosure.internal_clearance_mm
        + 2.0 * (lane.enclosure.wall_thickness_mm)
    )
    return 2.0 * ((width * depth) + (width * height) + (depth * height)) / 1_000_000.0


def _thermal_result(
    graph: DesignGraph,
    request: ThermalRequest,
    environment: UseEnvironment | None,
) -> ThermalResult:
    try:
        electrical = extract_electrical_lane(graph)
        mechanical = extract_mechanical_lane(graph)
    except GraphExtractionError as exc:
        raise ThermalAnalysisError(str(exc)) from exc
    components = {component.refdes for component in electrical.components}
    ambient, ambient_finding = _ambient(request, environment)
    outer_area = _enclosure_area_m2(mechanical)
    wall_m = request.enclosure.wall_thickness_mm / 1000.0
    material_k = request.enclosure.material.k_w_per_mk
    theta_ba = 1.0 / (NATURAL_CONVECTION_H_W_PER_M2K * outer_area) + wall_m / (
        material_k * outer_area
    )
    results: list[ThermalSourceResult] = []
    for source in request.sources:
        findings: list[str] = []
        if source.refdes not in components:
            findings.append(f"source component {source.refdes} is missing from graph")
        if ambient_finding is not None:
            findings.append(ambient_finding)
        if source.power_w is None:
            findings.append("source power is undeclared")
        area_m2 = (
            source.pcb_copper_area_mm2 / 1_000_000.0
            if source.pcb_copper_area_mm2 is not None
            else None
        )
        theta_cb = 1.0 / (PAD_SPREADING_H_W_PER_M2K * area_m2) if area_m2 is not None else None
        paths: list[float] = []
        if source.package_theta_jc_c_per_w is not None and theta_cb is not None:
            paths.append(source.package_theta_jc_c_per_w + theta_cb + theta_ba)
        if source.package_theta_ja_c_per_w is not None:
            paths.append(source.package_theta_ja_c_per_w)
        if not paths:
            findings.append("thermal resistance path is incomplete")
        total = max(paths) if paths else None
        tj = (
            ambient + source.power_w * total
            if ambient is not None and source.power_w is not None and total is not None
            else None
        )
        status: ThermalStatus = "unknown"
        if not findings and tj is not None:
            status = "fail" if tj > source.tj_max_c else "pass"
            if status == "fail":
                findings.append(
                    f"junction temperature {tj:.6g} C exceeds limit {source.tj_max_c:.6g} C"
                )
        results.append(
            ThermalSourceResult(
                refdes=source.refdes,
                power_w=source.power_w,
                theta_jc_c_per_w=source.package_theta_jc_c_per_w,
                theta_ja_c_per_w=source.package_theta_ja_c_per_w,
                theta_cb_c_per_w=theta_cb,
                theta_ba_c_per_w=theta_ba if paths else None,
                theta_total_c_per_w=total,
                tj_c=tj,
                status=status,
                findings=findings,
            )
        )
    statuses = [result.status for result in results]
    status: ThermalStatus = (
        "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    )
    findings = [f"{result.refdes}: {finding}" for result in results for finding in result.findings]
    return ThermalResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        ambient_c=ambient,
        sources=results,
        input_hashes={
            "graph": canonical_sha256(graph),
            "request": canonical_sha256(request),
            "environment": canonical_sha256(environment) if environment else "unknown",
        },
        findings=findings,
    )


def estimate_thermal(
    graph: DesignGraph,
    request: ThermalRequest,
    environment: UseEnvironment | None = None,
) -> ThermalResult:
    """Estimate junction temperature using a conservative lumped model.

    The model uses declared package resistance, a fixed pad-spreading
    coefficient, and enclosure natural convection plus wall conduction. It is
    an estimate and not a replacement for measured thermal characterization.
    """
    _check_identity(graph, request)
    return _thermal_result(graph, request, environment)


def thermal_markdown(result: ThermalResult) -> str:
    lines = [
        "# 熱抵抗簡易推定",
        "",
        "見積（estimate）・発注権限なし。FEMや実測の代替ではありません。",
        "",
        f"- status: `{result.status}`",
        f"- authority: `{result.authority}`",
        f"- ambient_c: `{result.ambient_c}`",
        "",
        "| refdes | power (W) | theta total (C/W) | Tj (C) | status |",
        "|---|---:|---:|---:|---|",
    ]
    for source in result.sources:
        lines.append(
            f"| {source.refdes} | {source.power_w} | "
            f"{source.theta_total_c_per_w} | {source.tj_c} | {source.status} |"
        )
    if result.findings:
        lines.extend(["", "## Findings", ""])
        lines.extend(f"- {finding}" for finding in result.findings)
    return "\n".join(lines) + "\n"


__all__ = ["ThermalAnalysisError", "estimate_thermal", "thermal_markdown"]
