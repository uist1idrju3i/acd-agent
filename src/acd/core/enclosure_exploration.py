"""Bounded, deterministic enclosure interference exploration."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.adapters.cad.mechanical import MechanicalGateError
from acd.core.design_freedom import (
    DesignFreedomDeclaration,
    design_freedom_dimension,
    load_design_freedom_declaration,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode

ENCLOSURE_EXPLORATION_ARTIFACT_KIND = "enclosure_exploration_report"
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_JOBS = 1
DEFAULT_SAMPLING_POINTS = 3
_DIMENSION_ATTRS: dict[str, str] = {
    "enclosure_wall_thickness_mm": "wall_thickness_mm",
    "enclosure_internal_clearance_mm": "internal_clearance_mm",
    "enclosure_standoff_height_mm": "standoff_height_mm",
    "enclosure_standoff_radius_mm": "standoff_radius_mm",
}
_DEFAULT_PIPELINE_LOCK = threading.Lock()


class EnclosureExplorationError(ValueError):
    """Raised when an enclosure exploration request cannot be evaluated safely."""


@dataclass(frozen=True)
class EnclosureExplorationCandidate:
    """One immutable enclosure candidate proposal."""

    candidate_id: str
    dimensions: tuple[str, ...]
    changes: dict[str, float]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class EnclosureExplorationResult:
    """Structured enclosure exploration observation and report path."""

    report: dict[str, Any]
    report_path: Path


PipelineRunner = Callable[[Path, Path], object]


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EnclosureExplorationError(
            f"graph is invalid or unreadable: {path}: {exc}"
        ) from exc


def _script_hash() -> str:
    path = Path(__file__).resolve()
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise EnclosureExplorationError(f"cannot hash exploration script: {path}") from exc


def _write_json(path: Path, body: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _enclosure_node(graph: DesignGraph) -> GraphNode:
    nodes = [node for node in graph.nodes if node.kind == "mechanical.enclosure"]
    if len(nodes) != 1:
        raise EnclosureExplorationError(
            "graph must contain exactly one mechanical.enclosure node"
        )
    return nodes[0]


def _numeric_attr(node: GraphNode, attr: str) -> float:
    value = node.attrs.get(attr)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EnclosureExplorationError(
            f"{node.id}: attr {attr!r} is missing or not numeric"
        )
    return float(value)


def validate_enclosure_dimensions(
    dimensions: Sequence[str],
    declaration: DesignFreedomDeclaration | None = None,
) -> tuple[str, ...]:
    """Validate requested dimensions against searchable mechanical declarations."""
    loaded = declaration or load_design_freedom_declaration()
    requested = tuple(sorted(set(dimensions)))
    declared = {item.dimension_id: item for item in loaded.dimensions}
    unknown = sorted(set(requested) - set(declared))
    if unknown:
        raise EnclosureExplorationError(
            "candidate references unknown change dimensions: " + ", ".join(unknown)
        )
    non_mechanical = sorted(
        dimension for dimension in requested if declared[dimension].lane != "mechanical"
    )
    if non_mechanical:
        raise EnclosureExplorationError(
            "candidate references non-mechanical change dimensions: "
            + ", ".join(non_mechanical)
        )
    disabled = sorted(
        dimension for dimension in requested if not declared[dimension].search_enabled
    )
    if disabled:
        raise EnclosureExplorationError(
            "candidate references non-explorable change dimensions: "
            + ", ".join(disabled)
        )
    unsupported = sorted(set(requested) - set(_DIMENSION_ATTRS))
    if unsupported:
        raise EnclosureExplorationError(
            "searchable mechanical dimensions have no graph attribute mapping: "
            + ", ".join(unsupported)
        )
    return requested


def _candidate_values(
    node: GraphNode,
    dimension_id: str,
    declaration: DesignFreedomDeclaration,
    sampling_points: int,
) -> tuple[float, ...]:
    if sampling_points < 2:
        raise EnclosureExplorationError("sampling_points must be at least 2")
    dimension = design_freedom_dimension(dimension_id, declaration)
    if dimension.minimum is None or dimension.maximum is None:
        raise EnclosureExplorationError(
            f"{dimension_id}: searchable dimension must declare minimum and maximum"
        )
    attr = _DIMENSION_ATTRS[dimension_id]
    current_value = _numeric_attr(node, attr)
    minimum = float(dimension.minimum)
    maximum = float(dimension.maximum)
    if current_value < minimum or current_value > maximum:
        raise EnclosureExplorationError(
            f"{dimension_id}: graph value is outside declared bounds"
        )
    step = (maximum - minimum) / (sampling_points - 1)
    values = {minimum + step * index for index in range(sampling_points)}
    values.add(current_value)
    return tuple(sorted(values))


def enumerate_enclosure_candidates(
    graph: DesignGraph,
    dimensions: Sequence[str] | None = None,
    declaration: DesignFreedomDeclaration | None = None,
    *,
    sampling_points: int = DEFAULT_SAMPLING_POINTS,
) -> tuple[EnclosureExplorationCandidate, ...]:
    """Enumerate bounded values by minimum current-value change.

    For every selected dimension, the boundary values, current graph value, and
    ``sampling_points`` equally spaced values including both boundaries are
    considered. The current value is omitted as a no-op. Candidates are sorted
    by absolute deviation from the current value, then value and dimension ID.
    """
    loaded = declaration or load_design_freedom_declaration()
    selected = validate_enclosure_dimensions(
        dimensions
        if dimensions is not None
        else tuple(
            item.dimension_id
            for item in loaded.dimensions
            if item.lane == "mechanical" and item.search_enabled
        ),
        loaded,
    )
    if not selected:
        raise EnclosureExplorationError(
            "no searchable mechanical enclosure dimensions are declared"
        )
    node = _enclosure_node(graph)
    pending: list[tuple[str, float]] = []
    current_values: dict[str, float] = {}
    for dimension_id in selected:
        attr = _DIMENSION_ATTRS.get(dimension_id)
        if attr is None:
            raise EnclosureExplorationError(
                f"{dimension_id}: searchable mechanical dimension has no graph "
                "attribute mapping"
            )
        current_values[dimension_id] = _numeric_attr(node, attr)
        pending.extend(
            (dimension_id, value)
            for value in _candidate_values(
                node,
                dimension_id,
                loaded,
                sampling_points,
            )
        )
    pending.sort(
        key=lambda item: (
            abs(item[1] - current_values[item[0]]),
            item[1],
            item[0],
        )
    )
    candidates: list[EnclosureExplorationCandidate] = []
    ordinal = 1
    for dimension_id, value in pending:
        if current_values[dimension_id] == value:
            continue
        candidates.append(
            EnclosureExplorationCandidate(
                candidate_id=f"enclosure-{ordinal:04d}",
                dimensions=(dimension_id,),
                changes={dimension_id: value},
                provenance={
                    "declaration_id": loaded.declaration_id,
                    "declaration_hash": loaded.declaration_hash,
                    "graph_revision": graph.revision,
                    "script_name": "src/acd/core/enclosure_exploration.py",
                    "script_sha256": _script_hash(),
                    "pass_evidence": False,
                },
            )
        )
        ordinal += 1
    return tuple(candidates)


def _replace_node_attrs(
    graph: DesignGraph,
    node_id: str,
    updates: Mapping[str, AttrValue],
) -> DesignGraph:
    nodes = [
        node.model_copy(update={"attrs": {**node.attrs, **updates}})
        if node.id == node_id
        else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def _apply_candidate(
    graph: DesignGraph,
    candidate: EnclosureExplorationCandidate,
) -> DesignGraph:
    node = _enclosure_node(graph)
    updates: dict[str, AttrValue] = {
        _DIMENSION_ATTRS[dimension_id]: value
        for dimension_id, value in candidate.changes.items()
    }
    return _replace_node_attrs(graph, node.id, updates)


def _copy_graph(path: Path, graph: DesignGraph) -> None:
    path.write_text(graph.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _evaluate_candidate(
    candidate: EnclosureExplorationCandidate,
    graph: DesignGraph,
    source_fixture: Path,
    candidate_out: Path,
    temporary_root: Path,
    pipeline_runner: PipelineRunner,
    pipeline_lock: threading.Lock | None = None,
) -> dict[str, Any]:
    working_fixture = temporary_root / candidate.candidate_id
    shutil.copytree(source_fixture, working_fixture)
    _copy_graph(working_fixture / "graph.json", _apply_candidate(graph, candidate))
    try:
        if pipeline_lock is None:
            pipeline_result = pipeline_runner(working_fixture, candidate_out)
        else:
            with pipeline_lock:
                pipeline_result = pipeline_runner(working_fixture, candidate_out)
    except MechanicalGateError as exc:
        return {
            "status": "gate_rejected",
            "reasons": [str(exc)],
            "pass_evidence": False,
        }
    except Exception as exc:
        return {
            "status": "stopped",
            "reasons": [f"pipeline execution failed (fail-closed): {exc}"],
            "pass_evidence": False,
        }
    finally:
        (candidate_out / "evidence-mechanical.json").unlink(missing_ok=True)
    outcome: dict[str, Any] = {
        "status": "candidate_survived_gates",
        "reasons": [],
        "pass_evidence": False,
    }
    if isinstance(pipeline_result, Mapping):
        outcome["gate_result"] = {
            key: pipeline_result[key]
            for key in (
                "authoritative",
                "measured_max_interference_volume_mm3",
                "measured_min_wall_mm",
                "measured_min_clearance_mm",
            )
            if key in pipeline_result
        }
    return outcome


def explore_enclosure_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    max_candidates: int,
    *,
    dimensions: Sequence[str] | None = None,
    jobs: int = DEFAULT_JOBS,
    pipeline_runner: PipelineRunner | None = None,
    sampling_points: int = DEFAULT_SAMPLING_POINTS,
) -> EnclosureExplorationResult:
    """Explore bounded enclosure candidates without granting pass authority."""
    if max_candidates < 1:
        raise EnclosureExplorationError("max_candidates must be positive")
    if jobs < 1:
        raise EnclosureExplorationError("jobs must be positive")
    graph = _load_graph(graph_path)
    if not fixture_dir.is_dir():
        raise EnclosureExplorationError(f"fixture directory is missing: {fixture_dir}")
    declaration = load_design_freedom_declaration()
    candidates = enumerate_enclosure_candidates(
        graph,
        dimensions,
        declaration,
        sampling_points=sampling_points,
    )
    pending = candidates[:max_candidates]
    pipeline_lock: threading.Lock | None = None
    if pipeline_runner is None:
        from acd.pipeline.gd1_enclosure import run_pipeline

        pipeline_runner = run_pipeline
        pipeline_lock = _DEFAULT_PIPELINE_LOCK
    source_fixture = fixture_dir.resolve()
    candidate_out_root = out_dir / "candidates"

    def evaluate(candidate: EnclosureExplorationCandidate) -> dict[str, Any]:
        return _evaluate_candidate(
            candidate,
            graph,
            source_fixture,
            candidate_out_root / candidate.candidate_id,
            temporary_root,
            pipeline_runner,
            pipeline_lock,
        )

    with tempfile.TemporaryDirectory(prefix="acd-enclosure-exploration-") as temporary:
        temporary_root = Path(temporary)
        if jobs == 1:
            outcomes = [evaluate(candidate) for candidate in pending]
        else:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                outcomes = list(executor.map(evaluate, pending))
    records: list[dict[str, Any]] = []
    winner: str | None = None
    for candidate, outcome in zip(pending, outcomes, strict=True):
        record = {
            "candidate_id": candidate.candidate_id,
            "dimensions": list(candidate.dimensions),
            "changes": candidate.changes,
            "declaration_id": declaration.declaration_id,
            "declaration_hash": declaration.declaration_hash,
            "pass_evidence": False,
            "provenance": candidate.provenance,
            "outcome": outcome,
        }
        records.append(record)
        if outcome["status"] == "candidate_survived_gates" and winner is None:
            winner = candidate.candidate_id
    stopped = any(record["outcome"]["status"] == "stopped" for record in records)
    if stopped:
        winner = None
    status = "stopped" if stopped else "candidate_found" if winner else "exhausted"
    report = {
        "schema_version": "0.1",
        "artifact_kind": ENCLOSURE_EXPLORATION_ARTIFACT_KIND,
        "status": status,
        "termination_reason": {
            "candidate_found": "candidate_survived_gates",
            "exhausted": "candidate_budget_exhausted",
            "stopped": "fail_closed_stop",
        }[status],
        "pass_evidence": False,
        "record_class": "L2",
        "l2_statement": "This is an L2 candidate exploration record, not gate Evidence.",
        "authority_statement": "L1 deterministic mechanical gates retain sole authority.",
        "target_revision": graph.revision,
        "max_candidates": max_candidates,
        "evaluated_candidates": len(records),
        "winner_candidate_id": winner,
        "winner_written": False,
        "candidates": records,
        "provenance": {
            "source_graph": str(graph_path.resolve()),
            "source_fixture": str(source_fixture),
            "declaration_id": declaration.declaration_id,
            "declaration_hash": declaration.declaration_hash,
            "l1_authority": "deterministic mechanical pipeline gates",
            "note": "L2 exploration observation; pass_evidence is always false.",
        },
    }
    report["content_sha256"] = canonical_json_sha256(report)
    report_path = out_dir / "enclosure-exploration-report.json"
    _write_json(report_path, report)
    return EnclosureExplorationResult(report=report, report_path=report_path)


__all__ = [
    "DEFAULT_JOBS",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_SAMPLING_POINTS",
    "ENCLOSURE_EXPLORATION_ARTIFACT_KIND",
    "EnclosureExplorationCandidate",
    "EnclosureExplorationError",
    "EnclosureExplorationResult",
    "enumerate_enclosure_candidates",
    "explore_enclosure_candidates",
    "validate_enclosure_dimensions",
]
