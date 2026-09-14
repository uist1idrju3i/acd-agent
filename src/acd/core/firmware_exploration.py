"""Firmware-lane-only candidate exploration.

Unlike the board explorer, the firmware explorer only enumerates the declared
``gpio_assignment`` dimension. Board placement and rotation dimensions are
reported as excluded rather than turned into candidates. Coverage findings from
the firmware lane's ``firmware-coverage.json`` mean a declaration is missing,
so the search stops with ``declaration_required`` and names the required
declaration target instead of generating candidates. The report is an L3
observation with ``pass_evidence`` false; deterministic gates remain the sole
authority.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast, get_args

from acd.adapters.freerouting.router import DEFAULT_ROUTER_MAX_PASSES
from acd.core.exploration import (
    FIRMWARE_EXPLORATION_ARTIFACT_KIND,
    ExplorationCandidate,
    ExplorationError,
    ExplorationResult,
    PipelineRunner,
    RemediationRequest,
    enumerate_gpio_assignment_candidates,
    load_exploration_graph,
    load_exploration_rationale,
    run_candidate_search,
)
from acd.core.firmware_coverage import FirmwareCoverageCode, FirmwareCoverageFinding

FIRMWARE_SEARCHABLE_DIMENSIONS: frozenset[str] = frozenset({"gpio_assignment"})

_REGISTRY = "contracts/firmware-capability-registry.json"
_DECLARATION_TARGETS: dict[FirmwareCoverageCode, str] = {
    "action_unregistered": f"{_REGISTRY}#capabilities[].actions",
    "trigger_unemitted": f"{_REGISTRY}#capabilities[].emits_triggers",
    "led_indicator_untargeted": "graph.json#firmware.sequence_step (led target)",
    "pin_role_unconsumed": "graph.json#firmware.pin_assignment / firmware.sequence_step",
}


@dataclass(frozen=True)
class RequiredDeclaration:
    """One missing declaration a firmware recovery candidate cannot supply."""

    code: FirmwareCoverageCode
    node_id: str
    message: str
    declaration_target: str


def load_firmware_coverage_findings(
    path: Path,
) -> tuple[FirmwareCoverageFinding, ...]:
    """Parse a firmware coverage report into typed findings (fail-closed)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplorationError(
            f"firmware coverage report is unreadable: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ExplorationError("firmware coverage report is not an object")
    findings = cast(dict[str, Any], payload).get("findings")
    if not isinstance(findings, list):
        raise ExplorationError("firmware coverage report findings are missing")
    known_codes = set(get_args(FirmwareCoverageCode))
    result: list[FirmwareCoverageFinding] = []
    for item in cast(list[object], findings):
        if not isinstance(item, dict):
            raise ExplorationError("firmware coverage finding is not an object")
        body = cast(dict[str, Any], item)
        code = body.get("code")
        node_id = body.get("node_id")
        message = body.get("message")
        if (
            not isinstance(code, str)
            or code not in known_codes
            or not isinstance(node_id, str)
            or not isinstance(message, str)
        ):
            raise ExplorationError(
                "firmware coverage finding is malformed (fail-closed)"
            )
        result.append(
            FirmwareCoverageFinding(
                code=cast(FirmwareCoverageCode, code),
                node_id=node_id,
                message=message,
            )
        )
    return tuple(result)


def explore_firmware_candidates(
    graph_path: Path,
    fixture_dir: Path,
    out_dir: Path,
    max_candidates: int,
    *,
    dry_run: bool = False,
    pipeline_runner: PipelineRunner,
    remediation: Sequence[RemediationRequest],
    coverage_findings: Sequence[FirmwareCoverageFinding] = (),
    max_passes: int = DEFAULT_ROUTER_MAX_PASSES,
) -> ExplorationResult:
    """Explore declared firmware GPIO alternatives without pass authority.

    Only ``gpio_assignment`` candidates are generated. Coverage findings mean
    the rejection needs a declaration, not a design candidate, so the search
    reports ``declaration_required`` with the declaration target and consumes
    no candidate budget.
    """
    if max_candidates < 1:
        raise ExplorationError("max_candidates must be positive")
    if max_passes < 1:
        raise ExplorationError("max_passes must be positive")
    graph = load_exploration_graph(graph_path)
    if not fixture_dir.is_dir():
        raise ExplorationError(f"fixture directory is missing: {fixture_dir}")
    rationale = load_exploration_rationale(fixture_dir / "rationale.json")
    requested = {
        dimension
        for request in remediation
        for dimension in request.change_dimensions
    }
    remediation_dimensions = sorted(requested & FIRMWARE_SEARCHABLE_DIMENSIONS)
    excluded_dimensions = sorted(requested - FIRMWARE_SEARCHABLE_DIMENSIONS)
    required_declarations: list[dict[str, Any]] = []
    termination_override: tuple[str, str] | None = None
    candidates: tuple[ExplorationCandidate, ...] = ()
    if coverage_findings:
        termination_override = ("stopped", "declaration_required")
        required_declarations = [
            asdict(
                RequiredDeclaration(
                    code=finding.code,
                    node_id=finding.node_id,
                    message=finding.message,
                    declaration_target=_DECLARATION_TARGETS[finding.code],
                )
            )
            for finding in coverage_findings
        ]
    elif "gpio_assignment" in remediation_dimensions:
        candidates = enumerate_gpio_assignment_candidates(graph)
    return run_candidate_search(
        graph,
        graph_path,
        fixture_dir,
        out_dir,
        rationale,
        candidates,
        max_candidates,
        max_passes,
        dry_run=dry_run,
        pipeline_runner=pipeline_runner,
        lane_id="firmware-pipeline",
        artifact_kind=FIRMWARE_EXPLORATION_ARTIFACT_KIND,
        remediation_dimensions=remediation_dimensions,
        remediation_driven=True,
        generation_diagnostics=[],
        extra_report={
            "candidate_source": "firmware_registry_and_predicates",
            "excluded_dimensions": excluded_dimensions,
            "required_declarations": required_declarations,
            "searchable_dimensions": sorted(FIRMWARE_SEARCHABLE_DIMENSIONS),
        },
        termination_override=termination_override,
    )


__all__ = [
    "FIRMWARE_SEARCHABLE_DIMENSIONS",
    "RequiredDeclaration",
    "explore_firmware_candidates",
    "load_firmware_coverage_findings",
]
