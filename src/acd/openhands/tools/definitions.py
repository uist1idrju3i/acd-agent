"""OpenHands SDK ToolDefinitions for deterministic ACD entrypoints."""

from __future__ import annotations

import json
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

    @property
    def to_llm_content(self) -> list[TextContent]:
        if self.fail_closed:
            reason = self.failure_reason or "an unknown failure occurred"
            text = (
                f"{self.operation} failed closed: {reason}. "
                "This is not pass evidence."
            )
        elif self.operation == "probe_tools":
            versions = self.versions or {}
            version_text = ", ".join(
                f"{name}={versions[name]}" for name in sorted(versions)
            ) or "none"
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


class AcdProbeToolsObservation(AcdObservation):
    """Observation returned by the external tool probe."""


class AcdValidateDesignGraphObservation(AcdObservation):
    """Observation returned by graph validation."""


class AcdRunBoardPipelineObservation(AcdObservation):
    """Observation returned by the board pipeline."""


class AcdRunEnclosurePipelineObservation(AcdObservation):
    """Observation returned by the enclosure pipeline."""


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


class AcdValidateDesignGraphExecutor(
    ToolExecutor[AcdValidateDesignGraphAction, AcdObservation]
):
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
            graph = DesignGraph.model_validate(
                json.loads(graph_path.read_text(encoding="utf-8"))
            )
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


class AcdRunBoardPipelineExecutor(
    ToolExecutor[AcdRunBoardPipelineAction, AcdObservation]
):
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


class AcdRunEnclosurePipelineExecutor(
    ToolExecutor[AcdRunEnclosurePipelineAction, AcdObservation]
):
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
        graph_path = _resolved_resource_path(
            str(Path(action.fixture) / "graph.json")
        )
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
        graph_path = _resolved_resource_path(
            str(Path(action.fixture) / "graph.json")
        )
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


ACD_TOOL_DEFINITIONS: tuple[
    tuple[str, type[ToolDefinition[Any, Any]]], ...
] = (
    ("acd_probe_tools", AcdProbeTools),
    ("acd_validate_design_graph", AcdValidateDesignGraph),
    ("acd_run_board_pipeline", AcdRunBoardPipeline),
    ("acd_run_enclosure_pipeline", AcdRunEnclosurePipeline),
)


def register_acd_tools() -> None:
    """Register ACD ToolDefinitions without import-time side effects."""
    registered = set(list_registered_tools())
    for name, tool in ACD_TOOL_DEFINITIONS:
        if name not in registered:
            register_tool(name, tool)
            registered.add(name)
