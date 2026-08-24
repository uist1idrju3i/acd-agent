"""Tests for Phase 3 OpenHands tool coverage."""

from __future__ import annotations

from pathlib import Path

from acd.openhands.tools.definitions import (
    ACD_TOOL_DEFINITIONS,
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
