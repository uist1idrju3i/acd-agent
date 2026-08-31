"""OpenHands SDK ToolDefinitions for deterministic ACD entrypoints."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from openhands.sdk.llm import TextContent
from openhands.sdk.tool import (
    Action,
    DeclaredResources,
    Observation,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    list_registered_tools,
)
from openhands.sdk.tool.registry import register_tool  # pyright: ignore[reportUnknownVariableType]
from pydantic import Field

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.firmware_capability_entry import register_firmware_capability
from acd.core.functional_block_entry import register_functional_block_contract
from acd.core.naming import artifact_prefix
from acd.core.parts_catalog_entry import register_parts_catalog_entry
from acd.openhands.tools.probe import probe_all
from acd.schema.design_graph import DesignGraph

if TYPE_CHECKING:
    from openhands.sdk.conversation.state import ConversationState


def run_board(
    fixture_dir: Path,
    out_dir: Path,
    max_passes: int,
    fab_profile_path: Path | None = None,
    fab_profile_id: str | None = None,
) -> dict[str, str]:
    """Run the board pipeline without importing it during package initialization."""
    from acd.pipeline.gd1_board import run_pipeline

    return run_pipeline(
        fixture_dir,
        out_dir,
        max_passes,
        fab_profile_path,
        fab_profile_id=fab_profile_id,
    )


def run_enclosure(fixture_dir: Path, out_dir: Path) -> dict[str, object]:
    """Run the enclosure pipeline without importing it during package initialization."""
    from acd.pipeline.enclosure import run_pipeline

    return run_pipeline(fixture_dir, out_dir)


def _error(message: str, *, operation: str) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "failure_reason": message,
        "fail_closed": True,
        "is_error": True,
    }


def _envelopes(out_dir: Path) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for path in sorted(out_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
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


def _resolved_resource_path(raw_path: str) -> Path | None:
    try:
        return Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _file_sha256(path: Path) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _resources(*paths: tuple[str, Path]) -> DeclaredResources:
    resolved: list[str] = []
    for prefix, raw_path in paths:
        path = _resolved_resource_path(str(raw_path))
        if path is None:
            return DeclaredResources(keys=(), declared=False)
        resolved.append(f"{prefix}:{path}")
    return DeclaredResources(keys=tuple(resolved), declared=True)


def _fixture_output_path(fixture: str, suffix: str) -> Path:
    graph_path = Path(fixture) / "graph.json"
    graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    return Path("out") / f"{artifact_prefix(graph.graph_id)}{suffix}"


def _pipeline_output_path(
    fixture: str, explicit_out: str | None, suffix: str
) -> Path:
    if explicit_out is not None:
        return Path(explicit_out)
    return _fixture_output_path(fixture, suffix)


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


class AcdProbeToolsAction(Action):
    """Request external tool capability probes."""


class AcdValidateDesignGraphAction(Action):
    """Validate one canonical DesignGraph JSON file."""

    path: str = Field(description="Path to the canonical DesignGraph JSON file.")


class AcdRunBoardPipelineAction(Action):
    """Run the deterministic board pipeline."""

    fixture: str = Field(
        default="fixtures/golden-design-1",
        description="Fixture directory containing graph.json.",
    )
    out: str | None = Field(
        default=None,
        description="Output directory; derived from fixture graph when omitted.",
    )
    fab_profile: str | None = Field(default=None, description="Fabrication profile JSON path.")
    fab_profile_id: str | None = Field(
        default=None, description="Registered fabrication profile id."
    )
    max_passes: int = Field(
        default=DEFAULT_ROUTER_MAX_PASSES,
        description="Bounded router pass budget for the board lane.",
    )


class AcdRunEnclosurePipelineAction(Action):
    """Run the deterministic enclosure pipeline."""

    fixture: str = Field(
        default="fixtures/golden-design-1",
        description="Fixture directory containing graph.json.",
    )
    out: str | None = Field(
        default=None,
        description="Output directory; derived from fixture graph when omitted.",
    )


class AcdRegisterFunctionalBlockAction(Action):
    """Validate and append one functional-block contract declaration."""

    contract: str = Field(
        description="FunctionalBlockContract JSON path or inline JSON object."
    )
    registry: str = Field(
        default="contracts/functional-block-registry.json",
        description="Functional-block registry JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the registry.",
    )


class AcdRegisterFirmwareCapabilityAction(Action):
    """Validate and append one firmware capability declaration."""

    capability: str = Field(
        description="FirmwareCapabilityContract JSON path or inline JSON object."
    )
    registry: str = Field(
        default="contracts/firmware-capability-registry.json",
        description="Firmware capability registry JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the registry.",
    )


class AcdRegisterPartsCatalogEntryAction(Action):
    """Validate and append one parts-catalog entry declaration."""

    entry: str = Field(description="PartCatalogEntry JSON path or inline JSON object.")
    catalog: str = Field(
        default="contracts/parts-catalog.json",
        description="Parts catalog JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the catalog.",
    )


class AcdRunFirmwarePipelineAction(Action):
    fixture: str = Field(default="fixtures/golden-design-1")
    out: str | None = Field(
        default=None,
        description="Output directory; derived from fixture graph when omitted.",
    )
    run_seconds: int = Field(
        default=15,
        ge=1,
        description="Bounded virtual-run duration.",
    )


class AcdCompileRequirementChangeAction(Action):
    fixture_dir: str
    requirement: str
    dry_run: bool = False
    mode: Literal["update", "add", "delete"] = Field(
        default="update",
        description=(
            "Whether the declared record updates an existing requirement, adds "
            "a new one, or deletes one. Graph, requirements, and rationale are "
            "written in one transaction in every mode."
        ),
    )


class AcdBuildDesignFixtureAction(Action):
    spec: str
    out: str
    overwrite: bool = Field(
        default=False,
        description=(
            "Regenerate an existing fixture graph. The existing graph is "
            "preserved next to the overwrite report; implicit overwrite stays "
            "fail-closed."
        ),
    )


class AcdAggregateOrderTotalAction(Action):
    quote_records: list[str] = Field(min_length=1)
    order_scope: str
    fab_profile: str
    target_revision: str
    evaluated_at: str
    output: str


class AcdExploreBoardCandidatesAction(Action):
    graph: str
    fixture_dir: str
    out: str
    max_candidates: int = Field(ge=1)
    max_passes: int = Field(default=DEFAULT_ROUTER_MAX_PASSES, ge=1)
    dry_run: bool = False


class AcdExploreEnclosureCandidatesAction(Action):
    graph: str
    fixture_dir: str
    out: str
    max_candidates: int = Field(ge=1)
    dimensions: list[str] = Field(default_factory=list)
    jobs: int = Field(default=1, ge=1)
    sampling_points: int = Field(default=3, ge=2)


class AcdDiagnoseGateFailureAction(Action):
    out_dir: str
    fixture: str | None = Field(
        default=None,
        description=(
            "Fixture directory whose rationale coverage and lane preflight "
            "declarations are reported alongside the failed predicates."
        ),
    )
    lane_id: str | None = Field(
        default=None,
        description=(
            "Lane whose declared recovery dimensions and required declarations "
            "are reported. An undeclared lane is reported as unsupported."
        ),
    )


class AcdCheckOrderReadinessAction(Action):
    repository: str = "."
    policy: str = "plugins/acd/hooks/order-policy.json"
    design_graph_path: str = Field(
        description="Repository-relative path to the design graph being evaluated."
    )
    order_total: str
    evidence: list[str] = Field(default_factory=list)
    evaluated_at: str


class AcdRunDesignLoopAction(Action):
    """Run the fixed graph-driven VibeBB design loop."""

    fixture: str = Field(default="fixtures/golden-design-1")
    out_root: str = Field(default="out")
    order_total: str | None = None
    policy: str = "plugins/acd/hooks/order-policy.json"
    repository: str = "."
    fab_profile: str | None = None
    fab_profile_id: str | None = None
    max_passes: int = Field(default=DEFAULT_ROUTER_MAX_PASSES, ge=1)
    max_silkscreen_iterations: int = Field(default=5, ge=1)
    run_seconds: int = Field(default=15, ge=1)
    evaluated_at: str | None = None
    cache_dir: str | None = Field(
        default=None,
        description="Optional content-addressed cache directory for deterministic artifacts.",
    )
    resume: bool = Field(
        default=False,
        description="Reuse valid matching artifacts without restoring verdicts or Evidence.",
    )
    jobs: int = Field(
        default=1,
        ge=1,
        description="Maximum parallel board, enclosure, and firmware lanes.",
    )
    explore_board: bool = Field(
        default=False,
        description="Explore board candidates after a fail-closed board rejection.",
    )
    recover_lanes: bool = Field(
        default=False,
        description=(
            "Explore the declared recovery dimensions of any rejected lane. "
            "A lane without a declared recoverable dimension stays rejected."
        ),
    )
    fixture_overwrite: bool = Field(
        default=False,
        description=(
            "Regenerate the fixture even when it already holds a graph. "
            "The existing graph is preserved next to the overwrite report."
        ),
    )
    max_exploration_candidates: int = Field(
        default=3,
        ge=1,
        description="Maximum candidates evaluated in each board exploration round.",
    )
    max_exploration_rounds: int = Field(
        default=1,
        ge=1,
        description="Maximum board exploration and loop rerun rounds.",
    )
    requirement: str | None = Field(
        default=None,
        description="Optional updated requirement record to compile before the loop.",
    )
    fixture_spec: str | None = Field(
        default=None,
        description="Optional design fixture specification to generate before the loop.",
    )
    quote_records: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Optional quote records for order-total aggregation mode.",
    )
    order_scope: str | None = Field(
        default=None,
        description="Optional OrderScope JSON path for aggregation mode.",
    )


class AcdProbeToolsObservation(AcdObservation):
    """Observation returned by the external tool probe."""


class AcdValidateDesignGraphObservation(AcdObservation):
    """Observation returned by graph validation."""


class AcdRunBoardPipelineObservation(AcdObservation):
    """Observation returned by the board pipeline."""


class AcdRunEnclosurePipelineObservation(AcdObservation):
    """Observation returned by the enclosure pipeline."""


class AcdBootstrapWorkspaceAction(Action):
    """Prepare a clean workspace at an explicit repository revision."""

    repo_url: str = Field(description="Repository URL to clone or reuse.")
    revision: str = Field(description="Commit SHA or ref to prepare.")
    workspace: str = Field(description="Workspace directory to create or reuse.")


class AcdBootstrapWorkspaceObservation(AcdObservation):
    """Observation returned by workspace bootstrap."""

    bootstrap_record_path: str | None = None


class AcdRegisterFunctionalBlockObservation(AcdObservation):
    """Observation returned by functional-block contract registration."""


class AcdRegisterFirmwareCapabilityObservation(AcdObservation):
    """Observation returned by firmware capability registration."""


class AcdRegisterPartsCatalogEntryObservation(AcdObservation):
    """Observation returned by parts-catalog entry registration."""


class AcdRunFirmwarePipelineObservation(AcdObservation):
    """Observation returned by the firmware Skill subprocess."""


class AcdCompileRequirementChangeObservation(AcdObservation):
    """Observation returned by the requirement compiler."""


class AcdBuildDesignFixtureObservation(AcdObservation):
    """Observation returned by the arbitrary fixture builder."""


class AcdAggregateOrderTotalObservation(AcdObservation):
    """Observation returned by deterministic order-total aggregation."""


class AcdExploreBoardCandidatesObservation(AcdObservation):
    """Observation returned by the bounded exploration loop."""


class AcdExploreEnclosureCandidatesObservation(AcdObservation):
    """Observation returned by bounded enclosure exploration."""


class AcdDiagnoseGateFailureObservation(AcdObservation):
    """Observation returned by the read-only gate diagnosis."""


class AcdCheckOrderReadinessObservation(AcdObservation):
    """Observation returned by the read-only pre-order check."""


class AcdRunDesignLoopObservation(AcdObservation):
    """Observation returned by the graph-driven VibeBB design loop."""


class AcdProbeToolsExecutor(ToolExecutor[AcdProbeToolsAction, AcdObservation]):
    def __call__(
        self,
        action: AcdProbeToolsAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del action, conversation
        try:
            report = probe_all()
            return AcdProbeToolsObservation(
                ok=True,
                operation="probe_tools",
                results=[result.model_dump(mode="json") for result in report.results],
                versions=report.versions(),
                fail_closed=any(not result.is_known for result in report.results),
            )
        except Exception as exc:
            return AcdProbeToolsObservation(**_error(str(exc), operation="probe_tools"))


class AcdValidateDesignGraphExecutor(ToolExecutor[AcdValidateDesignGraphAction, AcdObservation]):
    def __call__(
        self,
        action: AcdValidateDesignGraphAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            graph_path = Path(action.path)
            if not graph_path.is_file():
                return AcdValidateDesignGraphObservation(
                    **_error(
                        f"design graph does not exist: {action.path}",
                        operation="validate_design_graph",
                    )
                )
            graph = DesignGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
            return AcdValidateDesignGraphObservation(
                ok=True,
                operation="validate_design_graph",
                graph_id=graph.graph_id,
                revision=graph.revision,
                node_count=len(graph.nodes),
                path=str(graph_path),
                fail_closed=False,
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            return AcdValidateDesignGraphObservation(
                **_error(str(exc), operation="validate_design_graph")
            )


class AcdRunBoardPipelineExecutor(ToolExecutor[AcdRunBoardPipelineAction, AcdObservation]):
    def __call__(
        self,
        action: AcdRunBoardPipelineAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        fixture_path = Path(action.fixture)
        profile_path = Path(action.fab_profile) if action.fab_profile is not None else None
        try:
            out_path = _pipeline_output_path(action.fixture, action.out, "-mcp")
        except Exception as exc:
            return AcdRunBoardPipelineObservation(
                **_error(
                    f"cannot resolve board pipeline output path: {exc}",
                    operation="run_board_pipeline",
                )
            )
        try:
            if not (fixture_path / "graph.json").is_file():
                return AcdRunBoardPipelineObservation(
                    **_error(
                        f"fixture graph does not exist: {action.fixture}",
                        operation="run_board_pipeline",
                    )
                )
            if profile_path is not None and not profile_path.is_file():
                return AcdRunBoardPipelineObservation(
                    **_error(
                        f"fab profile does not exist: {action.fab_profile}",
                        operation="run_board_pipeline",
                    )
                )
            if action.max_passes <= 0:
                return AcdRunBoardPipelineObservation(
                    **_error(
                        "max_passes must be positive",
                        operation="run_board_pipeline",
                    )
                )
            summary = run_board(
                fixture_path,
                out_path,
                action.max_passes,
                profile_path,
                action.fab_profile_id,
            )
            return AcdRunBoardPipelineObservation(
                ok=True,
                operation="run_board_pipeline",
                summary=summary,
                output_path=str(out_path),
                envelopes=_envelopes(out_path),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunBoardPipelineObservation(
                **_error(str(exc), operation="run_board_pipeline"),
            )


class AcdRunEnclosurePipelineExecutor(ToolExecutor[AcdRunEnclosurePipelineAction, AcdObservation]):
    def __call__(
        self,
        action: AcdRunEnclosurePipelineAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        fixture_path = Path(action.fixture)
        try:
            out_path = _pipeline_output_path(
                action.fixture, action.out, "-enclosure-mcp"
            )
        except Exception as exc:
            return AcdRunEnclosurePipelineObservation(
                **_error(
                    f"cannot resolve enclosure pipeline output path: {exc}",
                    operation="run_enclosure_pipeline",
                )
            )
        try:
            if not (fixture_path / "graph.json").is_file():
                return AcdRunEnclosurePipelineObservation(
                    **_error(
                        f"fixture graph does not exist: {action.fixture}",
                        operation="run_enclosure_pipeline",
                    )
                )
            summary = run_enclosure(fixture_path, out_path)
            return AcdRunEnclosurePipelineObservation(
                ok=True,
                operation="run_enclosure_pipeline",
                summary=summary,
                output_path=str(out_path),
                envelopes=_envelopes(out_path),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunEnclosurePipelineObservation(
                **_error(str(exc), operation="run_enclosure_pipeline"),
            )


class AcdRegisterFunctionalBlockExecutor(
    ToolExecutor[AcdRegisterFunctionalBlockAction, AcdRegisterFunctionalBlockObservation]
):
    def __call__(
        self,
        action: AcdRegisterFunctionalBlockAction,
        conversation: Any = None,
    ) -> AcdRegisterFunctionalBlockObservation:
        del conversation
        try:
            result = register_functional_block_contract(
                action.contract,
                Path(action.registry),
                dry_run=action.dry_run,
            )
            return AcdRegisterFunctionalBlockObservation(
                ok=True,
                operation="register_functional_block",
                registry_id=result.registry_id,
                prior_registry_hash=result.prior_registry_hash,
                new_registry_hash=result.new_registry_hash,
                contract_source=result.contract_source,
                contract=result.contract.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterFunctionalBlockObservation(
                **_error(str(exc), operation="register_functional_block")
            )


class AcdRegisterFirmwareCapabilityExecutor(
    ToolExecutor[
        AcdRegisterFirmwareCapabilityAction,
        AcdRegisterFirmwareCapabilityObservation,
    ]
):
    def __call__(
        self,
        action: AcdRegisterFirmwareCapabilityAction,
        conversation: Any = None,
    ) -> AcdRegisterFirmwareCapabilityObservation:
        del conversation
        try:
            result = register_firmware_capability(
                action.capability,
                Path(action.registry),
                dry_run=action.dry_run,
            )
            return AcdRegisterFirmwareCapabilityObservation(
                ok=True,
                operation="register_firmware_capability",
                registry_id=result.registry_id,
                prior_registry_hash=result.prior_registry_hash,
                new_registry_hash=result.new_registry_hash,
                contract_source=result.capability_source,
                contract=result.capability.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterFirmwareCapabilityObservation(
                **_error(str(exc), operation="register_firmware_capability")
            )


class AcdRegisterPartsCatalogEntryExecutor(
    ToolExecutor[
        AcdRegisterPartsCatalogEntryAction,
        AcdRegisterPartsCatalogEntryObservation,
    ]
):
    def __call__(
        self,
        action: AcdRegisterPartsCatalogEntryAction,
        conversation: Any = None,
    ) -> AcdRegisterPartsCatalogEntryObservation:
        del conversation
        try:
            result = register_parts_catalog_entry(
                action.entry,
                Path(action.catalog),
                dry_run=action.dry_run,
            )
            return AcdRegisterPartsCatalogEntryObservation(
                ok=True,
                operation="register_parts_catalog_entry",
                catalog_id=result.catalog_id,
                prior_catalog_hash=result.prior_catalog_hash,
                new_catalog_hash=result.new_catalog_hash,
                entry_source=result.entry_source,
                entry=result.entry.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterPartsCatalogEntryObservation(
                **_error(str(exc), operation="register_parts_catalog_entry")
            )


def run_bootstrap(
    repo_url: str,
    revision: str,
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run the bundled bootstrap script through its subprocess boundary."""
    script = (
        Path(__file__).resolve().parents[4]
        / "plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py"
    )
    if not script.is_file():
        raise FileNotFoundError(f"workspace bootstrap script does not exist: {script}")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-url",
            repo_url,
            "--revision",
            revision,
            "--workspace",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=3600,
    )
    try:
        report = cast(dict[str, Any], json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise ValueError("workspace bootstrap emitted invalid JSON") from exc
    report["_returncode"] = result.returncode
    return report, {
        "script": str(script),
        "script_sha256": f"sha256:{digest}",
    }


class AcdBootstrapWorkspaceExecutor(
    ToolExecutor[AcdBootstrapWorkspaceAction, AcdBootstrapWorkspaceObservation]
):
    def __call__(
        self,
        action: AcdBootstrapWorkspaceAction,
        conversation: Any = None,
    ) -> AcdBootstrapWorkspaceObservation:
        del conversation
        try:
            if not action.repo_url or not action.revision or not action.workspace:
                return AcdBootstrapWorkspaceObservation(
                    **_error(
                        "repo_url, revision, and workspace are required",
                        operation="bootstrap_workspace",
                    )
                )
            report, provenance = run_bootstrap(
                action.repo_url,
                action.revision,
                Path(action.workspace),
            )
            ok = bool(report.get("ok")) and report.get("_returncode") == 0
            return AcdBootstrapWorkspaceObservation(
                ok=ok,
                operation="bootstrap_workspace",
                failure_reason=report.get("failure_reason"),
                fail_closed=not ok,
                summary=report,
                output_path=report.get("bootstrap_record_path"),
                bootstrap_record_path=report.get("bootstrap_record_path"),
                provenance=provenance,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return AcdBootstrapWorkspaceObservation(
                **_error(str(exc), operation="bootstrap_workspace")
            )


class AcdRunFirmwarePipelineExecutor(ToolExecutor[AcdRunFirmwarePipelineAction, AcdObservation]):
    def __call__(
        self,
        action: AcdRunFirmwarePipelineAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.pipeline.repository import repository_root

            root = repository_root()
            script = root / ("plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py")
            if not script.is_file():
                return AcdRunFirmwarePipelineObservation(
                    **_error(
                        f"firmware Skill script is missing: {script}",
                        operation="run_firmware_pipeline",
                    )
                )
            if action.run_seconds <= 0:
                return AcdRunFirmwarePipelineObservation(
                    **_error("run_seconds must be positive", operation="run_firmware_pipeline")
                )
            out_path = _pipeline_output_path(action.fixture, action.out, "-fw")
            command = [
                "uv",
                "run",
                "--script",
                str(script),
                "--fixture",
                action.fixture,
                "--out",
                str(out_path),
                "--run-seconds",
                str(action.run_seconds),
            ]
            started_at = datetime.now(UTC)
            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True, check=False
            )
            if completed.returncode != 0:
                return AcdRunFirmwarePipelineObservation(
                    **_error(
                        completed.stderr.strip() or f"firmware Skill exited {completed.returncode}",
                        operation="run_firmware_pipeline",
                    ),
                    output_path=str(out_path),
                )
            summary_path = out_path / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(summary, dict):
                raise ValueError("firmware Skill summary must be an object")
            from acd.pipeline.firmware_evidence import write_firmware_evidence

            script_sha256 = _file_sha256(script)
            graph = DesignGraph.model_validate_json(
                (Path(action.fixture) / "graph.json").read_text(encoding="utf-8")
            )
            evidence_path, evidence = write_firmware_evidence(
                graph,
                cast(dict[str, Any], summary),
                out_path,
                script_sha256=script_sha256,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            return AcdRunFirmwarePipelineObservation(
                ok=True,
                operation="run_firmware_pipeline",
                summary=cast(dict[str, Any], summary),
                output_path=str(out_path),
                evidence_path=str(evidence_path),
                revision=graph.revision,
                provenance={
                    "skill_name": "acd-firmware-esp32c3",
                    "script_name": str(script.relative_to(root)),
                    "script_sha256": script_sha256,
                    "measurement_class": "virtual",
                    "evidence_authoritative": evidence.supports_authoritative_pass(
                        graph.revision
                    ),
                    "evidence_provisional": evidence.is_provisional(),
                    "pass_evidence": False,
                },
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunFirmwarePipelineObservation(
                **_error(str(exc), operation="run_firmware_pipeline"),
            )


class AcdCompileRequirementChangeExecutor(
    ToolExecutor[AcdCompileRequirementChangeAction, AcdObservation]
):
    def __call__(
        self,
        action: AcdCompileRequirementChangeAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.requirement_compiler import compile_requirement_change

            result = compile_requirement_change(
                Path(action.fixture_dir),
                Path(action.requirement),
                dry_run=action.dry_run,
                mode=action.mode,
            )
            report = result.report
            return AcdCompileRequirementChangeObservation(
                ok=True,
                operation="compile_requirement_change",
                report=report,
                changed_node_ids=report.get("changed_node_ids"),
                before_hash=report.get("before_hash"),
                after_hash=report.get("after_hash"),
                provenance=report.get("provenance"),
                output_path=action.fixture_dir,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdCompileRequirementChangeObservation(
                **_error(str(exc), operation="compile_requirement_change")
            )


class AcdBuildDesignFixtureExecutor(ToolExecutor[AcdBuildDesignFixtureAction, AcdObservation]):
    def __call__(
        self,
        action: AcdBuildDesignFixtureAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.pipeline.fixture_builder import build_design_fixture
            from acd.schema import DesignFixtureSpec

            spec = DesignFixtureSpec.model_validate_json(
                Path(action.spec).read_text(encoding="utf-8")
            )
            graph = build_design_fixture(
                spec, Path(action.out), overwrite=action.overwrite
            )
            return AcdBuildDesignFixtureObservation(
                ok=True,
                operation="build_design_fixture",
                graph_id=graph.graph_id,
                revision=graph.revision,
                node_count=len(graph.nodes),
                output_path=action.out,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdBuildDesignFixtureObservation(
                **_error(str(exc), operation="build_design_fixture")
            )


class AcdAggregateOrderTotalExecutor(
    ToolExecutor[AcdAggregateOrderTotalAction, AcdObservation]
):
    def __call__(
        self,
        action: AcdAggregateOrderTotalAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.order_total import (
                aggregate_order_total,
                order_total_result_to_document,
            )
            from acd.core.timestamps import parse_evaluated_at
            from acd.schema import FabProfileDocument, OrderScope, QuoteRecord

            records = [
                QuoteRecord.model_validate_json(
                    Path(path).read_text(encoding="utf-8")
                )
                for path in action.quote_records
            ]
            scope = OrderScope.model_validate_json(
                Path(action.order_scope).read_text(encoding="utf-8")
            )
            fab_profile = FabProfileDocument.model_validate_json(
                Path(action.fab_profile).read_text(encoding="utf-8")
            )
            result = aggregate_order_total(
                records,
                scope,
                fab_profile=fab_profile,
                evaluated_at=parse_evaluated_at(action.evaluated_at),
                target_revision=action.target_revision,
            )
            document = order_total_result_to_document(result)
            output_path = Path(action.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=output_path.parent,
                    prefix=f".{output_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(document.model_dump_json(indent=2) + "\n")
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, output_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            return AcdAggregateOrderTotalObservation(
                ok=True,
                operation="aggregate_order_total",
                report={
                    "quote_count": len(records),
                    "target_revision": result.target_revision,
                    "breakdown_hash": result.breakdown_hash,
                    "pass_evidence": False,
                },
                output_path=str(output_path),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdAggregateOrderTotalObservation(
                **_error(str(exc), operation="aggregate_order_total")
            )


class AcdExploreBoardCandidatesExecutor(
    ToolExecutor[AcdExploreBoardCandidatesAction, AcdObservation]
):
    def __call__(
        self,
        action: AcdExploreBoardCandidatesAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.exploration import explore_board_candidates

            result = explore_board_candidates(
                Path(action.graph),
                Path(action.fixture_dir),
                Path(action.out),
                action.max_candidates,
                max_passes=action.max_passes,
                dry_run=action.dry_run,
            )
            return AcdExploreBoardCandidatesObservation(
                ok=True,
                operation="explore_board_candidates",
                report=result.report,
                output_path=str(result.report_path),
                pass_evidence=False,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdExploreBoardCandidatesObservation(
                **_error(str(exc), operation="explore_board_candidates")
            )


class AcdExploreEnclosureCandidatesExecutor(
    ToolExecutor[AcdExploreEnclosureCandidatesAction, AcdObservation]
):
    def __call__(
        self,
        action: AcdExploreEnclosureCandidatesAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.enclosure_exploration import explore_enclosure_candidates

            result = explore_enclosure_candidates(
                Path(action.graph),
                Path(action.fixture_dir),
                Path(action.out),
                action.max_candidates,
                dimensions=action.dimensions or None,
                jobs=action.jobs,
                sampling_points=action.sampling_points,
            )
            return AcdExploreEnclosureCandidatesObservation(
                ok=True,
                operation="explore_enclosure_candidates",
                report=result.report,
                output_path=str(result.report_path),
                pass_evidence=False,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdExploreEnclosureCandidatesObservation(
                **_error(str(exc), operation="explore_enclosure_candidates")
            )


class AcdDiagnoseGateFailureExecutor(ToolExecutor[AcdDiagnoseGateFailureAction, AcdObservation]):
    def __call__(
        self,
        action: AcdDiagnoseGateFailureAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.gate_diagnosis import diagnose_gate_failure

            report = diagnose_gate_failure(
                Path(action.out_dir),
                Path(action.fixture) if action.fixture is not None else None,
                action.lane_id,
            )
            return AcdDiagnoseGateFailureObservation(
                ok=True,
                operation="diagnose_gate_failure",
                report=report,
                output_path=action.out_dir,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdDiagnoseGateFailureObservation(
                **_error(str(exc), operation="diagnose_gate_failure")
            )


class AcdCheckOrderReadinessExecutor(ToolExecutor[AcdCheckOrderReadinessAction, AcdObservation]):
    def __call__(
        self,
        action: AcdCheckOrderReadinessAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from datetime import datetime

            from acd.core.order_total import order_total_result_from_document
            from acd.openhands.order_gate import evaluate_pre_order_gate
            from acd.schema import OrderPolicy, OrderTotalDocument

            repository = Path(action.repository)
            policy = OrderPolicy.model_validate_json(
                Path(action.policy).read_text(encoding="utf-8")
            )
            order_total = order_total_result_from_document(
                OrderTotalDocument.model_validate_json(
                    Path(action.order_total).read_text(encoding="utf-8")
                )
            )
            evaluated_at = datetime.fromisoformat(action.evaluated_at.replace("Z", "+00:00"))
            evidence = [Path(path) for path in action.evidence]
            record = evaluate_pre_order_gate(
                repository=repository,
                policy=policy,
                design_graph_path=Path(action.design_graph_path),
                order_total=order_total,
                evidence_paths=evidence,
                evaluated_at=evaluated_at,
            )
            return AcdCheckOrderReadinessObservation(
                ok=True,
                operation="check_order_readiness",
                report=record.model_dump(mode="json"),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdCheckOrderReadinessObservation(
                **_error(str(exc), operation="check_order_readiness")
            )


class AcdRunDesignLoopExecutor(
    ToolExecutor[AcdRunDesignLoopAction, AcdRunDesignLoopObservation]
):
    def __call__(
        self,
        action: AcdRunDesignLoopAction,
        conversation: Any = None,
    ) -> AcdRunDesignLoopObservation:
        del conversation
        try:
            from acd.core.timestamps import parse_evaluated_at
            from acd.pipeline.design_loop import run_design_loop

            evaluated_at = (
                parse_evaluated_at(action.evaluated_at)
                if action.evaluated_at
                else None
            )
            result = run_design_loop(
                Path(action.fixture),
                Path(action.out_root),
                order_total=Path(action.order_total) if action.order_total else None,
                policy=Path(action.policy),
                repository=Path(action.repository),
                fab_profile=Path(action.fab_profile) if action.fab_profile else None,
                fab_profile_id=action.fab_profile_id,
                max_passes=action.max_passes,
                max_silkscreen_iterations=action.max_silkscreen_iterations,
                run_seconds=action.run_seconds,
                evaluated_at=evaluated_at,
                cache_dir=Path(action.cache_dir) if action.cache_dir else None,
                resume=action.resume,
                jobs=action.jobs,
                explore_board=action.explore_board,
                recover_lanes=action.recover_lanes,
                fixture_overwrite=action.fixture_overwrite,
                max_exploration_candidates=action.max_exploration_candidates,
                max_exploration_rounds=action.max_exploration_rounds,
                requirement=Path(action.requirement) if action.requirement else None,
                fixture_spec=Path(action.fixture_spec) if action.fixture_spec else None,
                quote_records=(
                    [Path(path) for path in action.quote_records]
                    if action.quote_records
                    else None
                ),
                order_scope=Path(action.order_scope) if action.order_scope else None,
            )
            return AcdRunDesignLoopObservation(
                ok=bool(result.get("ok")),
                operation="run_design_loop",
                graph_id=result.get("graph_id"),
                summary=result,
                output_path=action.out_root,
                failure_reason=result.get("failure_reason"),
                fail_closed=bool(result.get("fail_closed", True)),
                pass_evidence=False,
            )
        except Exception as exc:
            return AcdRunDesignLoopObservation(
                **_error(str(exc), operation="run_design_loop"),
                output_path=action.out_root,
            )


class AcdProbeTools(ToolDefinition[AcdProbeToolsAction, AcdProbeToolsObservation]):
    def declared_resources(self, action: Action) -> DeclaredResources:
        del action
        return DeclaredResources(keys=(), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_probe_tools does not accept parameters")
        return [
            cls(
                action_type=AcdProbeToolsAction,
                observation_type=AcdProbeToolsObservation,
                description="Probe configured external tools and report their versions.",
                annotations=ToolAnnotations(
                    title="acd_probe_tools",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdProbeToolsExecutor(),
            )
        ]


class AcdValidateDesignGraph(
    ToolDefinition[AcdValidateDesignGraphAction, AcdValidateDesignGraphObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdValidateDesignGraphAction):
            return DeclaredResources(keys=(), declared=False)
        path = _resolved_resource_path(action.path)
        if path is None:
            return DeclaredResources(keys=(), declared=False)
        return DeclaredResources(keys=(f"file:{path}",), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_validate_design_graph does not accept parameters")
        return [
            cls(
                action_type=AcdValidateDesignGraphAction,
                observation_type=AcdValidateDesignGraphObservation,
                description="Validate a canonical DesignGraph JSON file.",
                annotations=ToolAnnotations(
                    title="acd_validate_design_graph",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdValidateDesignGraphExecutor(),
            )
        ]


class AcdRunBoardPipeline(
    ToolDefinition[AcdRunBoardPipelineAction, AcdRunBoardPipelineObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRunBoardPipelineAction):
            return DeclaredResources(keys=(), declared=False)
        graph_path = _resolved_resource_path(str(Path(action.fixture) / "graph.json"))
        try:
            out_raw = str(
                _pipeline_output_path(action.fixture, action.out, "-mcp")
            )
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        out_path = _resolved_resource_path(out_raw)
        if graph_path is None or out_path is None:
            return DeclaredResources(keys=(), declared=False)
        return DeclaredResources(
            keys=(f"file:{graph_path}", f"acd-out:{out_path}"),
            declared=True,
        )

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_run_board_pipeline does not accept parameters")
        return [
            cls(
                action_type=AcdRunBoardPipelineAction,
                observation_type=AcdRunBoardPipelineObservation,
                description="Run the deterministic board pipeline.",
                annotations=ToolAnnotations(
                    title="acd_run_board_pipeline",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdRunBoardPipelineExecutor(),
            )
        ]


class AcdRunEnclosurePipeline(
    ToolDefinition[AcdRunEnclosurePipelineAction, AcdRunEnclosurePipelineObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRunEnclosurePipelineAction):
            return DeclaredResources(keys=(), declared=False)
        graph_path = _resolved_resource_path(str(Path(action.fixture) / "graph.json"))
        try:
            out_raw = str(
                _pipeline_output_path(
                    action.fixture, action.out, "-enclosure-mcp"
                )
            )
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        out_path = _resolved_resource_path(out_raw)
        if graph_path is None or out_path is None:
            return DeclaredResources(keys=(), declared=False)
        return DeclaredResources(
            keys=(f"file:{graph_path}", f"acd-out:{out_path}"),
            declared=True,
        )

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_run_enclosure_pipeline does not accept parameters")
        return [
            cls(
                action_type=AcdRunEnclosurePipelineAction,
                observation_type=AcdRunEnclosurePipelineObservation,
                description="Run the deterministic enclosure pipeline.",
                annotations=ToolAnnotations(
                    title="acd_run_enclosure_pipeline",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdRunEnclosurePipelineExecutor(),
            )
        ]


class AcdRunFirmwarePipeline(
    ToolDefinition[AcdRunFirmwarePipelineAction, AcdRunFirmwarePipelineObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRunFirmwarePipelineAction):
            return DeclaredResources(keys=(), declared=False)
        try:
            out_raw = str(_pipeline_output_path(action.fixture, action.out, "-fw"))
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        return _resources(
            ("file", Path(action.fixture) / "graph.json"),
            ("acd-out", Path(out_raw)),
            (
                "file",
                Path(__file__).parents[4]
                / "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py",
            ),
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_run_firmware_pipeline does not accept parameters")
        return [
            cls(
                action_type=AcdRunFirmwarePipelineAction,
                observation_type=AcdRunFirmwarePipelineObservation,
                description="Run the firmware Skill through its subprocess boundary.",
                annotations=ToolAnnotations(
                    title="acd_run_firmware_pipeline",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdRunFirmwarePipelineExecutor(),
            )
        ]


class AcdCompileRequirementChange(
    ToolDefinition[AcdCompileRequirementChangeAction, AcdCompileRequirementChangeObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdCompileRequirementChangeAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(
            ("acd-out", Path(action.fixture_dir)),
            ("file", Path(action.requirement)),
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_compile_requirement_change does not accept parameters")
        return [
            cls(
                action_type=AcdCompileRequirementChangeAction,
                observation_type=AcdCompileRequirementChangeObservation,
                description=(
                    "Compile a machine-linked requirement change without "
                    "granting pass authority."
                ),
                annotations=ToolAnnotations(
                    title="acd_compile_requirement_change",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdCompileRequirementChangeExecutor(),
            )
        ]


class AcdBuildDesignFixture(
    ToolDefinition[AcdBuildDesignFixtureAction, AcdBuildDesignFixtureObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdBuildDesignFixtureAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(("file", Path(action.spec)), ("acd-out", Path(action.out)))

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_build_design_fixture does not accept parameters")
        return [
            cls(
                action_type=AcdBuildDesignFixtureAction,
                observation_type=AcdBuildDesignFixtureObservation,
                description="Build a deterministic design fixture from a validated specification.",
                annotations=ToolAnnotations(
                    title="acd_build_design_fixture",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdBuildDesignFixtureExecutor(),
            )
        ]


class AcdAggregateOrderTotal(
    ToolDefinition[AcdAggregateOrderTotalAction, AcdAggregateOrderTotalObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdAggregateOrderTotalAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(
            *[("file", Path(path)) for path in action.quote_records],
            ("file", Path(action.order_scope)),
            ("file", Path(action.fab_profile)),
            ("acd-out", Path(action.output)),
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_aggregate_order_total does not accept parameters")
        return [
            cls(
                action_type=AcdAggregateOrderTotalAction,
                observation_type=AcdAggregateOrderTotalObservation,
                description=(
                    "Aggregate validated quote records into an order-total document "
                    "without granting L1 authority or creating authoritative Evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_aggregate_order_total",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdAggregateOrderTotalExecutor(),
            )
        ]


class AcdExploreBoardCandidates(
    ToolDefinition[AcdExploreBoardCandidatesAction, AcdExploreBoardCandidatesObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdExploreBoardCandidatesAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(
            ("file", Path(action.graph)),
            ("acd-out", Path(action.fixture_dir)),
            ("acd-out", Path(action.out)),
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_explore_board_candidates does not accept parameters")
        return [
            cls(
                action_type=AcdExploreBoardCandidatesAction,
                observation_type=AcdExploreBoardCandidatesObservation,
                description="Explore bounded board candidates under deterministic gate authority.",
                annotations=ToolAnnotations(
                    title="acd_explore_board_candidates",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdExploreBoardCandidatesExecutor(),
            )
        ]


class AcdExploreEnclosureCandidates(
    ToolDefinition[
        AcdExploreEnclosureCandidatesAction, AcdExploreEnclosureCandidatesObservation
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdExploreEnclosureCandidatesAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(
            ("file", Path(action.graph)),
            ("acd-out", Path(action.fixture_dir)),
            ("acd-out", Path(action.out)),
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_explore_enclosure_candidates does not accept parameters")
        return [
            cls(
                action_type=AcdExploreEnclosureCandidatesAction,
                observation_type=AcdExploreEnclosureCandidatesObservation,
                description=(
                    "Explore bounded enclosure candidates under deterministic "
                    "mechanical gates."
                ),
                annotations=ToolAnnotations(
                    title="acd_explore_enclosure_candidates",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdExploreEnclosureCandidatesExecutor(),
            )
        ]


class AcdDiagnoseGateFailure(
    ToolDefinition[AcdDiagnoseGateFailureAction, AcdDiagnoseGateFailureObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdDiagnoseGateFailureAction):
            return DeclaredResources(keys=(), declared=False)
        return _resources(("acd-out", Path(action.out_dir)))

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_diagnose_gate_failure does not accept parameters")
        return [
            cls(
                action_type=AcdDiagnoseGateFailureAction,
                observation_type=AcdDiagnoseGateFailureObservation,
                description="Read hashed diagnostic artifacts without producing gate Evidence.",
                annotations=ToolAnnotations(
                    title="acd_diagnose_gate_failure",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdDiagnoseGateFailureExecutor(),
            )
        ]


class AcdCheckOrderReadiness(
    ToolDefinition[AcdCheckOrderReadinessAction, AcdCheckOrderReadinessObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdCheckOrderReadinessAction):
            return DeclaredResources(keys=(), declared=False)
        paths = [
            ("file", Path(action.policy)),
            ("file", Path(action.design_graph_path)),
            ("file", Path(action.order_total)),
            *[("file", Path(path)) for path in action.evidence],
        ]
        return _resources(*paths)

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_check_order_readiness does not accept parameters")
        return [
            cls(
                action_type=AcdCheckOrderReadinessAction,
                observation_type=AcdCheckOrderReadinessObservation,
                description="Check pre-order readiness read-only; never execute an order.",
                annotations=ToolAnnotations(
                    title="acd_check_order_readiness",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdCheckOrderReadinessExecutor(),
            )
        ]


class AcdRunDesignLoop(
    ToolDefinition[AcdRunDesignLoopAction, AcdRunDesignLoopObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRunDesignLoopAction):
            return DeclaredResources(keys=(), declared=False)
        root = Path(action.repository)
        cache_resource = (
            (("acd-out", Path(action.cache_dir)),) if action.cache_dir else ()
        )
        return _resources(
            ("file", Path(action.fixture) / "graph.json"),
            ("file", Path(action.fixture) / "requirements.json"),
            *((("file", Path(action.order_total)),) if action.order_total else ()),
            ("file", Path(action.policy)),
            *((("file", Path(action.fab_profile)),) if action.fab_profile else ()),
            *(
                ("file", Path(path))
                for path in action.quote_records or []
            ),
            *((("file", Path(action.order_scope)),) if action.order_scope else ()),
            *((("file", Path(action.requirement)),) if action.requirement else ()),
            *((("file", Path(action.fixture_spec)),) if action.fixture_spec else ()),
            ("file", root / "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py"),
            ("acd-out", Path(action.out_root)),
            *cache_resource,
        )

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_run_design_loop does not accept parameters")
        return [
            cls(
                action_type=AcdRunDesignLoopAction,
                observation_type=AcdRunDesignLoopObservation,
                description=(
                    "Run the fixed graph-driven VibeBB design loop through "
                    "deterministic stages, with optional artifact cache/resume, "
                    "stage timing, bounded lane parallelism, and opt-in bounded "
                    "board exploration after board rejection. Cache reuse and "
                    "exploration never restore verdicts or Evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_run_design_loop",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                executor=AcdRunDesignLoopExecutor(),
            )
        ]


class AcdBootstrapWorkspace(
    ToolDefinition[AcdBootstrapWorkspaceAction, AcdBootstrapWorkspaceObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdBootstrapWorkspaceAction):
            return DeclaredResources(keys=(), declared=False)
        path = _resolved_resource_path(action.workspace)
        if path is None:
            return DeclaredResources(keys=(), declared=False)
        return DeclaredResources(keys=(f"acd-workspace:{path}",), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_bootstrap_workspace does not accept parameters")
        return [
            cls(
                action_type=AcdBootstrapWorkspaceAction,
                observation_type=AcdBootstrapWorkspaceObservation,
                description="Initialize and doctor a clean ACD workspace.",
                annotations=ToolAnnotations(
                    title="acd_bootstrap_workspace",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=True,
                ),
                executor=AcdBootstrapWorkspaceExecutor(),
            )
        ]


class AcdRegisterFunctionalBlock(
    ToolDefinition[
        AcdRegisterFunctionalBlockAction,
        AcdRegisterFunctionalBlockObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterFunctionalBlockAction):
            return DeclaredResources(keys=(), declared=False)
        registry_path = _resolved_resource_path(action.registry)
        if registry_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{registry_path}"]
        contract_path = _resolved_resource_path(action.contract)
        if contract_path is not None and contract_path.is_file():
            keys.insert(0, f"file:{contract_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_register_functional_block does not accept parameters")
        return [
            cls(
                action_type=AcdRegisterFunctionalBlockAction,
                observation_type=AcdRegisterFunctionalBlockObservation,
                description=(
                    "Validate and register one functional-block contract declaration."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_functional_block",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterFunctionalBlockExecutor(),
            )
        ]


class AcdRegisterFirmwareCapability(
    ToolDefinition[
        AcdRegisterFirmwareCapabilityAction,
        AcdRegisterFirmwareCapabilityObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterFirmwareCapabilityAction):
            return DeclaredResources(keys=(), declared=False)
        registry_path = _resolved_resource_path(action.registry)
        if registry_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{registry_path}"]
        capability_path = _resolved_resource_path(action.capability)
        if capability_path is not None and capability_path.is_file():
            keys.insert(0, f"file:{capability_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError(
                "acd_register_firmware_capability does not accept parameters"
            )
        return [
            cls(
                action_type=AcdRegisterFirmwareCapabilityAction,
                observation_type=AcdRegisterFirmwareCapabilityObservation,
                description=(
                    "Validate and register one firmware capability declaration. "
                    "This is a declaration path, not gate evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_firmware_capability",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterFirmwareCapabilityExecutor(),
            )
        ]


class AcdRegisterPartsCatalogEntry(
    ToolDefinition[
        AcdRegisterPartsCatalogEntryAction,
        AcdRegisterPartsCatalogEntryObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterPartsCatalogEntryAction):
            return DeclaredResources(keys=(), declared=False)
        catalog_path = _resolved_resource_path(action.catalog)
        if catalog_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{catalog_path}"]
        entry_path = _resolved_resource_path(action.entry)
        if entry_path is not None and entry_path.is_file():
            keys.insert(0, f"file:{entry_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_register_parts_catalog_entry does not accept parameters")
        return [
            cls(
                action_type=AcdRegisterPartsCatalogEntryAction,
                observation_type=AcdRegisterPartsCatalogEntryObservation,
                description=(
                    "Validate and register one parts-catalog entry declaration "
                    "without granting L1 authority or creating Evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_parts_catalog_entry",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterPartsCatalogEntryExecutor(),
            )
        ]


ACD_TOOL_DEFINITIONS: tuple[tuple[str, type[ToolDefinition[Any, Any]]], ...] = (
    ("acd_probe_tools", AcdProbeTools),
    ("acd_validate_design_graph", AcdValidateDesignGraph),
    ("acd_run_board_pipeline", AcdRunBoardPipeline),
    ("acd_run_enclosure_pipeline", AcdRunEnclosurePipeline),
    ("acd_register_functional_block", AcdRegisterFunctionalBlock),
    ("acd_register_firmware_capability", AcdRegisterFirmwareCapability),
    ("acd_register_parts_catalog_entry", AcdRegisterPartsCatalogEntry),
    ("acd_bootstrap_workspace", AcdBootstrapWorkspace),
    ("acd_run_firmware_pipeline", AcdRunFirmwarePipeline),
    ("acd_compile_requirement_change", AcdCompileRequirementChange),
    ("acd_build_design_fixture", AcdBuildDesignFixture),
    ("acd_aggregate_order_total", AcdAggregateOrderTotal),
    ("acd_explore_board_candidates", AcdExploreBoardCandidates),
    ("acd_explore_enclosure_candidates", AcdExploreEnclosureCandidates),
    ("acd_diagnose_gate_failure", AcdDiagnoseGateFailure),
    ("acd_check_order_readiness", AcdCheckOrderReadiness),
    ("acd_run_design_loop", AcdRunDesignLoop),
)


def register_acd_tools() -> None:
    """Register ACD ToolDefinitions without import-time side effects."""
    registered = set(list_registered_tools())
    for name, tool in ACD_TOOL_DEFINITIONS:
        if name not in registered:
            register_tool(name, tool)
            registered.add(name)
