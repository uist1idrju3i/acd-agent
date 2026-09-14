from __future__ import annotations

# pyright: reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownMemberType=false
import json
from pathlib import Path
from typing import Any

import pytest

from acd.core.exploration import ExplorationError, RemediationRequest
from acd.core.firmware_coverage import FirmwareCoverageFinding
from acd.core.firmware_exploration import (
    FIRMWARE_SEARCHABLE_DIMENSIONS,
    explore_firmware_candidates,
    load_firmware_coverage_findings,
)
from acd.core.lane_recovery import resolve_lane_recovery

FIXTURE_DIR = Path("fixtures/golden-design-1")
GRAPH_PATH = FIXTURE_DIR / "graph.json"


def _runner(_fixture: Path, _out: Path) -> dict[str, Any]:
    return {"gate": "completed"}


def _remediation(*dimensions: str) -> tuple[RemediationRequest, ...]:
    return (
        RemediationRequest(
            predicate="gpio_assignment_conflict",
            change_dimensions=tuple(dimensions),
            refdes="U1",
        ),
    )


def _coverage_finding(code: str = "action_unregistered") -> FirmwareCoverageFinding:
    return FirmwareCoverageFinding(
        code=code,  # pyright: ignore[reportArgumentType]
        node_id="fw.step.blink",
        message="action is not registered in the capability registry",
    )


def test_board_dimensions_are_excluded_from_firmware_candidates(
    tmp_path: Path,
) -> None:
    result = explore_firmware_candidates(
        GRAPH_PATH,
        FIXTURE_DIR,
        tmp_path / "out",
        max_candidates=1,
        dry_run=True,
        pipeline_runner=_runner,
        remediation=_remediation("component_placement_xy", "gpio_assignment"),
    )
    report = result.report
    assert report["lane_id"] == "firmware-pipeline"
    assert report["remediation_driven"] is True
    assert report["pass_evidence"] is False
    assert report["excluded_dimensions"] == ["component_placement_xy"]
    assert report["searchable_dimensions"] == ["gpio_assignment"]
    assert report["candidate_source"] == "firmware_registry_and_predicates"
    kinds = {candidate["kind"] for candidate in report["candidates"]}
    assert kinds <= {"gpio_assignment"}
    assert "decoupling_placement" not in kinds
    assert "placement" not in kinds


def test_coverage_findings_stop_with_declaration_required(tmp_path: Path) -> None:
    result = explore_firmware_candidates(
        GRAPH_PATH,
        FIXTURE_DIR,
        tmp_path / "out",
        max_candidates=3,
        dry_run=True,
        pipeline_runner=_runner,
        remediation=_remediation("gpio_assignment"),
        coverage_findings=(_coverage_finding(),),
    )
    report = result.report
    assert report["status"] == "stopped"
    assert report["termination_reason"] == "declaration_required"
    assert report["evaluated_candidates"] == 0
    assert report["consumed_budget"] == 0
    assert report["record_class"] == "L3"
    assert report["pass_evidence"] is False
    declarations = report["required_declarations"]
    assert len(declarations) == 1
    assert declarations[0]["declaration_target"] == (
        "contracts/firmware-capability-registry.json#capabilities[].actions"
    )
    assert declarations[0]["code"] == "action_unregistered"


def test_searchable_dimensions_match_the_lane_recovery_declaration() -> None:
    plan = resolve_lane_recovery("firmware-pipeline")
    assert plan.explorer == "firmware"
    assert frozenset(plan.dimensions) == FIRMWARE_SEARCHABLE_DIMENSIONS


def test_no_declared_dimension_generates_no_candidate(tmp_path: Path) -> None:
    result = explore_firmware_candidates(
        GRAPH_PATH,
        FIXTURE_DIR,
        tmp_path / "out",
        max_candidates=1,
        dry_run=True,
        pipeline_runner=_runner,
        remediation=_remediation("component_placement_xy"),
    )
    assert result.report["status"] == "stopped"
    assert result.report["termination_reason"] == "no_candidate_generated"
    assert result.report["evaluated_candidates"] == 0


def test_load_firmware_coverage_findings_parses_report(tmp_path: Path) -> None:
    path = tmp_path / "firmware-coverage.json"
    path.write_text(
        json.dumps(
            {
                "status": "fail",
                "findings": [
                    {
                        "code": "trigger_unemitted",
                        "node_id": "fw.cap.uart",
                        "message": "declared trigger is never emitted",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    findings = load_firmware_coverage_findings(path)
    assert [finding.code for finding in findings] == ["trigger_unemitted"]
    assert findings[0].node_id == "fw.cap.uart"


def test_load_firmware_coverage_findings_missing_file_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(ExplorationError):
        load_firmware_coverage_findings(tmp_path / "absent.json")


def test_load_firmware_coverage_findings_malformed_json_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "firmware-coverage.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExplorationError):
        load_firmware_coverage_findings(path)


def test_load_firmware_coverage_findings_unknown_code_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "firmware-coverage.json"
    path.write_text(
        json.dumps(
            {
                "status": "fail",
                "findings": [
                    {"code": "bogus_code", "node_id": "n1", "message": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ExplorationError):
        load_firmware_coverage_findings(path)


def test_max_candidates_zero_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExplorationError):
        explore_firmware_candidates(
            GRAPH_PATH,
            FIXTURE_DIR,
            tmp_path / "out",
            max_candidates=0,
            dry_run=True,
            pipeline_runner=_runner,
            remediation=_remediation("gpio_assignment"),
        )
