"""ToolDefinitions that probe tools, validate graphs, and run the three lane pipelines."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

from openhands.sdk.tool import (
    Action,
    DeclaredResources,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
)
from pydantic import Field

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.runtime.fileio import file_sha256, read_json
from acd.openhands.tools.probe import probe_all
from acd.schema.design_graph import DesignGraph

if TYPE_CHECKING:
    from openhands.sdk.conversation.state import ConversationState
from acd.openhands.tools._base import (
    AcdObservation,
    collect_envelopes,
    declared_resources_for,
    error_payload,
    pipeline_output_path,
    resolved_resource_path,
)


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


class AcdRunFirmwarePipelineObservation(AcdObservation):
    """Observation returned by the firmware Skill subprocess."""


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
            return AcdProbeToolsObservation(**error_payload(str(exc), operation="probe_tools"))


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
                    **error_payload(
                        f"design graph does not exist: {action.path}",
                        operation="validate_design_graph",
                    )
                )
            graph = DesignGraph.model_validate(read_json(graph_path))
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
                **error_payload(str(exc), operation="validate_design_graph")
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
            out_path = pipeline_output_path(action.fixture, action.out, "-mcp")
        except Exception as exc:
            return AcdRunBoardPipelineObservation(
                **error_payload(
                    f"cannot resolve board pipeline output path: {exc}",
                    operation="run_board_pipeline",
                )
            )
        try:
            if not (fixture_path / "graph.json").is_file():
                return AcdRunBoardPipelineObservation(
                    **error_payload(
                        f"fixture graph does not exist: {action.fixture}",
                        operation="run_board_pipeline",
                    )
                )
            if profile_path is not None and not profile_path.is_file():
                return AcdRunBoardPipelineObservation(
                    **error_payload(
                        f"fab profile does not exist: {action.fab_profile}",
                        operation="run_board_pipeline",
                    )
                )
            if action.max_passes <= 0:
                return AcdRunBoardPipelineObservation(
                    **error_payload(
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
                envelopes=collect_envelopes(out_path),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunBoardPipelineObservation(
                **error_payload(str(exc), operation="run_board_pipeline"),
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
            out_path = pipeline_output_path(
                action.fixture, action.out, "-enclosure-mcp"
            )
        except Exception as exc:
            return AcdRunEnclosurePipelineObservation(
                **error_payload(
                    f"cannot resolve enclosure pipeline output path: {exc}",
                    operation="run_enclosure_pipeline",
                )
            )
        try:
            if not (fixture_path / "graph.json").is_file():
                return AcdRunEnclosurePipelineObservation(
                    **error_payload(
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
                envelopes=collect_envelopes(out_path),
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRunEnclosurePipelineObservation(
                **error_payload(str(exc), operation="run_enclosure_pipeline"),
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
        encoding="utf-8",
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
                    **error_payload(
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
                **error_payload(str(exc), operation="bootstrap_workspace")
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
                    **error_payload(
                        f"firmware Skill script is missing: {script}",
                        operation="run_firmware_pipeline",
                    )
                )
            if action.run_seconds <= 0:
                return AcdRunFirmwarePipelineObservation(
                    **error_payload(
                        "run_seconds must be positive", operation="run_firmware_pipeline"
                    )
                )
            out_path = pipeline_output_path(action.fixture, action.out, "-fw")
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
                command,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if completed.returncode != 0:
                return AcdRunFirmwarePipelineObservation(
                    **error_payload(
                        completed.stderr.strip() or f"firmware Skill exited {completed.returncode}",
                        operation="run_firmware_pipeline",
                    ),
                    output_path=str(out_path),
                )
            summary_path = out_path / "summary.json"
            summary = read_json(summary_path)
            if not isinstance(summary, dict):
                raise ValueError("firmware Skill summary must be an object")
            from acd.pipeline.firmware_evidence import write_firmware_evidence

            script_sha256 = file_sha256(script)
            graph = DesignGraph.model_validate_json(
                (Path(action.fixture) / "graph.json").read_text(encoding="utf-8")
            )
            evidence_path, evidence = write_firmware_evidence(
                graph,
                cast(dict[str, Any], summary),
                out_path,
                graph_path=Path(action.fixture) / "graph.json",
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
                **error_payload(str(exc), operation="run_firmware_pipeline"),
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
        path = resolved_resource_path(action.path)
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
        graph_path = resolved_resource_path(str(Path(action.fixture) / "graph.json"))
        try:
            out_raw = str(
                pipeline_output_path(action.fixture, action.out, "-mcp")
            )
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        out_path = resolved_resource_path(out_raw)
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
        graph_path = resolved_resource_path(str(Path(action.fixture) / "graph.json"))
        try:
            out_raw = str(
                pipeline_output_path(
                    action.fixture, action.out, "-enclosure-mcp"
                )
            )
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        out_path = resolved_resource_path(out_raw)
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
            out_raw = str(pipeline_output_path(action.fixture, action.out, "-fw"))
        except (OSError, UnicodeError, ValueError):
            return DeclaredResources(keys=(), declared=False)
        return declared_resources_for(
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


class AcdBootstrapWorkspace(
    ToolDefinition[AcdBootstrapWorkspaceAction, AcdBootstrapWorkspaceObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdBootstrapWorkspaceAction):
            return DeclaredResources(keys=(), declared=False)
        path = resolved_resource_path(action.workspace)
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
