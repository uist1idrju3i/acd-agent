"""Bounded, deterministic design-candidate exploration.

Exploration is an L2 steering mechanism. Candidate reports and exploration
reports are observations only; deterministic pipeline gates remain the sole
authority for accepting a design.
"""
# pyright: reportUnknownVariableType=false,reportUnknownMemberType=false,reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.candidate_commit import CandidateCommitError, commit_candidate_graph
from acd.core.decoupling_placement import (
    DecouplingPlacementError,
    solve_decoupling_placements,
)
from acd.core.design_freedom import load_design_freedom_declaration
from acd.core.design_predicates import evaluate_design_predicates, evaluate_strapping_pin
from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph, GraphNode

EXPLORATION_ARTIFACT_KIND = "board_exploration_report"
FIRMWARE_EXPLORATION_ARTIFACT_KIND = "firmware_exploration_report"
DECOUPLING_SOLVER_NAME = "acd-core-deterministic-decoupling"
PLACEMENT_SKILL_NAME = "acd-placement-search"
PLACEMENT_SCRIPT = (
    "plugins/acd/skills/acd-placement-search/scripts/placement_search.py"
)
SEARCHABLE_DIMENSIONS = frozenset(
    {
        "component_placement_xy",
        "component_rotation_deg",
        "gpio_assignment",
    }
)


class ExplorationError(ValueError):
    """Raised when an exploration request cannot be evaluated safely."""


@dataclass(frozen=True)
class ExplorationCandidate:
    """One immutable candidate proposal before deterministic gate evaluation."""

    candidate_id: str
    kind: str
    dimensions: tuple[str, ...]
    changes: dict[str, Any]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class RemediationRequest:
    """One declared remediation request extracted from a rejected predicate."""

    predicate: str
    change_dimensions: tuple[str, ...]
    refdes: str | None = None
    target_refdes: str | None = None
    net: str | None = None


@dataclass(frozen=True)
class ExplorationResult:
    """Structured exploration observation and its report path."""

    report: dict[str, Any]
    report_path: Path


PipelineRunner = Callable[[Path, Path], object]


