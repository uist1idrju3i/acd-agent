"""Workaround work-instruction projection tests."""

from __future__ import annotations

import json
from pathlib import Path

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


def _salvage(tmp_path: Path) -> Path:
    directory = tmp_path / "salvage"
    directory.mkdir()
    graph = DesignGraph.model_validate_json(GRAPH.read_text(encoding="utf-8"))
    diff = load_rework_diff(REWORK).diff
    write_derived_graph(apply_rework_diff(graph, diff), directory)
    result = SalvageGateResult(
        workaround_id=diff.workaround_id,
        graph_id=graph.graph_id,
        base_revision=graph.revision,
        derived_revision=diff.derived_revision,
        verdict="salvageable",
        gate_runs=[
            GateRun(gate="test", status="pass", source="computed", detail="fixture")
        ],
        dfa_blockers=[],
        safety_boundary_touched=True,
        approval_status="approved",
        degraded_functions=[],
        reasons=[],
    )
    (directory / "salvage-gate.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return directory


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
