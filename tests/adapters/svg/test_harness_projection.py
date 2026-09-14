"""Harness projection determinism tests."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from acd.adapters.svg import (  # pyright: ignore[reportMissingTypeStubs]
    generate_harness_visual_projection,
)
from acd.core.electrical import extract_electrical_lane
from acd.schema import DesignGraph, HarnessContract

ROOT = Path(__file__).parents[3]
FIXTURE = ROOT / "fixtures/harness/gd1-external-sensor"


def _inputs() -> tuple[DesignGraph, HarnessContract]:
    graph = DesignGraph.model_validate(
        json.loads((FIXTURE / "graph.json").read_text(encoding="utf-8"))
    )
    contract = HarnessContract.model_validate(
        json.loads((FIXTURE / "harness.json").read_text(encoding="utf-8"))
    )
    return graph, contract


def test_harness_svg_is_byte_identical_and_csv_has_one_row_per_wire(
    tmp_path: Path,
) -> None:
    graph, contract = _inputs()
    lane = extract_electrical_lane(graph)
    first = tmp_path / "first"
    second = tmp_path / "second"
    input_files = (FIXTURE / "graph.json", FIXTURE / "harness.json")
    generate_harness_visual_projection(
        out_dir=first,
        source_revision=graph.revision,
        graph=graph,
        lane=lane,
        contract=contract,
        authoritative_inputs=input_files,
        input_base_dir=ROOT,
    )
    generate_harness_visual_projection(
        out_dir=second,
        source_revision=graph.revision,
        graph=graph,
        lane=lane,
        contract=contract,
        authoritative_inputs=input_files,
        input_base_dir=ROOT,
    )
    assert (first / "harness.svg").read_bytes() == (second / "harness.svg").read_bytes()


def test_projection_script_writes_cut_length_table(tmp_path: Path) -> None:
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/project_harness.py",
            "--graph",
            str(FIXTURE / "graph.json"),
            "--harness",
            str(FIXTURE / "harness.json"),
            "--out-dir",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    with (out / "cut-length-table.csv").open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 4
    assert (out / "harness-projection.provenance.json").is_file()
    second = tmp_path / "second-script"
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/project_harness.py",
            "--graph",
            str(FIXTURE / "graph.json"),
            "--harness",
            str(FIXTURE / "harness.json"),
            "--out-dir",
            str(second),
        ],
        cwd=ROOT,
        check=True,
    )
    for name in (
        "harness.svg",
        "cut-length-table.csv",
        "cut-length-table.md",
        "harness-projection.provenance.json",
    ):
        assert (out / name).read_bytes() == (second / name).read_bytes()
