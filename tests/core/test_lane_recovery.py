"""Tests for declaration-driven per-lane recovery resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.design_freedom import load_design_freedom_declaration
from acd.core.lane_recovery import (
    LaneRecoveryDeclarationError,
    load_lane_recovery_declarations,
    resolve_lane_recovery,
)

DECLARATION_PATH = Path("contracts/lane-recovery-declaration.json")


def test_declared_lanes_resolve_searchable_dimensions() -> None:
    freedom = load_design_freedom_declaration()
    searchable = {
        item.dimension_id for item in freedom.dimensions if item.search_enabled
    }

    for lane_id, explorer in (
        ("board-pipeline", "board"),
        ("enclosure-pipeline", "enclosure"),
        ("firmware-pipeline", "firmware"),
    ):
        plan = resolve_lane_recovery(lane_id)
        assert plan.supported is True
        assert plan.explorer == explorer
        assert plan.dimensions
        assert set(plan.dimensions) <= searchable
        assert plan.reason is None


def test_unsupported_lanes_report_next_step_without_dimensions() -> None:
    for lane_id in ("silkscreen-resolve", "order-readiness"):
        plan = resolve_lane_recovery(lane_id)
        assert plan.supported is False
        assert plan.explorer == "none"
        assert plan.dimensions == ()
        assert plan.next_step_action
        assert plan.reason


def test_undeclared_lane_is_unsupported_and_names_the_declaration() -> None:
    plan = resolve_lane_recovery("undeclared-lane")

    assert plan.supported is False
    assert plan.reason is not None
    assert "no recovery declaration" in plan.reason
    assert "lane-recovery-declaration.json" in plan.next_step_action


def test_diagnostic_payload_stays_l3() -> None:
    diagnostic = resolve_lane_recovery("board-pipeline").as_diagnostic()

    assert diagnostic["record_class"] == "L3"
    assert diagnostic["pass_evidence"] is False
    assert diagnostic["declaration_hash"].startswith("sha256:")


def test_dimension_disabled_by_design_freedom_fails_closed(tmp_path: Path) -> None:
    document = json.loads(DECLARATION_PATH.read_text(encoding="utf-8"))
    freedom = load_design_freedom_declaration()
    disabled = sorted(
        item.dimension_id for item in freedom.dimensions if not item.search_enabled
    )
    assert disabled, "the design freedom declaration has no disabled dimension"
    for lane in document["lanes"]:
        if lane["lane_id"] == "board-pipeline":
            lane["recovery_dimensions"] = [disabled[0]]
    path = tmp_path / "lane-recovery-declaration.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    plan = resolve_lane_recovery(
        "board-pipeline", declarations=load_lane_recovery_declarations(path)
    )

    assert plan.supported is False
    assert plan.reason is not None
    assert "not searchable" in plan.reason


def test_malformed_declaration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "lane-recovery-declaration.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(LaneRecoveryDeclarationError, match="invalid"):
        load_lane_recovery_declarations(path)


def test_explorable_lane_without_dimension_is_rejected(tmp_path: Path) -> None:
    document = json.loads(DECLARATION_PATH.read_text(encoding="utf-8"))
    for lane in document["lanes"]:
        if lane["lane_id"] == "board-pipeline":
            lane["recovery_dimensions"] = []
    path = tmp_path / "lane-recovery-declaration.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LaneRecoveryDeclarationError):
        load_lane_recovery_declarations(path)
