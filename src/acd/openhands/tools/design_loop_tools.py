"""ToolDefinitions for requirement compilation, fixtures, exploration, and the design loop."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from openhands.sdk.tool import (
    Action,
    DeclaredResources,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
)
from pydantic import Field

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES

if TYPE_CHECKING:
    from openhands.sdk.conversation.state import ConversationState
from acd.openhands.tools._base import (
    AcdObservation,
    declared_resources_for,
    error_payload,
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
                **error_payload(str(exc), operation="compile_requirement_change")
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
                **error_payload(str(exc), operation="build_design_fixture")
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
                **error_payload(str(exc), operation="aggregate_order_total")
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
                **error_payload(str(exc), operation="explore_board_candidates")
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
                **error_payload(str(exc), operation="explore_enclosure_candidates")
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
                **error_payload(str(exc), operation="diagnose_gate_failure")
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
                **error_payload(str(exc), operation="check_order_readiness")
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
                **error_payload(str(exc), operation="run_design_loop"),
                output_path=action.out_root,
            )


class AcdCompileRequirementChange(
    ToolDefinition[AcdCompileRequirementChangeAction, AcdCompileRequirementChangeObservation]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdCompileRequirementChangeAction):
            return DeclaredResources(keys=(), declared=False)
        return declared_resources_for(
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
        return declared_resources_for(("file", Path(action.spec)), ("acd-out", Path(action.out)))

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
        return declared_resources_for(
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
        return declared_resources_for(
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
        return declared_resources_for(
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
        return declared_resources_for(("acd-out", Path(action.out_dir)))

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
        return declared_resources_for(*paths)

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
        return declared_resources_for(
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
