"""Shared observation model and path/resource helpers for ACD ToolDefinitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from openhands.sdk.llm import TextContent
from openhands.sdk.tool import (
    DeclaredResources,
    Observation,
)

from acd.core.fileio import read_json
from acd.core.naming import artifact_prefix
from acd.schema.design_graph import DesignGraph

if TYPE_CHECKING:
    pass


def error_payload(message: str, *, operation: str) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "failure_reason": message,
        "fail_closed": True,
        "is_error": True,
    }


def collect_envelopes(out_dir: Path) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for path in sorted(out_dir.rglob("*.json")):
        try:
            value = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and {
            "tool_name",
            "tool_version",
            "input_hash",
            "output_hash",
        }.issubset(cast(dict[str, Any], value)):
            envelopes.append({"path": str(path), "envelope": value})
    return envelopes


def resolved_resource_path(raw_path: str) -> Path | None:
    try:
        return Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def declared_resources_for(*paths: tuple[str, Path]) -> DeclaredResources:
    resolved: list[str] = []
    for prefix, raw_path in paths:
        path = resolved_resource_path(str(raw_path))
        if path is None:
            return DeclaredResources(keys=(), declared=False)
        resolved.append(f"{prefix}:{path}")
    return DeclaredResources(keys=tuple(resolved), declared=True)


def fixture_output_path(fixture: str, suffix: str) -> Path:
    graph_path = Path(fixture) / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    return Path("out") / f"{artifact_prefix(graph.graph_id)}{suffix}"


def pipeline_output_path(
    fixture: str, explicit_out: str | None, suffix: str
) -> Path:
    if explicit_out is not None:
        return Path(explicit_out)
    return fixture_output_path(fixture, suffix)


class AcdObservation(Observation):
    """Common typed result fields for ACD deterministic tools."""

    ok: bool
    operation: str
    failure_reason: str | None = None
    fail_closed: bool
    summary: dict[str, Any] | None = None
    output_path: str | None = None
    envelopes: list[dict[str, Any]] | None = None
    results: list[dict[str, Any]] | None = None
    versions: dict[str, str] | None = None
    graph_id: str | None = None
    revision: str | None = None
    node_count: int | None = None
    path: str | None = None
    report: dict[str, Any] | None = None
    changed_node_ids: list[str] | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    provenance: dict[str, Any] | None = None
    pass_evidence: bool = False
    registry_id: str | None = None
    prior_registry_hash: str | None = None
    new_registry_hash: str | None = None
    contract_source: str | None = None
    contract: dict[str, Any] | None = None
    written: bool | None = None
    catalog_id: str | None = None
    prior_catalog_hash: str | None = None
    new_catalog_hash: str | None = None
    entry_source: str | None = None
    entry: dict[str, Any] | None = None
    evidence_path: str | None = None

    @property
    def to_llm_content(self) -> list[TextContent]:
        if self.fail_closed:
            reason = self.failure_reason or "an unknown failure occurred"
            text = f"{self.operation} failed closed: {reason}. This is not pass evidence."
        elif self.operation == "probe_tools":
            versions = self.versions or {}
            version_text = (
                ", ".join(f"{name}={versions[name]}" for name in sorted(versions)) or "none"
            )
            unknown = sorted(
                str(result.get("tool_name", "unknown"))
                for result in self.results or []
                if result.get("is_known") is False
            )
            unknown_text = f"; unknown={', '.join(unknown)}" if unknown else ""
            text = f"{self.operation}: versions={version_text}{unknown_text}."
        elif self.operation == "validate_design_graph":
            text = (
                f"{self.operation}: graph_id={self.graph_id}, "
                f"revision={self.revision}, node_count={self.node_count}."
            )
        elif self.operation in {"run_board_pipeline", "run_enclosure_pipeline"}:
            summary = self.summary or {}
            summary_keys = ", ".join(sorted(str(key) for key in summary)) or "none"
            text = (
                f"{self.operation}: output_path={self.output_path}, "
                f"envelopes={len(self.envelopes or [])}, "
                f"summary_keys={summary_keys}."
            )
        elif self.report is not None:
            text = f"{self.operation}: report_keys={', '.join(sorted(self.report))}."
        elif self.operation in {
            "register_functional_block",
            "register_firmware_capability",
        }:
            text = (
                f"{self.operation}: registry_id={self.registry_id}, "
                f"prior_registry_hash={self.prior_registry_hash}, "
                f"new_registry_hash={self.new_registry_hash}, "
                f"written={self.written}. This is a declaration, not gate evidence."
            )
        elif self.operation == "register_parts_catalog_entry":
            text = (
                f"{self.operation}: catalog_id={self.catalog_id}, "
                f"prior_catalog_hash={self.prior_catalog_hash}, "
                f"new_catalog_hash={self.new_catalog_hash}, "
                f"written={self.written}. This is a declaration, not gate evidence."
            )
        elif self.failure_reason:
            text = f"{self.operation}: {self.failure_reason}"
        else:
            text = f"{self.operation} completed successfully."
        return [TextContent(text=text)]
