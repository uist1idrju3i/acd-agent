"""Workaround work-instruction projection tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from test_interface_spec import GRAPH, config_report, pins_header

from acd.core.rework_diff import apply_rework_diff, load_rework_diff, write_derived_graph
from acd.schema.design_graph import DesignGraph
from acd.schema.salvage import GateRun, SalvageGateResult
from acd.schema.work_instruction import WorkInstructionDocument
from generate_work_instruction import main

ROOT = Path(__file__).resolve().parents[5]
DEFECTS = ROOT / "fixtures" / "defect" / "sample" / "defects.json"
REWORK = ROOT / "fixtures" / "rework" / "sample" / "rework.json"
DFA = ROOT / "fixtures" / "rework" / "sample" / "rework-dfa.json"
FW_REWORK = ROOT / "fixtures" / "rework" / "sample-fw-only" / "rework.json"
FW_DFA = ROOT / "fixtures" / "rework" / "sample-fw-only" / "rework-dfa.json"


def _salvage(
    tmp_path: Path,
    *,
    rework_path: Path = REWORK,
    verdict: Literal["salvageable", "constrained_salvage"] = "salvageable",
    degraded_functions: list[str] | None = None,
) -> Path:
    directory = tmp_path / "salvage"
    directory.mkdir(parents=True)
    graph = DesignGraph.model_validate_json(GRAPH.read_text(encoding="utf-8"))
    diff = load_rework_diff(rework_path).diff
    write_derived_graph(apply_rework_diff(graph, diff), directory)
    result = SalvageGateResult(
        workaround_id=diff.workaround_id,
        graph_id=graph.graph_id,
        base_revision=graph.revision,
        derived_revision=diff.derived_revision,
        verdict=verdict,
        gate_runs=[
            GateRun(gate="test", status="pass", source="computed", detail="fixture")
        ],
        dfa_blockers=[],
        safety_boundary_touched=True,
        approval_status="approved",
        degraded_functions=degraded_functions or [],
        reasons=[],
    )
    (directory / "salvage-gate.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return directory


def _fw_defects(tmp_path: Path) -> Path:
    payload = json.loads(DEFECTS.read_text(encoding="utf-8"))
    payload["records"][0]["defect_id"] = "defect.firmware-degrade"
    path = tmp_path / "fw-defects.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _run(
    output: Path,
    salvage: Path,
    *,
    defects: Path = DEFECTS,
    rework: Path = REWORK,
    dfa: Path = DFA,
    lang: str | None = None,
) -> int:
    arguments = [
        "--graph", str(GRAPH), "--defects", str(defects),
        "--rework", str(rework), "--dfa", str(dfa),
        "--salvage-dir", str(salvage), "--pins-header",
        str(pins_header(output.parent)), "--firmware-config-report",
        str(config_report(output.parent)), "--out-dir", str(output),
    ]
    if lang is not None:
        arguments.extend(["--lang", lang])
    return main(arguments)


def test_sample_work_instruction_validates_and_has_projection(tmp_path: Path) -> None:
    salvage = _salvage(tmp_path)
    header = pins_header(tmp_path)
    report = config_report(tmp_path)
    output = tmp_path / "out"
    assert (
        main(
            [
                "--graph",
                str(GRAPH),
                "--defects",
                str(DEFECTS),
                "--rework",
                str(REWORK),
                "--dfa",
                str(DFA),
                "--salvage-dir",
                str(salvage),
                "--pins-header",
                str(header),
                "--firmware-config-report",
                str(report),
                "--out-dir",
                str(output),
            ]
        )
        == 0
    )
    document = WorkInstructionDocument.model_validate_json(
        (output / "work-instruction.json").read_text(encoding="utf-8")
    )
    assert len(document.steps) == 2
    assert document.required_parts[0].refdes == "R4"
    assert document.required_tools[0].basis == "DFA review for the resistor assembly change."
    assert document.target_units.lots == ["LOT-GD1-001"]
    assert document.highlight_projection is not None
    assert (output / document.highlight_projection).is_file()
    assert document.post_work_inspection.items
    assert all(
        item.criterion.unknown_reason == (
            "firmware projection unavailable for this revision"
        )
        for item in document.post_work_inspection.items
        if item.category in {"flash_boot", "led", "sensor", "serial"}
    )
    assert all(
        item.criterion.source is not None
        for item in document.post_work_inspection.items
        if item.criterion.kind != "unknown"
    )


def test_not_salvageable_writes_nothing(tmp_path: Path) -> None:
    salvage = _salvage(tmp_path)
    payload = json.loads((salvage / "salvage-gate.json").read_text(encoding="utf-8"))
    payload["verdict"] = "not_salvageable"
    payload["reasons"] = ["gate failed"]
    (salvage / "salvage-gate.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    output = tmp_path / "out"
    assert (
        main(
            [
                "--graph", str(GRAPH), "--defects", str(DEFECTS),
                "--rework", str(REWORK), "--dfa", str(DFA),
                "--salvage-dir", str(salvage), "--pins-header",
                str(pins_header(tmp_path)), "--firmware-config-report",
                str(config_report(tmp_path)), "--out-dir", str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


def test_firmware_only_constrained_salvage_renders_warning(tmp_path: Path) -> None:
    defects = _fw_defects(tmp_path)
    salvage = _salvage(
        tmp_path,
        rework_path=FW_REWORK,
        verdict="constrained_salvage",
        degraded_functions=["usb_c_cc_termination"],
    )
    output = tmp_path / "out"
    assert _run(
        output,
        salvage,
        defects=defects,
        rework=FW_REWORK,
        dfa=FW_DFA,
    ) == 0
    document = WorkInstructionDocument.model_validate_json(
        (output / "work-instruction.json").read_text(encoding="utf-8")
    )
    assert document.salvage_verdict == "constrained_salvage"
    assert document.required_parts == []
    assert any(step.op == "firmware" for step in document.steps)
    assert "全機能を復元しない" in (
        output / "work-instruction.md"
    ).read_text(encoding="utf-8")


def test_tampered_derived_graph_writes_nothing(tmp_path: Path) -> None:
    salvage = _salvage(tmp_path)
    derived = salvage / "derived-graph.json"
    payload = json.loads(derived.read_text(encoding="utf-8"))
    payload["revision"] = "r1+WA-TAMPERED"
    derived.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    assert _run(output, salvage) == 1
    assert not output.exists()


def test_languages_validate_and_are_deterministic(tmp_path: Path) -> None:
    first_salvage = _salvage(tmp_path / "first")
    first = tmp_path / "first" / "out"
    assert _run(first, first_salvage) == 0
    second_salvage = _salvage(tmp_path / "second")
    second = tmp_path / "second" / "out"
    assert _run(second, second_salvage) == 0
    assert (first / "work-instruction.json").read_bytes() == (
        second / "work-instruction.json"
    ).read_bytes()
    assert (first / "work-instruction.md").read_bytes() == (
        second / "work-instruction.md"
    ).read_bytes()

    en_salvage = _salvage(tmp_path / "en")
    en = tmp_path / "en" / "out"
    assert _run(en, en_salvage, lang="en") == 0
    WorkInstructionDocument.model_validate_json(
        (en / "en" / "work-instruction.json").read_text(encoding="utf-8")
    )
    assert not re.search(
        r"[\u3400-\u9fff\u3040-\u30ff]",
        (en / "en" / "work-instruction.md").read_text(encoding="utf-8"),
    )
