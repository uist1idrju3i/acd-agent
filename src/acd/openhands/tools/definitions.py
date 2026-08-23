"""OpenHands SDK ToolDefinitions for deterministic ACD entrypoints."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

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

from acd.core.functional_block_entry import register_functional_block_contract
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
    from acd.pipeline.gd1_enclosure import run_pipeline

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
        elif self.operation == "register_functional_block":
            text = (
                f"{self.operation}: registry_id={self.registry_id}, "
                f"prior_registry_hash={self.prior_registry_hash}, "
                f"new_registry_hash={self.new_registry_hash}, "
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
    """Run the deterministic GD1 board pipeline."""

    fixture: str = Field(
        default="fixtures/golden-design-1",
        description="Fixture directory containing graph.json.",
    )
    out: str = Field(
        default="out/gd1-mcp",
        description="Output directory for generated board artifacts.",
    )
    fab_profile: str | None = Field(default=None, description="Fabrication profile JSON path.")
    fab_profile_id: str | None = Field(
        default=None, description="Registered fabrication profile id."
    )
    max_passes: int = Field(
        default=3,
        description="Maximum number of deterministic pipeline passes.",
    )


class AcdRunEnclosurePipelineAction(Action):
    """Run the deterministic GD1 enclosure pipeline."""

    fixture: str = Field(
        default="fixtures/golden-design-1",
        description="Fixture directory containing graph.json.",
    )
    out: str = Field(
        default="out/gd1-enclosure-mcp",
        description="Output directory for generated enclosure artifacts.",
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


class AcdRunFirmwarePipelineAction(Action):
    fixture: str = Field(default="fixtures/golden-design-1")
    out: str = Field(default="out/gd1-fw")
    run_seconds: int = Field(
        default=15,
        ge=1,
        description="Bounded virtual-run duration.",
    )


class AcdCompileRequirementChangeAction(Action):
    fixture_dir: str
    requirement: str
    dry_run: bool = False


class AcdBuildDesignFixtureAction(Action):
    spec: str
    out: str


class AcdExploreBoardCandidatesAction(Action):
    graph: str
    fixture_dir: str
    out: str
    max_candidates: int = Field(ge=1)
    max_passes: int = Field(default=3, ge=1)
    dry_run: bool = False


class AcdDiagnoseGateFailureAction(Action):
    out_dir: str


class AcdCheckOrderReadinessAction(Action):
    repository: str = "."
    policy: str = "plugins/acd/hooks/order-policy.json"
    order_total: str
    evidence: list[str] = Field(default_factory=list)
    evaluated_at: str


class AcdRunDesignLoopAction(Action):
    """Run the fixed graph-driven VibeBB design loop."""

    fixture: str = Field(default="fixtures/golden-design-1")
    out_root: str = Field(default="out")
    order_total: str
    policy: str = "plugins/acd/hooks/order-policy.json"
    repository: str = "."
    fab_profile: str | None = None
    fab_profile_id: str | None = None
    max_passes: int = Field(default=3, ge=1)
    max_silkscreen_iterations: int = Field(default=5, ge=1)
    run_seconds: int = Field(default=15, ge=1)
    evaluated_at: str | None = None


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


class AcdRunFirmwarePipelineObservation(AcdObservation):
    """Observation returned by the firmware Skill subprocess."""


class AcdCompileRequirementChangeObservation(AcdObservation):
    """Observation returned by the requirement compiler."""


class AcdBuildDesignFixtureObservation(AcdObservation):
    """Observation returned by the arbitrary fixture builder."""


class AcdExploreBoardCandidatesObservation(AcdObservation):
    """Observation returned by the bounded exploration loop."""


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
        out_path = Path(action.out)
        profile_path = Path(action.fab_profile) if action.fab_profile is not None else None
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
                output_path=action.out,
                envelopes=_envelopes(out_path),
            )


class AcdRunEnclosurePipelineExecutor(ToolExecutor[AcdRunEnclosurePipelineAction, AcdObservation]):
    def __call__(
        self,
        action: AcdRunEnclosurePipelineAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        fixture_path = Path(action.fixture)
        out_path = Path(action.out)
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
                output_path=action.out,
                envelopes=_envelopes(out_path),
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
            out_path = Path(action.out)
            command = [
                "uv",
                "run",
                "--script",
                str(script),
                "--fixture",
                action.fixture,
                "--out",
                action.out,
                "--run-seconds",
                str(action.run_seconds),
            ]
            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True, check=False
            )
            if completed.returncode != 0:
                return AcdRunFirmwarePipelineObservation(
                    **_error(
                        completed.stderr.strip() or f"firmware Skill exited {completed.returncode}",
                        operation="run_firmware_pipeline",
                    ),
                    output_path=action.out,
                )
            summary_path = out_path / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(summary, dict):
                raise ValueError("firmware Skill summary must be an object")
            return AcdRunFirmwarePipelineObservation(
                ok=True,
                operation="run_firmware_pipeline",
                summary=cast(dict[str, Any], summary),
                output_path=action.out,
                provenance={
                    "skill_name": "acd-firmware-esp32c3",
                    "script_name": str(script.relative_to(root)),
                    "script_sha256": _file_sha256(script),
                    "pass_evidence": False,
                },
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunFirmwarePipelineObservation(
                **_error(str(exc), operation="run_firmware_pipeline"),
                output_path=action.out,
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
            graph = build_design_fixture(spec, Path(action.out))
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


class AcdDiagnoseGateFailureExecutor(ToolExecutor[AcdDiagnoseGateFailureAction, AcdObservation]):
    def __call__(
        self,
        action: AcdDiagnoseGateFailureAction,
        conversation: Any = None,
    ) -> AcdObservation:
        del conversation
        try:
            from acd.core.gate_diagnosis import diagnose_gate_failure

            report = diagnose_gate_failure(Path(action.out_dir))
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
                order_total=Path(action.order_total),
                policy=Path(action.policy),
                repository=Path(action.repository),
                fab_profile=Path(action.fab_profile) if action.fab_profile else None,
                fab_profile_id=action.fab_profile_id,
                max_passes=action.max_passes,
                max_silkscreen_iterations=action.max_silkscreen_iterations,
                run_seconds=action.run_seconds,
                evaluated_at=evaluated_at,
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
        out_path = _resolved_resource_path(action.out)
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
                description="Run the deterministic GD1 board pipeline.",
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
        out_path = _resolved_resource_path(action.out)
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
                description="Run the deterministic GD1 enclosure pipeline.",
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
        return _resources(
            ("file", Path(action.fixture) / "graph.json"),
            ("acd-out", Path(action.out)),
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
        return _resources(
            ("file", Path(action.fixture) / "graph.json"),
            ("file", Path(action.order_total)),
            ("file", Path(action.policy)),
            ("file", root / "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py"),
            ("acd-out", Path(action.out_root)),
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
                    "deterministic stages."
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


ACD_TOOL_DEFINITIONS: tuple[tuple[str, type[ToolDefinition[Any, Any]]], ...] = (
    ("acd_probe_tools", AcdProbeTools),
    ("acd_validate_design_graph", AcdValidateDesignGraph),
    ("acd_run_board_pipeline", AcdRunBoardPipeline),
    ("acd_run_enclosure_pipeline", AcdRunEnclosurePipeline),
    ("acd_register_functional_block", AcdRegisterFunctionalBlock),
    ("acd_bootstrap_workspace", AcdBootstrapWorkspace),
    ("acd_run_firmware_pipeline", AcdRunFirmwarePipeline),
    ("acd_compile_requirement_change", AcdCompileRequirementChange),
    ("acd_build_design_fixture", AcdBuildDesignFixture),
    ("acd_explore_board_candidates", AcdExploreBoardCandidates),
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
