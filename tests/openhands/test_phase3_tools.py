"""Tests for Phase 3 OpenHands tool coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.openhands.tools.definitions import (
    ACD_TOOL_DEFINITIONS,
    AcdCheckOrderReadiness,
    AcdCheckOrderReadinessAction,
    AcdDiagnoseGateFailure,
    AcdDiagnoseGateFailureAction,
    AcdRunFirmwarePipelineAction,
)


def test_phase3_tools_are_registered_in_code_contract() -> None:
    names = {name for name, _definition in ACD_TOOL_DEFINITIONS}
    assert {
        "acd_run_firmware_pipeline",
        "acd_compile_requirement_change",
        "acd_build_design_fixture",
        "acd_explore_board_candidates",
        "acd_explore_enclosure_candidates",
        "acd_diagnose_gate_failure",
        "acd_check_order_readiness",
    } <= names


def test_read_only_diagnosis_declares_output_resource() -> None:
    tool = AcdDiagnoseGateFailure.create()[0]
    resources = tool.declared_resources(
        AcdDiagnoseGateFailureAction(out_dir="out/diagnosis")
    )
    assert resources.declared is True
    assert resources.keys == (f"acd-out:{Path('out/diagnosis').resolve()}",)


def test_firmware_action_rejects_non_positive_duration() -> None:
    try:
        AcdRunFirmwarePipelineAction(run_seconds=0)
    except ValueError:
        return
    raise AssertionError("non-positive firmware duration was accepted")


def test_order_readiness_requires_explicit_design_graph() -> None:
    with pytest.raises(ValueError):
        AcdCheckOrderReadinessAction.model_validate(
            {
                "order_total": "out/order-total.json",
                "evaluated_at": "2026-08-14T00:00:00Z",
            }
        )

    action = AcdCheckOrderReadinessAction(
        design_graph_path="fixtures/custom/graph.json",
        order_total="out/order-total.json",
        evaluated_at="2026-08-14T00:00:00Z",
    )
    resources = AcdCheckOrderReadiness.create()[0].declared_resources(action)
    assert resources.declared is True
    assert resources.keys == (
        f"file:{Path('plugins/acd/hooks/order-policy.json').resolve()}",
        f"file:{Path('fixtures/custom/graph.json').resolve()}",
        f"file:{Path('out/order-total.json').resolve()}",
    )
