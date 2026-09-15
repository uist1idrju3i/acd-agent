"""Stage runners for the graph-driven design loop."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from acd.adapters.kicad.fab.silkscreen import SilkscreenGateError
from acd.core.lane_preflight import (
    LANE_REQUIREMENTS,
    missing_declaration_action,
    missing_declarations,
    run_lane_preflight,
)
from acd.core.manufacturing_submission import (
    ManufacturingSubmissionError,
    evaluate_manufacturing_submission,
)
from acd.core.order_total import (
    aggregate_order_total,
    order_total_result_from_document,
    order_total_result_to_document,
)
from acd.core.requirement_compiler import compile_requirement_change
from acd.core.requirements import (
    default_requirements_path,
    load_requirements,
    validate_requirements,
)
from acd.core.silkscreen import extract_silkscreen_lane
from acd.openhands.order_gate import evaluate_pre_order_gate
from acd.pipeline.enclosure import run_pipeline as run_enclosure_pipeline
from acd.pipeline.firmware_lane import FirmwareLaneError, run_firmware_lane
from acd.pipeline.fixture_builder import build_design_fixture
from acd.pipeline.gd1_board import run_pipeline as run_board_pipeline
from acd.pipeline.graph_diff_projection import (
    GraphDiffProjectionError,
    run_graph_diff_projection,
)
from acd.pipeline.lane_plan import (
    DESIGN_LOOP_LANE_IDS,
)
from acd.pipeline.projection_docs import ProjectionDocsError, run_projection_docs
from acd.pipeline.silkscreen_resolve import (
    ROUTED_SILKSCREEN_MAX_ROUNDS,
    reresolve_routed_silkscreen,
    resolve_silkscreen,
)
from acd.pipeline.visual_review import derive_visual_review
from acd.schema import (
    DesignFixtureSpec,
    FabProfileDocument,
    OrderPolicy,
    OrderScope,
    OrderTotalDocument,
    QuoteRecord,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.lane_preflight import LanePreflightReport

from .config import DesignLoopConfig, StageRunner, load_graph, stage_failure, stage_success

SILKSCREEN_NEXT_STEP_ACTION = (
    "shorten the text value of the listed mechanical.silk_text nodes "
    "first, then widen placement_search_limit_mm on the node, then "
    "declare x_mm/y_mm (see candidate_failures in the stage summary); "
    "do not remove all functional labels — a single remaining unplaced "
    "text is accepted by measurement and then fails 'silkscreen "
    "resolution accepted unresolved text coordinates' (keep at least "
    "one placed label alongside); silkscreen gate thresholds are not "
    "adjustable"
)


def _run_silkscreen(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("silkscreen-resolve").output_path
    if output is None:
        raise ValueError("silkscreen stage has no output path")
    result = resolve_silkscreen(
        config.fixture_dir,
        output,
        config.fab_profile,
        config.max_silkscreen_iterations,
        config.fab_profile_id,
    )
    status = result.get("status")
    if status == "resolved":
        return stage_success("silkscreen-resolve", output_path=str(output), summary=result)
    unresolved = sorted(
        text.node_id
        for text in extract_silkscreen_lane(load_graph(config.fixture_dir)).texts
        if text.x_mm is None or text.y_mm is None
    )
    return stage_failure(
        "silkscreen-resolve",
        f"silkscreen resolution ended with status {status!r}; "
        f"unresolved silk texts: {', '.join(unresolved) or 'none'}",
        output_path=str(output),
        summary=result,
        next_step_action=SILKSCREEN_NEXT_STEP_ACTION,
    )


def run_board_stage(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("board-pipeline").output_path
    if output is None:
        raise ValueError("board stage has no output path")

    def pipeline() -> dict[str, Any]:
        return run_board_pipeline(
            config.fixture_dir,
            output,
            config.max_passes,
            config.fab_profile,
            fab_profile_id=config.fab_profile_id,
            cache_dir=(
                config.cache_dir if config.lane_plan.stage("board-pipeline").cacheable else None
            ),
            timing_recorder=config.timing_recorder,
        )

    try:
        result = pipeline()
    except SilkscreenGateError as exc:
        # The routed board carries SES-imported vias and mask openings the
        # pre-routing resolver never saw; re-resolve once on the routed board
        # (bounded to ROUTED_SILKSCREEN_MAX_ROUNDS) and rerun the gate, which
        # stays the only pass authority.
        routed_board = output / "routed" / f"{config.output_prefix}.kicad_pcb"
        try:
            reresolve = reresolve_routed_silkscreen(
                config.fixture_dir,
                output / "routed-silkscreen-reresolve",
                routed_board,
                config.fab_profile,
                config.fab_profile_id,
            )
        except Exception as inner:
            return stage_failure(
                "board-pipeline",
                f"{type(exc).__name__}: {exc}; routed silkscreen re-resolution "
                f"failed (fail-closed): {type(inner).__name__}: {inner}",
            )
        if reresolve.get("status") != "candidates_written":
            return stage_failure(
                "board-pipeline",
                f"{type(exc).__name__}: {exc}; routed silkscreen re-resolution "
                f"produced no writable candidates: status={reresolve.get('status')}",
                routed_silkscreen_reresolve=reresolve,
                next_step_action=SILKSCREEN_NEXT_STEP_ACTION,
            )
        try:
            result = pipeline()
        except SilkscreenGateError as second:
            return stage_failure(
                "board-pipeline",
                f"routed silkscreen gate rejected after "
                f"{ROUTED_SILKSCREEN_MAX_ROUNDS} bounded re-resolution round "
                f"(fail-closed): {type(second).__name__}: {second}",
                routed_silkscreen_reresolve=reresolve,
                next_step_action=SILKSCREEN_NEXT_STEP_ACTION,
            )
        return stage_success(
            "board-pipeline",
            output_path=str(output),
            summary=result,
            routed_silkscreen_reresolve=reresolve,
        )
    return stage_success("board-pipeline", output_path=str(output), summary=result)


def _run_enclosure(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("enclosure-pipeline").output_path
    if output is None:
        raise ValueError("enclosure stage has no output path")
    result = run_enclosure_pipeline(
        config.fixture_dir,
        output,
        timing_recorder=config.timing_recorder,
    )
    return stage_success("enclosure-pipeline", output_path=str(output), summary=result)


def _run_firmware(config: DesignLoopConfig) -> dict[str, Any]:
    output = config.lane_plan.stage("firmware-pipeline").output_path
    if output is None:
        raise ValueError("firmware stage has no output path")
    try:
        result = run_firmware_lane(
            config.repository,
            config.fixture_dir,
            output,
            run_seconds=config.run_seconds,
        )
    except FirmwareLaneError as exc:
        fields: dict[str, Any] = {}
        if exc.output_path is not None:
            fields["output_path"] = str(exc.output_path)
        return stage_failure("firmware-pipeline", str(exc), **fields)
    return stage_success(
        "firmware-pipeline",
        output_path=str(result.output_path),
        summary=result.summary,
        evidence_path=str(result.evidence_path),
        evidence_authoritative=result.evidence.supports_authoritative_pass(result.graph_revision),
        evidence_provisional=result.evidence.is_provisional(),
        measurement_class="virtual",
        provenance={
            "skill_name": "acd-firmware-esp32c3",
            "script_name": str(result.script_path.relative_to(config.repository)),
            "script_sha256": result.script_sha256,
            "pass_evidence": False,
        },
    )


def _run_visual_review_manifest(config: DesignLoopConfig) -> dict[str, Any]:
    """Derive review PNGs and write the mandatory vision-review manifest.

    The manifest is an L3/L2 boundary: it only records which projections the
    agent must inspect with the vision tool. It never grants pass authority.
    """
    manifest = derive_visual_review(config.out_root, jobs=config.jobs)
    return stage_success(
        "visual-review-manifest",
        manifest_path=str(config.out_root / "visual-review-manifest.json"),
        required=len(manifest.required),
        status="pending-agent-inspection",
    )


def _run_graph_diff_projection(config: DesignLoopConfig) -> dict[str, Any]:
    if config.previous_graph_path is None:
        return stage_success(
            "graph-diff-projection",
            status="skipped",
            reason="previous graph not declared",
            record_class="L3",
        )
    try:
        output = run_graph_diff_projection(
            graph_path=config.fixture_dir / "graph.json",
            previous_graph_path=config.previous_graph_path,
            out_dir=config.out_root / "graph-diff",
            project_name=config.graph_id,
        )
    except GraphDiffProjectionError as exc:
        return stage_failure(
            "graph-diff-projection",
            str(exc),
            record_class="L3",
        )
    return stage_success(
        "graph-diff-projection",
        output_path=str(output),
        record_class="L3",
    )


def _run_projection_docs(config: DesignLoopConfig) -> dict[str, Any]:
    board_out = config.lane_plan.stage("board-pipeline").output_path
    enclosure_out = config.lane_plan.stage("enclosure-pipeline").output_path
    firmware_out = config.lane_plan.stage("firmware-pipeline").output_path
    if board_out is None or enclosure_out is None or firmware_out is None:
        return stage_failure(
            "projection-docs",
            "board, enclosure, or firmware output path is undeclared (fail-closed)",
            record_class="L3",
        )
    output = config.out_root / "docs"
    try:
        result = run_projection_docs(
            config.repository,
            graph_path=config.fixture_dir / "graph.json",
            out_root=config.out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            previous_graph_path=config.previous_graph_path,
            languages=config.document_languages,
        )
    except ProjectionDocsError as exc:
        fields: dict[str, Any] = {"record_class": "L3"}
        if exc.output_path is not None:
            fields["output_path"] = str(exc.output_path)
        return stage_failure(
            "projection-docs",
            str(exc),
            next_step_action=(
                "fix the graph declarations or pin projection the document "
                "generator reported; documents are L3 and never grant approval"
            ),
            **fields,
        )
    return stage_success(
        "projection-docs",
        record_class="L3",
        output_path=str(result.output_path),
        documents=[document.as_dict() for document in result.documents],
        hashes_path=str(result.hashes_path),
        provenance=result.provenance,
    )


def _run_manufacturing_submission(config: DesignLoopConfig) -> dict[str, Any]:
    board_out = config.lane_plan.stage("board-pipeline").output_path
    enclosure_out = config.lane_plan.stage("enclosure-pipeline").output_path
    output = config.lane_plan.stage("manufacturing-submission").output_path
    if board_out is None or enclosure_out is None or output is None:
        return stage_failure(
            "manufacturing-submission",
            "manufacturing submission output path is undeclared (fail-closed)",
            record_class="L3",
            authoritative=False,
        )
    try:
        verdict = evaluate_manufacturing_submission(
            board_dir=board_out,
            enclosure_dir=enclosure_out,
            graph_path=config.fixture_dir / "graph.json",
            require_authoritative=False,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            verdict.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    except ManufacturingSubmissionError as exc:
        return stage_failure(
            "manufacturing-submission",
            str(exc),
            record_class="L3",
            authoritative=False,
            verdict_path=str(output),
            require_authoritative=False,
        )
    fields = {
        "record_class": "L3",
        "authoritative": False,
        "verdict_path": str(output),
        "status": verdict.status,
        "require_authoritative": False,
        "checks": [
            {"check_id": check.check_id, "status": check.status} for check in verdict.checks
        ],
    }
    if verdict.status == "pass":
        return stage_success("manufacturing-submission", **fields)
    failed = [
        f"{check.check_id}: {check.detail}" for check in verdict.checks if check.status == "fail"
    ]
    return stage_failure(
        "manufacturing-submission",
        "manufacturing submission verdict is 'fail': " + "; ".join(failed),
        next_step_action=(
            "resolve the listed checks in the board/enclosure lanes; the verdict is not adjustable"
        ),
        **fields,
    )


def order_readiness_not_executed(config: DesignLoopConfig) -> dict[str, Any]:
    """Record that order readiness was never executed in design-only mode.

    Design-only mode iterates the design stages without any order path. The
    absence of an executed order gate is a failure, never a pass: no order
    result is synthesized here.
    """
    return stage_failure(
        "order-readiness",
        "order readiness was not executed in design-only mode",
        execution_status="not_executed",
        order_readiness_status="not_executed",
        design_only=True,
    )


def _run_order_readiness(config: DesignLoopConfig) -> dict[str, Any]:
    if config.order_total is None:
        return stage_failure(
            "order-readiness",
            "order-total document is undeclared (fail-closed)",
            execution_status="not_executed",
            order_readiness_status="not_executed",
        )
    try:
        policy_path = (
            config.policy if config.policy.is_absolute() else config.repository / config.policy
        )
        order_total_path = (
            config.order_total
            if config.order_total.is_absolute()
            else config.repository / config.order_total
        )
        policy = OrderPolicy.model_validate_json(policy_path.read_text(encoding="utf-8"))
        order_total = order_total_result_from_document(
            OrderTotalDocument.model_validate_json(order_total_path.read_text(encoding="utf-8"))
        )
        record = evaluate_pre_order_gate(
            repository=config.repository,
            policy=policy,
            design_graph_path=config.fixture_dir / "graph.json",
            order_total=order_total,
            evidence_paths=sorted(config.repository.glob(policy.evidence_paths)),
            evaluated_at=config.evaluated_at,
        )
    except Exception as exc:
        return stage_failure("order-readiness", str(exc))
    return stage_success(
        "order-readiness",
        summary=record.model_dump(mode="json"),
        output_path=None,
    )


def run_order_total_aggregation(config: DesignLoopConfig) -> dict[str, Any]:
    """Aggregate caller-provided quote paths without producing readiness evidence."""
    output_path = config.lane_plan.stage("order-total-aggregation").output_path
    if output_path is None:
        return stage_failure(
            "order-total-aggregation",
            "order-total aggregation output path is undeclared (fail-closed)",
            record_class="L2",
        )
    if not config.quote_records or config.order_scope is None:
        return stage_failure(
            "order-total-aggregation",
            "quote records and order scope are required for aggregation",
            record_class="L2",
        )
    if config.fab_profile is None:
        return stage_failure(
            "order-total-aggregation",
            "fab profile is required for aggregation",
            record_class="L2",
        )
    try:
        records = [
            QuoteRecord.model_validate_json(quote_path.read_text(encoding="utf-8"))
            for quote_path in config.quote_records
        ]
        scope = OrderScope.model_validate_json(config.order_scope.read_text(encoding="utf-8"))
        fab_profile = FabProfileDocument.model_validate_json(
            config.fab_profile.read_text(encoding="utf-8")
        )
        graph = load_graph(config.fixture_dir)
        result = aggregate_order_total(
            records,
            scope,
            fab_profile=fab_profile,
            evaluated_at=config.evaluated_at,
            target_revision=graph.revision,
        )
        document = order_total_result_to_document(result)
        output_path.parent.mkdir(parents=True, exist_ok=True)
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
    except Exception as exc:
        return stage_failure(
            "order-total-aggregation",
            f"{type(exc).__name__}: {exc}",
            record_class="L2",
            output_path=str(output_path),
        )
    return stage_success(
        "order-total-aggregation",
        record_class="L2",
        output_path=str(output_path),
        quote_count=len(records),
        target_revision=result.target_revision,
        evaluated_at=config.evaluated_at.isoformat(),
        breakdown_hash=result.breakdown_hash,
    )


def run_fixture_generation(config: DesignLoopConfig) -> dict[str, Any]:
    if config.fixture_spec is None:
        raise ValueError("fixture spec is not configured")
    graph_path = config.fixture_dir / "graph.json"
    if graph_path.exists() and not config.fixture_overwrite:
        return stage_failure(
            "fixture-generation",
            "fixture directory already contains graph.json (fail-closed); "
            "declare an explicit overwrite to regenerate it",
        )
    try:
        spec = DesignFixtureSpec.model_validate_json(
            config.fixture_spec.read_text(encoding="utf-8")
        )
        graph = build_design_fixture(
            spec,
            config.fixture_dir,
            overwrite=config.fixture_overwrite,
            spec_dir=config.fixture_spec.parent,
            cpl_evidence_dir=config.cpl_evidence_dir,
        )
    except Exception as exc:
        return stage_failure("fixture-generation", f"{type(exc).__name__}: {exc}")
    # Diagnostic only: the fixture was written, and the loop entry preflight
    # decides whether the lanes may run. Reporting the gaps here lets a design
    # input be completed without waiting for that stop.
    preflight = run_lane_preflight(
        graph,
        _preflight_lanes(),
        root=config.repository,
        evidence_root=(
            config.fixture_dir if (config.fixture_dir / "evidence").is_dir() else config.repository
        ),
    )
    diagnostics: dict[str, Any] = {"lane_preflight_status": preflight.status}
    diagnostics["producer_gaps"] = [
        item.model_dump(mode="json") for item in preflight.producer_gaps
    ]
    diagnostics.update(_firmware_coverage_diagnostics(preflight))
    if preflight.status != "declarations_complete":
        diagnostics["missing_declarations"] = [
            item.model_dump(mode="json") for item in missing_declarations(preflight)
        ]
        diagnostics["next_step_action"] = missing_declaration_action(preflight)
    return stage_success(
        "fixture-generation",
        graph_id=graph.graph_id,
        revision=graph.revision,
        overwrite=config.fixture_overwrite,
        output_path=str(config.fixture_dir),
        **diagnostics,
    )


def _preflight_lanes() -> tuple[str, ...]:
    return tuple(
        lane for lane in ("silkscreen-resolve", *DESIGN_LOOP_LANE_IDS) if lane in LANE_REQUIREMENTS
    )


def _firmware_coverage_diagnostics(
    report: LanePreflightReport,
) -> dict[str, Any]:
    """Surface a non-pass firmware coverage verdict next to the declarations.

    The entry stays diagnostic: a ``fail`` or ``unknown`` coverage status is
    reported so the design input can be fixed early, but it does not change
    the preflight's own declarations status.
    """
    for lane in report.lanes:
        if lane.lane != "firmware-pipeline" or lane.firmware_coverage is None:
            continue
        if lane.firmware_coverage.get("status") != "pass":
            return {"firmware_coverage": lane.firmware_coverage}
    return {}


def run_lane_preflight_stage(config: DesignLoopConfig) -> dict[str, Any]:
    """Stop before the gates when a planned lane lacks declarations.

    The preflight is an L3 diagnostic: `declarations_complete` only lets the
    gates run; it never stands in for a gate verdict. An incomplete result fails
    closed and names the declarations the design input has to add; nothing is
    auto-completed.
    """
    output_path = config.lane_plan.stage("lane-preflight").output_path
    try:
        graph = load_graph(config.fixture_dir)
        report = run_lane_preflight(
            graph,
            _preflight_lanes(),
            root=config.repository,
            evidence_root=(
                config.fixture_dir
                if (config.fixture_dir / "evidence").is_dir()
                else config.repository
            ),
        )
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return stage_failure(
            "lane-preflight",
            f"{type(exc).__name__}: {exc}",
            record_class="L3",
        )
    fields: dict[str, Any] = {
        "record_class": "L3",
        "diagnostic_only": True,
        "graph_id": graph.graph_id,
        "revision": graph.revision,
        "preflight_status": report.status,
        "preflight_lanes": list(_preflight_lanes()),
        "producer_gaps": [item.model_dump(mode="json") for item in report.producer_gaps],
        "output_path": str(output_path) if output_path is not None else None,
        **_firmware_coverage_diagnostics(report),
    }
    if report.status == "declarations_complete":
        return stage_success("lane-preflight", **fields)
    action = missing_declaration_action(report)
    return stage_failure(
        "lane-preflight",
        "lane declarations are missing or unsupported (fail-closed); see next_step_action",
        missing_declarations=[
            item.model_dump(mode="json") for item in missing_declarations(report)
        ],
        unsupported_values=[
            item.model_dump(mode="json")
            for lane in report.lanes
            for item in lane.unsupported_values
        ],
        next_step_action=action,
        **fields,
    )


def run_requirement_compile(config: DesignLoopConfig) -> dict[str, Any]:
    if config.requirement is None:
        raise ValueError("requirement update is not configured")
    try:
        before_graph = load_graph(config.fixture_dir)
        compilation = compile_requirement_change(
            config.fixture_dir,
            config.requirement,
            dry_run=False,
        )
        after_graph = load_graph(config.fixture_dir)
    except Exception as exc:
        return stage_failure(
            "requirement-compile",
            f"{type(exc).__name__}: {exc}",
            record_class="L2",
        )
    if after_graph.graph_id != before_graph.graph_id:
        return stage_failure(
            "requirement-compile",
            "compiled graph ID changed (fail-closed)",
            record_class="L2",
            before_graph_sha256=canonical_json_sha256(before_graph.model_dump(mode="json")),
            after_graph_sha256=canonical_json_sha256(after_graph.model_dump(mode="json")),
        )
    report = dict(compilation.report)
    report.update(
        {
            "stage_id": "requirement-compile",
            "ok": True,
            "fail_closed": False,
            "pass_evidence": False,
            "record_class": "L2",
        }
    )
    return report


def run_requirement_entry_validation_stage(config: DesignLoopConfig) -> dict[str, Any]:
    """Validate loop inputs before L1 stages; never replace gates or Evidence."""
    requirements_path = default_requirements_path(config.fixture_dir)
    try:
        loaded = load_requirements(requirements_path)
        graph = load_graph(config.fixture_dir)
        validate_requirements(loaded.document, graph)
    except Exception as exc:
        return stage_failure(
            "requirement-entry-validation",
            f"{type(exc).__name__}: {exc}",
            requirements_path=str(requirements_path),
        )
    return stage_success(
        "requirement-entry-validation",
        requirements_path=str(requirements_path),
        requirements_sha256=loaded.document_hash,
        graph_id=graph.graph_id,
        revision=graph.revision,
        requirement_count=len(loaded.document.records),
    )


DEFAULT_STAGE_RUNNERS: dict[str, StageRunner] = {
    "requirement-entry-validation": run_requirement_entry_validation_stage,
    "lane-preflight": run_lane_preflight_stage,
    "silkscreen-resolve": _run_silkscreen,
    "board-pipeline": run_board_stage,
    "enclosure-pipeline": _run_enclosure,
    "firmware-pipeline": _run_firmware,
    "graph-diff-projection": _run_graph_diff_projection,
    "visual-review-manifest": _run_visual_review_manifest,
    "projection-docs": _run_projection_docs,
    "manufacturing-submission": _run_manufacturing_submission,
    "order-readiness": _run_order_readiness,
}
