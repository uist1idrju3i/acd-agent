"""Analysis artifact (SPICE/PDN/WCA/thermal/FEM/firmware) loading and summaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from pydantic import BaseModel

from acd.schema.fem import FemResult
from acd.schema.firmware_analysis import FirmwareAnalysisResult
from acd.schema.pdn import PdnResult
from acd.schema.spice import SpiceResult
from acd.schema.thermal import ThermalResult
from acd.schema.wca import WcaResult
from product_doc_inputs.common import (
    DocumentGenerationError,
    DocumentInput,
    format_number,
    load_json_object,
    sha256_file,
)


@dataclass(frozen=True)
class AnalysisArtifact:
    """One validated analysis result or an explicit not-run placeholder."""

    kind: str
    artifact_kind: str
    path: Path | None
    content_hash: str
    result: object | None
    status: str

    def input(self) -> DocumentInput | None:
        if self.path is None:
            return None
        return DocumentInput(path=self.path, content_hash=self.content_hash)


@dataclass(frozen=True)
class AnalysisBundle:
    """All six supported analysis kinds, including missing placeholders."""

    artifacts: tuple[AnalysisArtifact, ...]

    def by_kind(self, kind: str) -> AnalysisArtifact:
        for artifact in self.artifacts:
            if artifact.kind == kind:
                return artifact
        raise KeyError(kind)

    def inputs(self) -> tuple[DocumentInput, ...]:
        return tuple(item for artifact in self.artifacts if (item := artifact.input()) is not None)


_ANALYSIS_SPECS: tuple[tuple[str, str, type[BaseModel]], ...] = (
    ("spice", "spice_result", SpiceResult),
    ("pdn", "pdn_result", PdnResult),
    ("wca", "wca_result", WcaResult),
    ("thermal", "thermal_result", ThermalResult),
    ("fem", "fem_result", FemResult),
    ("firmware", "firmware_analysis_result", FirmwareAnalysisResult),
)


ANALYSIS_STATUS_TEMPLATE_KEYS = MappingProxyType(
    {
        "pass": "quality.analysis_status_pass",
        "findings": "quality.analysis_status_findings",
        "not_run": "quality.analysis_status_not_run",
    }
)


ANALYSIS_KIND_TEMPLATE_KEYS = MappingProxyType(
    {
        "spice": "quality.analysis_kind_spice",
        "pdn": "quality.analysis_kind_pdn",
        "wca": "quality.analysis_kind_wca",
        "thermal": "quality.analysis_kind_thermal",
        "fem": "quality.analysis_kind_fem",
        "firmware": "quality.analysis_kind_firmware",
    }
)


def load_analysis_results(
    dir_or_paths: Path | Sequence[Path],
    *,
    graph_id: str | None = None,
    revision: str | None = None,
) -> AnalysisBundle:
    """Load and validate supported analysis results without importing Skills."""
    paths = [dir_or_paths] if isinstance(dir_or_paths, Path) else list(dir_or_paths)
    candidates: list[Path] = []
    for path in paths:
        if path.is_dir():
            candidates.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            candidates.append(path)
    by_artifact: dict[str, AnalysisArtifact] = {}
    kind_by_artifact = {artifact_kind: kind for kind, artifact_kind, _ in _ANALYSIS_SPECS}
    model_by_artifact = {artifact_kind: model for _, artifact_kind, model in _ANALYSIS_SPECS}
    for path in sorted(set(candidates)):
        payload = load_json_object(path, label="analysis result")
        artifact_kind = payload.get("artifact_kind")
        if not isinstance(artifact_kind, str) or artifact_kind not in kind_by_artifact:
            continue
        model_type = model_by_artifact[artifact_kind]
        try:
            result = model_type.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DocumentGenerationError(f"analysis result {path} is not valid: {exc}") from exc
        result_graph_id = getattr(result, "graph_id", None)
        result_revision = getattr(result, "revision", None)
        if (
            graph_id is not None
            and revision is not None
            and (result_graph_id != graph_id or result_revision != revision)
        ):
            raise DocumentGenerationError(
                f"analysis result {path} targets graph/revision "
                f"{result_graph_id!r}/{result_revision!r}, not "
                f"{graph_id!r}/{revision!r}"
            )
        kind = kind_by_artifact[artifact_kind]
        if artifact_kind in by_artifact:
            raise DocumentGenerationError(f"duplicate {kind} analysis result: {path}")
        by_artifact[artifact_kind] = AnalysisArtifact(
            kind=kind,
            artifact_kind=artifact_kind,
            path=path,
            content_hash=sha256_file(path),
            result=result,
            status=str(payload.get("status", "unknown")),
        )
    artifacts = tuple(
        by_artifact.get(
            artifact_kind,
            AnalysisArtifact(
                kind=kind,
                artifact_kind=artifact_kind,
                path=None,
                content_hash="unknown",
                result=None,
                status="not_run",
            ),
        )
        for kind, artifact_kind, _ in _ANALYSIS_SPECS
    )
    return AnalysisBundle(artifacts=artifacts)


def analysis_summary(artifact: AnalysisArtifact) -> dict[str, object]:
    """Return deterministic display fields for one analysis artifact."""
    if artifact.result is None:
        return {
            "kind": artifact.kind,
            "artifact_kind": artifact.artifact_kind,
            "status": "not_run",
            "authority": "unknown",
            "measured": "unknown",
            "tool_versions": "unknown",
            "input_hashes": "unknown",
            "findings": "unknown",
        }
    result = cast(BaseModel, artifact.result)
    data = result.model_dump(mode="json")
    measured: list[str] = []
    tool_versions: list[str] = []
    input_hashes: list[str] = []
    findings: list[str] = []
    kind = artifact.kind
    if kind == "spice":
        for item in data.get("checks", []):
            measured_value = item.get("measured")
            if measured_value is not None:
                measured.append(f"{item.get('target')}={format_number(float(measured_value))}")
        version = data.get("ngspice_version")
        if version is not None:
            tool_versions.append(f"ngspice={version}")
    elif kind == "pdn":
        paths = data.get("paths", [])
        ir_values = [
            float(item["ir_drop_mv"]) for item in paths if item.get("ir_drop_mv") is not None
        ]
        density_values = [
            float(item["worst_current_density"])
            for item in paths
            if item.get("worst_current_density") is not None
        ]
        if ir_values:
            measured.append(f"worst_ir_drop_mv={format_number(max(ir_values))}")
        if density_values:
            measured.append(f"worst_current_density={format_number(max(density_values))}")
        tool_versions.extend(
            f"{key}={value}" for key, value in sorted(data.get("tool_versions", {}).items())
        )
    elif kind == "wca":
        for item in data.get("quantities", []):
            measured.append(
                f"{item.get('quantity_id')}=[{item.get('worst_low')},{item.get('worst_high')}]"
            )
    elif kind == "thermal":
        for item in data.get("sources", []):
            if item.get("tj_c") is not None:
                measured.append(f"{item.get('refdes')}.tj_c={item.get('tj_c')}")
    elif kind == "fem":
        for field in ("max_von_mises_pa", "max_deflection_mm", "max_temp_c"):
            if data.get(field) is not None:
                measured.append(f"{field}={data[field]}")
        tool_versions.extend(
            f"{key}={value}" for key, value in sorted(data.get("tool_versions", {}).items())
        )
    elif kind == "firmware":
        static = data.get("static_analysis")
        static_data: dict[str, Any] = {}
        if isinstance(static, dict):
            static_data = cast(dict[str, Any], static)
            counts = cast(dict[str, Any], static_data.get("counts", {}))
            measured.append(
                f"static_findings={int(counts.get('warning', 0)) + int(counts.get('error', 0))}"
            )
        stack = data.get("stack_usage")
        if isinstance(stack, dict):
            stack_data = cast(dict[str, Any], stack)
            tasks = cast(list[dict[str, Any]], stack_data.get("tasks", []))
            margins = [
                float(task.get("budget_bytes", 0)) - float(task.get("worst_static_bytes", 0))
                for task in tasks
            ]
            if margins:
                measured.append(f"stack_margin_bytes={format_number(min(margins))}")
        peripheral = data.get("peripheral_sim")
        if isinstance(peripheral, dict):
            peripheral_data = cast(dict[str, Any], peripheral)
            measured.append(f"sim={peripheral_data.get('status', 'unknown')}")
        if isinstance(static, dict) and static_data.get("tool_version") is not None:
            tool_versions.append(f"clang-tidy={static_data['tool_version']}")
        tool_versions.extend(
            f"{key}={value}" for key, value in sorted(data.get("tool_versions", {}).items())
        )
    raw_findings = cast(list[Any], data.get("findings", []))
    findings.extend(str(item) for item in raw_findings)
    if not measured:
        measured.append("unknown")
    raw_tools = cast(dict[str, Any] | None, data.get("tool_versions"))
    if not tool_versions and isinstance(raw_tools, dict):
        tool_versions.extend(f"{key}={value}" for key, value in sorted(raw_tools.items()))
    raw_hashes = cast(dict[str, Any] | None, data.get("input_hashes"))
    if isinstance(raw_hashes, dict):
        input_hashes.extend(f"{key}={value}" for key, value in sorted(raw_hashes.items()))
    return {
        "kind": artifact.kind,
        "artifact_kind": artifact.artifact_kind,
        "status": data.get("status", "unknown"),
        "authority": data.get("authority", "unknown"),
        "measured": "; ".join(measured),
        "tool_versions": "; ".join(tool_versions) or "unknown",
        "input_hashes": "; ".join(input_hashes) or "unknown",
        "findings": "; ".join(findings) or "none",
    }
