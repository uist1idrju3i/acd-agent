"""Bring-up test-plan projection tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from test_interface_spec import GRAPH, config_report, pins_header

from acd.schema.bringup_plan import BringUpTestPlan
from acd.schema.firmware_inspection import FirmwareInspectionItem, FirmwareInspectionSequence
from acd.schema.shipping_inspection import CriterionSource
from doc_inputs import DocumentGenerationError
from generate_bringup_plan import main as bringup_main


def _run(
    tmp_path: Path,
    *,
    lang: str = "ja",
    policy: Path | None = None,
    sequence: Path | None = None,
    revision: str = "r1",
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    header = pins_header(tmp_path, revision=revision)
    report = config_report(tmp_path, revision=revision)
    out_dir = tmp_path / "out"
    args = [
        "--graph",
        str(GRAPH),
        "--pins-header",
        str(header),
        "--firmware-config-report",
        str(report),
        "--out-dir",
        str(out_dir),
        "--base-dir",
        str(tmp_path),
    ]
    if policy is not None:
        args.extend(["--feedback-policy", str(policy)])
    if sequence is not None:
        args.extend(["--inspection-sequence", str(sequence)])
    if lang != "ja":
        args.extend(["--lang", lang])
    assert bringup_main(args) == 0
    return out_dir if lang == "ja" else out_dir / lang


def _sequence(path: Path, *, revision: str = "r1") -> Path:
    payload = FirmwareInspectionSequence(
        schema_version="0.1",
        graph_id="golden-design-1",
        target_revision=revision,
        entry_command="ACD INSPECT",
        begin_line=f"ACD_INSPECT begin target_revision={revision}",
        end_line="ACD_INSPECT end items=2",
        items=[
            FirmwareInspectionItem(
                item_id="led",
                kind="led",
                subject_node_ids=["fw.pin.led"],
                source=CriterionSource(
                    kind="firmware_projection",
                    ref="firmware-inspection-sequence.json#led",
                ),
                expected_line="ACD_INSPECT led:led gpio=7 result=executed",
                status="derived",
            ),
            FirmwareInspectionItem(
                item_id="power",
                kind="power_self_check",
                subject_node_ids=["net.p3v3"],
                status="unknown",
                unknown_reason="no self-measurement source declared in graph",
            ),
        ],
    )
    path.write_text(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_gd1_plan_validates_and_is_phase_ordered(tmp_path: Path) -> None:
    output = _run(tmp_path)
    plan = BringUpTestPlan.model_validate(
        json.loads((output / "bringup-test-plan.json").read_text(encoding="utf-8"))
    )
    phases = [item.phase for item in plan.items]
    assert phases == sorted(
        phases,
        key=("unpowered", "power_up", "flash_boot", "peripheral", "self_test").index,
    )
    assert all(
        item.measurement is not None and item.criterion_source is not None
        for item in plan.items
        if item.phase == "power_up"
    )
    assert all(
        item.stop_on_fail for item in plan.items if item.phase == "flash_boot"
    )
    assert all(
        item.criterion_source is not None
        for item in plan.items
        if item.unknown_reason is None
    )


def test_feedback_policy_lists_uncovered_rules(tmp_path: Path) -> None:
    output = _run(
        tmp_path,
        policy=Path(__file__).resolve().parents[5]
        / "fixtures"
        / "feedback"
        / "policy.json",
    )
    plan = BringUpTestPlan.model_validate(
        json.loads((output / "bringup-test-plan.json").read_text(encoding="utf-8"))
    )
    assert plan.uncovered_feedback_rules == [
        "led-frequency-reconfirm",
        "artifact-count",
    ]
    assert "実測計画で未被覆のfeedback rule" in (
        output / "bringup-test-plan.md"
    ).read_text(encoding="utf-8")


def test_feedback_policy_revision_mismatch_writes_nothing(tmp_path: Path) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        (Path(__file__).resolve().parents[5] / "fixtures/feedback/policy.json")
        .read_text(encoding="utf-8")
        .replace('"revision": "r1"', '"revision": "r2"'),
        encoding="utf-8",
    )
    with pytest.raises(DocumentGenerationError, match="feedback policy"):
        _run(tmp_path, policy=policy)
    assert not (tmp_path / "out").exists()


def test_inspection_sequence_adds_self_test_items(tmp_path: Path) -> None:
    sequence = _sequence(tmp_path / "sequence.json")
    output = _run(tmp_path, sequence=sequence)
    plan = BringUpTestPlan.model_validate(
        json.loads((output / "bringup-test-plan.json").read_text(encoding="utf-8"))
    )
    self_test = [item for item in plan.items if item.phase == "self_test"]
    assert len(self_test) == 3
    assert self_test[0].criterion_source is not None
    assert self_test[2].unknown_reason == "no self-measurement source declared in graph"


def test_revision_mismatched_sequence_writes_nothing(tmp_path: Path) -> None:
    sequence = _sequence(tmp_path / "sequence.json", revision="r2")
    with pytest.raises(DocumentGenerationError):
        _run(tmp_path, sequence=sequence)
    assert not (tmp_path / "out").exists()


def test_english_and_deterministic_outputs(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")
    assert (first / "bringup-test-plan.md").read_bytes() == (
        second / "bringup-test-plan.md"
    ).read_bytes()
    assert (first / "bringup-test-plan.json").read_bytes() == (
        second / "bringup-test-plan.json"
    ).read_bytes()
    english = _run(tmp_path / "english", lang="en")
    assert not re.search(
        r"[\u3400-\u9fff\u3040-\u30ff]",
        (english / "bringup-test-plan.md").read_text(encoding="utf-8"),
    )


def test_malformed_pins_header_writes_nothing(tmp_path: Path) -> None:
    report = config_report(tmp_path)
    header = tmp_path / "bad.h"
    header.write_text("#define ACD_TARGET_REVISION r1\n", encoding="utf-8")
    with pytest.raises(DocumentGenerationError):
        bringup_main(
            [
                "--graph",
                str(GRAPH),
                "--pins-header",
                str(header),
                "--firmware-config-report",
                str(report),
                "--out-dir",
                str(tmp_path / "out"),
            ]
        )
    assert not (tmp_path / "out").exists()