def _sha256(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise ExplorationError(f"cannot hash exploration input: {path}: {exc}") from exc


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExplorationError(f"graph is invalid or unreadable: {path}: {exc}") from exc


def _write_json(path: Path, body: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _report_with_hash(body: dict[str, Any]) -> dict[str, Any]:
    report = dict(body)
    report["content_sha256"] = canonical_json_sha256(report)
    return report


def _validate_dimensions(
    dimensions: Sequence[str],
    declaration_dimensions: Mapping[str, bool],
) -> tuple[str, ...]:
    unknown = sorted(set(dimensions) - set(declaration_dimensions))
    if unknown:
        raise ExplorationError(
            "candidate references unknown change dimensions: " + ", ".join(unknown)
        )
    disabled = sorted(
        dimension for dimension in dimensions if not declaration_dimensions[dimension]
    )
    if disabled:
        raise ExplorationError(
            "candidate references non-explorable change dimensions: "
            + ", ".join(disabled)
        )
    unsupported = sorted(set(dimensions) - SEARCHABLE_DIMENSIONS)
    if unsupported:
        raise ExplorationError(
            "candidate references unsupported change dimensions: "
            + ", ".join(unsupported)
        )
    return tuple(sorted(set(dimensions)))


def validate_candidate_dimensions(
    dimensions: Sequence[str],
) -> tuple[str, ...]:
    """Validate candidate dimensions against the current freedom declaration."""
    declaration = load_design_freedom_declaration()
    return _validate_dimensions(
        dimensions,
        {item.dimension_id: item.search_enabled for item in declaration.dimensions},
    )


def _placement_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    graph: DesignGraph,
) -> tuple[ExplorationCandidate, ...]:
    root = repository_root()
    script = root / PLACEMENT_SCRIPT
    if not script.is_file():
        raise ExplorationError(f"placement skill script is missing: {script}")
    profile_id: str | None = None
    for node in graph.nodes:
        if node.kind == "fab.order_intent":
            value = node.attrs.get("fab_profile")
            if isinstance(value, str):
                profile_id = value
                break
    if profile_id is None:
        raise ExplorationError("graph does not declare a fab profile")
    from acd.core.fab import load_fab_profile_registry, resolve_fab_profile_path

    profile = resolve_fab_profile_path(profile_id, load_fab_profile_registry())
    skill_output = out_dir / "skill" / "placements.json"
    command = (
        "uv",
        "run",
        "--script",
        str(script),
        "--input",
        str(graph_path),
        "--fixture-dir",
        str(fixture_dir),
        "--fab-profile",
        str(profile),
        "--output",
        str(skill_output),
    )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ExplorationError(f"placement skill could not start: {exc}") from exc
    if completed.returncode != 0:
        raise ExplorationError(
            "placement skill failed (fail-closed): "
            + (completed.stderr.strip() or f"exit {completed.returncode}")
        )
    try:
        payload = json.loads(skill_output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplorationError(f"placement skill output is invalid: {exc}") from exc
    if not isinstance(payload, list):
        raise ExplorationError("placement skill output must be an array (fail-closed)")
    refs = {
        str(node.attrs["refdes"])
        for node in graph.nodes
        if node.kind == "electrical.component" and "refdes" in node.attrs
    }
    placements: dict[str, dict[str, float]] = {}
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise ExplorationError("placement candidate must be an object (fail-closed)")
        refdes = item.get("refdes")
        values = {key: item.get(key) for key in ("x_mm", "y_mm", "rotation_deg")}
        if (
            not isinstance(refdes, str)
            or refdes not in refs
            or any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
                for value in values.values()
            )
        ):
            raise ExplorationError("placement candidate has malformed fields (fail-closed)")
        if refdes in placements:
            raise ExplorationError(f"duplicate placement for {refdes!r} (fail-closed)")
        placements[refdes] = {
            key: float(cast(int | float, value)) for key, value in values.items()
        }
    if set(placements) != refs:
        raise ExplorationError("placement skill omitted one or more components (fail-closed)")
    graph_revision = graph.revision
    provenance = {
        "skill_name": PLACEMENT_SKILL_NAME,
        "script_name": PLACEMENT_SCRIPT,
        "script_sha256": _sha256(script),
        "proposal_sha256": _sha256(skill_output),
        "graph_revision": graph_revision,
        "pass_evidence": False,
    }
    return (
        ExplorationCandidate(
            candidate_id="placement-0001",
            kind="placement",
            dimensions=("component_placement_xy", "component_rotation_deg"),
            changes={"placements": placements},
            provenance=provenance,
        ),
    )


def _u1_gpio_pads(graph: DesignGraph, lane: ElectricalLane) -> dict[int, str]:
    component = next((item for item in lane.components if item.refdes == "U1"), None)
    if component is None:
        raise ExplorationError("GPIO solver requires graph-declared U1 (fail-closed)")
    pins = {pin.pad for pin in lane.pins_of_component(component.node_id)}
    result: dict[int, str] = {}
    function_pads = {
        function: pad for pad, function in component.cpl_rotation_pin_functions.items()
    }
    for pad, function in component.cpl_rotation_pin_functions.items():
        if pad not in pins:
            continue
        if function.upper().startswith("IO") and function[2:].isdigit():
            result[int(function[2:])] = pad
    for alias, function in component.cpl_rotation_pin_aliases.items():
        prefix = alias.split("/", 1)[0]
        if not prefix.upper().startswith("GPIO") or not prefix[4:].isdigit():
            continue
        pad = function_pads.get(function)
        if pad in pins:
            result[int(prefix[4:])] = pad
    if not result:
        raise ExplorationError("graph declares no MCU GPIO pads (fail-closed)")
    return result


def _replace_node_attrs(
    graph: DesignGraph,
    updates: Mapping[str, Mapping[str, Any]],
) -> DesignGraph:
    nodes: list[GraphNode] = []
    for node in graph.nodes:
        values = updates.get(node.id)
        nodes.append(
            node.model_copy(update={"attrs": {**node.attrs, **values}})
            if values is not None
            else node
        )
    return graph.model_copy(update={"nodes": nodes})


def _gpio_candidate_graph(
    graph: DesignGraph,
    lane: ElectricalLane,
    node_id: str,
    target_gpio: int,
    gpio_pads: Mapping[int, str],
) -> tuple[DesignGraph, dict[str, Any]]:
    node = graph.node_by_id(node_id)
    net = node.attrs.get("net")
    current_gpio = node.attrs.get("gpio")
    if (
        not isinstance(net, str)
        or isinstance(current_gpio, bool)
        or not isinstance(current_gpio, int)
        or current_gpio not in gpio_pads
        or target_gpio not in gpio_pads
    ):
        raise ExplorationError(f"{node_id}: malformed GPIO assignment (fail-closed)")
    old_pad = gpio_pads[current_gpio]
    target_pad = gpio_pads[target_gpio]
    if target_pad == old_pad:
        raise ExplorationError(f"{node_id}: GPIO candidate is not an alternative")
    u1 = next(item for item in lane.components if item.refdes == "U1")
    old_pin = next((pin for pin in lane.pins_of_component(u1.node_id) if pin.pad == old_pad), None)
    target_pin = next(
        (pin for pin in lane.pins_of_component(u1.node_id) if pin.pad == target_pad), None
    )
    if old_pin is None or target_pin is None:
        raise ExplorationError(f"{node_id}: graph MCU pad declaration is incomplete")
    if target_pin.net_id is not None:
        return graph, {}
    updated = _replace_node_attrs(
        graph,
        {
            node_id: {"gpio": target_gpio},
            old_pin.node_id: {"net": None, "no_connect": True},
            target_pin.node_id: {"net": net, "no_connect": False},
        },
    )
    nodes = [
        item.model_copy(
            update={
                "depends_on": (
                    [u1.node_id]
                    if item.id == old_pin.node_id
                    else [u1.node_id, net]
                )
            }
        )
        if item.id in {old_pin.node_id, target_pin.node_id}
        else item
        for item in updated.nodes
    ]
    return (
        updated.model_copy(update={"nodes": nodes}),
        {
            node_id: {"gpio": target_gpio, "from_pad": old_pad, "to_pad": target_pad},
            old_pin.node_id: {"from_pad": old_pad},
            target_pin.node_id: {"to_pad": target_pad, "net": net},
        },
    )


def enumerate_gpio_assignment_candidates(
    graph: DesignGraph,
) -> tuple[ExplorationCandidate, ...]:
    """Enumerate free-MCU-pad assignments in stable node/GPIO order."""
    lane = extract_electrical_lane(graph)
    gpio_pads = _u1_gpio_pads(graph, lane)
    declarations = load_design_freedom_declaration()
    dimension_map = {item.dimension_id: item.search_enabled for item in declarations.dimensions}
    _validate_dimensions(("gpio_assignment",), dimension_map)
    candidates: list[ExplorationCandidate] = []
    ordinal = 1
    for node in sorted(
        (item for item in graph.nodes if item.kind == "firmware.pin_assignment"),
        key=lambda item: item.id,
    ):
        current = node.attrs.get("gpio")
        if isinstance(current, bool) or not isinstance(current, int):
            raise ExplorationError(f"{node.id}: GPIO is malformed (fail-closed)")
        for target_gpio in sorted(gpio_pads):
            if target_gpio == current:
                continue
            updated, change = _gpio_candidate_graph(
                graph, lane, node.id, target_gpio, gpio_pads
            )
            if not change:
                continue
            updated_lane = extract_electrical_lane(updated)
            strapping = evaluate_strapping_pin(updated, updated_lane)
            if strapping.status != "pass":
                continue
            candidates.append(
                ExplorationCandidate(
                    candidate_id=f"gpio-{ordinal:04d}",
                    kind="gpio_assignment",
                    dimensions=("gpio_assignment",),
                    changes=change,
                    provenance={
                        "solver": "acd-core-deterministic-gpio",
                        "script_name": "src/acd/core/exploration.py",
                        "script_sha256": _sha256(repository_root() / "src/acd/core/exploration.py"),
                        "graph_revision": graph.revision,
                        "pass_evidence": False,
                    },
                )
            )
            ordinal += 1
    return tuple(candidates)


def _validated_evidence_payload(
    path: Path, target_revision: str | None
) -> dict[str, Any]:
    """Read hashed structured gate evidence, rejecting unverifiable payloads."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplorationError(f"structured gate evidence is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExplorationError("structured gate evidence is not an object")
    body = cast(dict[str, Any], payload)
    if target_revision is not None and body.get("target_revision") != target_revision:
        raise ExplorationError(
            "structured gate evidence revision does not match the explored graph"
        )
    content_sha256 = body.get("content_sha256")
    if not isinstance(content_sha256, str):
        raise ExplorationError("structured gate evidence content hash is missing")
    unhashed = {key: value for key, value in body.items() if key != "content_sha256"}
    if canonical_json_sha256(unhashed) != content_sha256:
        raise ExplorationError("structured gate evidence content hash is invalid")
    return body


def load_remediation_requests(
    evidence_path: Path, target_revision: str | None = None
) -> tuple[RemediationRequest, ...]:
    """Extract declared remediation requests from hashed predicate evidence.

    Candidate generation is only allowed to act on remediation that a rejected
    deterministic predicate declared. Malformed or revision-mismatched evidence
    is rejected fail-closed instead of being treated as "no remediation".
    """
    if not evidence_path.is_file():
        raise ExplorationError(
            f"structured gate evidence is missing: {evidence_path}"
        )
    payload = _validated_evidence_payload(evidence_path, target_revision)
    if payload.get("gate") != "design_predicates":
        raise ExplorationError(
            "structured gate evidence gate is not design_predicates"
        )
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise ExplorationError("structured gate evidence observation is not an object")
    predicates = cast(dict[str, Any], observation).get("predicates", [])
    if not isinstance(predicates, list):
        raise ExplorationError("structured gate evidence predicates is not an array")
    requests: list[RemediationRequest] = []
    for item in cast(list[object], predicates):
        if not isinstance(item, dict):
            raise ExplorationError("structured gate evidence predicate is not an object")
        predicate = cast(dict[str, Any], item)
        remediation = predicate.get("remediation")
        if not isinstance(remediation, dict):
            continue
        body = cast(dict[str, Any], remediation)
        dimensions = body.get("change_dimensions", [])
        if not isinstance(dimensions, list) or not all(
            isinstance(value, str) for value in cast(list[object], dimensions)
        ):
            raise ExplorationError(
                "structured gate evidence remediation dimensions are malformed"
            )
        subject = body.get("subject")
        subject_body = cast(dict[str, Any], subject) if isinstance(subject, dict) else {}
        name = predicate.get("name")
        requests.append(
            RemediationRequest(
                predicate=name if isinstance(name, str) else "unknown",
                change_dimensions=tuple(
                    sorted(cast(list[str], dimensions))
                ),
                refdes=_optional_str(subject_body.get("refdes")),
                target_refdes=_optional_str(subject_body.get("target_refdes")),
                net=_optional_str(subject_body.get("net")),
            )
        )
    return tuple(requests)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _decoupling_placement_candidates(
    graph: DesignGraph,
    fixture_dir: Path,
    remediation: Sequence[RemediationRequest],
) -> tuple[ExplorationCandidate, ...]:
    """Derive targeted capacitor placements from declared remediation subjects."""
    subjects = {
        request.refdes
        for request in remediation
        if request.refdes is not None
        and "component_placement_xy" in request.change_dimensions
    }
    if not subjects:
        return ()
    try:
        report = solve_decoupling_placements(graph, fixture_dir)
    except (DecouplingPlacementError, OSError, ValueError) as exc:
        raise ExplorationError(
            f"decoupling remediation could not be solved: {exc}"
        ) from exc
    placements = {
        item.refdes: item
        for item in report.placements
        if item.changed and item.refdes in subjects
    }
    if not placements:
        return ()
    return (
        ExplorationCandidate(
            candidate_id="decoupling-0001",
            kind="decoupling_placement",
            dimensions=("component_placement_xy",),
            changes={
                "placements": {
                    refdes: {
                        "x_mm": item.placement_x_mm,
                        "y_mm": item.placement_y_mm,
                        "target_refdes": item.target_refdes,
                        "limit_mm": item.limit_mm,
                    }
                    for refdes, item in sorted(placements.items())
                }
            },
            provenance={
                "solver": DECOUPLING_SOLVER_NAME,
                "script_name": "src/acd/core/decoupling_placement.py",
                "script_sha256": _sha256(
                    repository_root() / "src/acd/core/decoupling_placement.py"
                ),
                "graph_revision": graph.revision,
                "remediation_subjects": sorted(subjects),
                "pass_evidence": False,
            },
        ),
    )


def _remediation_dimensions(
    remediation: Sequence[RemediationRequest],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                dimension
                for request in remediation
                for dimension in request.change_dimensions
            }
            & SEARCHABLE_DIMENSIONS
        )
    )


def _remediation_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    graph: DesignGraph,
    remediation: Sequence[RemediationRequest],
) -> tuple[ExplorationCandidate, ...]:
    """Generate only candidates that a declared remediation dimension supports."""
    dimensions = _remediation_dimensions(remediation)
    candidates: list[ExplorationCandidate] = []
    if "component_placement_xy" in dimensions:
        candidates.extend(
            _decoupling_placement_candidates(graph, fixture_dir, remediation)
        )
        candidates.extend(
            _placement_candidates(graph_path, fixture_dir, out_dir, graph)
        )
    if "gpio_assignment" in dimensions:
        candidates.extend(enumerate_gpio_assignment_candidates(graph))
    return tuple(candidates)


def _apply_candidate(graph: DesignGraph, candidate: ExplorationCandidate) -> DesignGraph:
    if candidate.kind == "decoupling_placement":
        updates: dict[str, dict[str, Any]] = {}
        for node in graph.nodes:
            if node.kind != "electrical.component":
                continue
            placement = candidate.changes["placements"].get(str(node.attrs.get("refdes")))
            if placement is None:
                continue
            updates[node.id] = {
                "placement_x_mm": placement["x_mm"],
                "placement_y_mm": placement["y_mm"],
                "placement_source": DECOUPLING_SOLVER_NAME,
                "placement_source_ref": (
                    f"decoupling_target={placement['target_refdes']};"
                    f"limit_mm={placement['limit_mm']}"
                ),
            }
        if not updates:
            raise ExplorationError(
                "decoupling candidate references unknown components (fail-closed)"
            )
        return _replace_node_attrs(graph, updates)
    if candidate.kind == "placement":
        updates = {}
        for node in graph.nodes:
            if node.kind != "electrical.component":
                continue
            refdes = node.attrs.get("refdes")
            placement = candidate.changes["placements"].get(str(refdes))
            if placement is None:
                raise ExplorationError(f"placement is missing for {refdes!r}")
            updates[node.id] = {
                "placement_x_mm": placement["x_mm"],
                "placement_y_mm": placement["y_mm"],
                "placement_rotation_deg": placement["rotation_deg"],
                "placement_source": PLACEMENT_SKILL_NAME,
                "placement_source_ref": (
                    f"{PLACEMENT_SCRIPT}:{candidate.provenance['script_sha256']}"
                ),
            }
        return _replace_node_attrs(graph, updates)
    if candidate.kind == "gpio_assignment":
        updates = {
            node_id: {
                "gpio": values["gpio"],
            }
            for node_id, values in candidate.changes.items()
            if "gpio" in values
        }
        for node_id, values in candidate.changes.items():
            node = graph.node_by_id(node_id)
            if node.kind != "electrical.pin":
                continue
            if "from_pad" in values:
                updates[node_id] = {"net": None, "no_connect": True}
            elif "to_pad" in values:
                updates[node_id] = {"net": values["net"], "no_connect": False}
        return _replace_node_attrs(graph, updates)
    raise ExplorationError(f"unsupported exploration candidate kind: {candidate.kind!r}")


def _copy_graph_to_working(graph: DesignGraph, path: Path) -> None:
    _write_json(path, graph.model_dump(mode="json"))


def _diagnostic_dimensions(
    path: Path,
    target_revision: str | None = None,
) -> tuple[tuple[str, ...], str | None]:
    if not path.is_file():
        return (), None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (), f"structured gate evidence is malformed: {exc}"
    if not isinstance(payload, dict):
        return (), "structured gate evidence is not an object"
    if target_revision is not None and payload.get("target_revision") != target_revision:
        return (), "structured gate evidence revision does not match candidate"
    if payload.get("gate") != "design_predicates":
        return (), "structured gate evidence gate is not design_predicates"
    content_sha256 = payload.get("content_sha256")
    if not isinstance(content_sha256, str):
        return (), "structured gate evidence content hash is missing"
    unhashed = {key: value for key, value in payload.items() if key != "content_sha256"}
    if canonical_json_sha256(unhashed) != content_sha256:
        return (), "structured gate evidence content hash is invalid"
    dimensions: set[str] = set()
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        return (), "structured gate evidence observation is not an object"
    predicates = observation.get("predicates", [])
    if isinstance(predicates, list):
        for item in predicates:
            if not isinstance(item, dict):
                continue
            remediation = item.get("remediation")
            if isinstance(remediation, dict):
                values = remediation.get("change_dimensions", [])
                if isinstance(values, list):
                    dimensions.update(value for value in values if isinstance(value, str))
    return tuple(sorted(dimensions)), None


def _candidate_outcome(
    candidate: ExplorationCandidate,
    graph: DesignGraph,
    working_fixture: Path,
    candidate_out: Path,
    pipeline_runner: PipelineRunner,
) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
    updated = _apply_candidate(graph, candidate)
    working_graph = working_fixture / "graph.json"
    _copy_graph_to_working(updated, working_graph)
    lane = extract_electrical_lane(updated)
    pre_router = evaluate_design_predicates(updated, lane, working_fixture)
    failed = tuple(
        result
        for result in pre_router
        if result.status not in {"pass", "not_applicable"}
    )
    if failed:
        dimensions = tuple(
            sorted(
                {
                    dimension
                    for result in failed
                    if result.remediation is not None
                    for dimension in result.remediation.change_dimensions
                }
            )
        )
        return (
            {
                "status": "pre_router_rejected",
                "reasons": [
                    {
                        "predicate": result.name,
                        "status": result.status,
                        "detail": result.detail,
                    }
                    for result in failed
                ],
                "pre_router": [result.model_dump(mode="json") for result in pre_router],
            },
            False,
            dimensions,
        )
    try:
        pipeline_runner(working_fixture, candidate_out)
    except Exception as exc:
        dimensions, diagnostic_error = _diagnostic_dimensions(
            candidate_out / "gate-evidence" / "design-predicates.json",
            graph.revision,
        )
        reasons = [f"deterministic pipeline rejected candidate: {exc}"]
        if diagnostic_error is not None:
            reasons.append(diagnostic_error)
            return (
                {
                    "status": "stopped",
                    "reasons": reasons,
                    "diagnostic_dimensions": list(dimensions),
                },
                False,
                (),
            )
        return (
            {
                "status": "gate_rejected",
                "reasons": reasons,
                "diagnostic_dimensions": list(dimensions),
            },
            False,
            dimensions,
        )
    return (
        {
            "status": "candidate_survived_gates",
            "reasons": [],
            "pre_router": [result.model_dump(mode="json") for result in pre_router],
        },
        True,
        (),
    )


def _commit_candidate(
    working_fixture: Path, source_graph: Path, source_fixture: Path
) -> dict[str, Any]:
    try:
        return commit_candidate_graph(
            _load_graph(working_fixture / "graph.json"), source_graph, source_fixture
        )
    except CandidateCommitError as exc:
        raise ExplorationError(str(exc)) from exc


def explore_board_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    max_candidates: int,
    *,
    max_passes: int = DEFAULT_ROUTER_MAX_PASSES,
    dry_run: bool = False,
    pipeline_runner: PipelineRunner | None = None,
    remediation: Sequence[RemediationRequest] | None = None,
    lane_id: str = "board-pipeline",
    artifact_kind: str = EXPLORATION_ARTIFACT_KIND,
) -> ExplorationResult:
    """Explore bounded placement and GPIO proposals without pass authority.

    When ``remediation`` is given, only candidates derived from those declared
    remediation dimensions are generated. Remediation-free rejection stops as
    unknown without consuming candidate budget.
    """
    if max_candidates < 1:
        raise ExplorationError("max_candidates must be positive")
    if max_passes < 1:
        raise ExplorationError("max_passes must be positive")
    graph = _load_graph(graph_path)
    if not fixture_dir.is_dir():
        raise ExplorationError(f"fixture directory is missing: {fixture_dir}")
    source_fixture = fixture_dir.resolve()
    source_graph = graph_path.resolve()
    declarations = load_design_freedom_declaration()
    dimension_map = {
        item.dimension_id: item.search_enabled for item in declarations.dimensions
    }
    remediation_dimensions: tuple[str, ...] = ()
    if remediation is None:
        placement = _placement_candidates(graph_path, fixture_dir, out_dir, graph)
        gpio = enumerate_gpio_assignment_candidates(graph)
        candidates = placement + gpio
    else:
        remediation_dimensions = _remediation_dimensions(remediation)
        candidates = _remediation_candidates(
            graph_path, fixture_dir, out_dir, graph, remediation
        )
    for candidate in candidates:
        _validate_dimensions(candidate.dimensions, dimension_map)
    pending = list(candidates[:max_candidates])
    if pipeline_runner is None:
        from acd.pipeline.gd1_board import run_pipeline

        def default_pipeline_runner(working: Path, output: Path) -> object:
            return run_pipeline(working, output, max_passes=max_passes)

        pipeline_runner = default_pipeline_runner
    candidate_records: list[dict[str, Any]] = []
    winner: str | None = None
    commit: dict[str, Any] | None = None
    commit_error: str | None = None
    with tempfile.TemporaryDirectory(prefix="acd-exploration-") as temporary:
        working_fixture = Path(temporary) / "fixture"
        shutil.copytree(source_fixture, working_fixture)
        while pending:
            candidate = pending.pop(0)
            candidate_out = out_dir / "candidates" / candidate.candidate_id
            try:
                outcome, survived, dimensions = _candidate_outcome(
                    candidate,
                    graph,
                    working_fixture,
                    candidate_out,
                    pipeline_runner,
                )
            except ExplorationError as exc:
                outcome = {"status": "stopped", "reasons": [str(exc)]}
                survived = False
                dimensions = ()
            candidate_records.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "kind": candidate.kind,
                    "dimensions": list(candidate.dimensions),
                    "changes": candidate.changes,
                    "pass_evidence": False,
                    "provenance": candidate.provenance,
                    "outcome": {**outcome, "pass_evidence": False},
                }
            )
            if outcome["status"] == "stopped":
                pending = []
            if survived:
                if dry_run:
                    winner = candidate.candidate_id
                    break
                try:
                    commit = _commit_candidate(
                        working_fixture, source_graph, source_fixture
                    )
                except ExplorationError as exc:
                    commit_error = str(exc)
                    candidate_records[-1]["outcome"] = {
                        **candidate_records[-1]["outcome"],
                        "status": "stopped",
                        "reasons": [
                            *candidate_records[-1]["outcome"]["reasons"],
                            commit_error,
                        ],
                    }
                    break
                winner = candidate.candidate_id
                break
            if dimensions:
                pending.extend(
                    item
                    for item in candidates
                    if item.candidate_id
                    not in {record["candidate_id"] for record in candidate_records}
                    and set(item.dimensions) & set(dimensions)
                    and item.candidate_id not in {entry.candidate_id for entry in pending}
                )
                pending = pending[: max_candidates - len(candidate_records)]
    stopped = any(record["outcome"]["status"] == "stopped" for record in candidate_records)
    if winner is not None:
        status = "candidate_found"
    elif stopped:
        status = "stopped"
    elif len(candidate_records) >= max_candidates:
        status = "exhausted"
    else:
        status = "stopped"
    body = _report_with_hash(
        {
            "schema_version": "0.1",
            "artifact_kind": artifact_kind,
            "lane_id": lane_id,
            "status": status,
            "termination_reason": {
                "candidate_found": "candidate_survived_gates",
                "exhausted": "candidate_budget_exhausted",
                "stopped": "fail_closed_stop",
            }[status],
            "pass_evidence": False,
            "record_class": "L3",
            "l3_statement": "This is an L3 exploration record, not gate Evidence.",
            "authority_statement": "L1 deterministic gates retain sole authority.",
            "target_revision": graph.revision,
            "max_candidates": max_candidates,
            "max_passes": max_passes,
            "evaluated_candidates": len(candidate_records),
            "winner_candidate_id": winner,
            "winner_written": winner is not None and not dry_run,
            "winner_commit": commit,
            "commit_error": commit_error,
            "remediation_dimensions": list(remediation_dimensions),
            "remediation_driven": remediation is not None,
            "candidates": candidate_records,
            "provenance": {
                "source_graph": str(source_graph),
                "source_fixture": str(source_fixture),
                "dry_run": dry_run,
                "l1_authority": "deterministic pipeline gates",
                "note": "L3 exploration observation; pass_evidence is always false.",
            },
        }
    )
    report_path = out_dir / "exploration-report.json"
    _write_json(report_path, body)
    return ExplorationResult(report=body, report_path=report_path)


def explore_firmware_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    max_candidates: int,
    *,
    dry_run: bool = False,
    pipeline_runner: PipelineRunner,
    remediation: Sequence[RemediationRequest],
) -> ExplorationResult:
    """Explore declared firmware GPIO alternatives without pass authority."""
    return explore_board_candidates(
        graph_path,
        fixture_dir,
        out_dir,
        max_candidates,
        dry_run=dry_run,
        pipeline_runner=pipeline_runner,
        remediation=remediation,
        lane_id="firmware-pipeline",
        artifact_kind=FIRMWARE_EXPLORATION_ARTIFACT_KIND,
    )


__all__ = [
    "EXPLORATION_ARTIFACT_KIND",
    "FIRMWARE_EXPLORATION_ARTIFACT_KIND",
    "ExplorationCandidate",
    "ExplorationError",
    "ExplorationResult",
    "RemediationRequest",
    "enumerate_gpio_assignment_candidates",
    "explore_board_candidates",
    "explore_firmware_candidates",
    "load_remediation_requests",
    "validate_candidate_dimensions",
]
