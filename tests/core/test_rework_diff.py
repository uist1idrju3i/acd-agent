from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.derive_rework_graph import main

from acd.core.rework_diff import (
    ReworkDiffError,
    apply_rework_diff,
    write_derived_graph,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.rework_diff import ReworkDiff

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REWORK_PATH = ROOT / "fixtures/rework/sample/rework.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _payload(**overrides: object) -> dict[str, Any]:
    value = json.loads(REWORK_PATH.read_text(encoding="utf-8"))
    value.update(overrides)
    return value


def _diff(payload: dict[str, Any] | None = None) -> ReworkDiff:
    return ReworkDiff.model_validate(payload or _payload())


def test_sample_applies_without_mutating_base() -> None:
    graph = _graph()
    before = graph.model_dump(mode="json")
    derived = apply_rework_diff(graph, _diff(), graph_path=GRAPH_PATH)
    assert graph.model_dump(mode="json") == before
    assert derived.graph.graph_id == "golden-design-1"
    assert derived.graph.revision == "r1+WA-001"
    assert derived.derived_revision == "r1+WA-001"
    assert "comp.r4" in derived.touched_node_ids
    assert derived.graph.node_by_id("comp.r4").attrs["jlcpcb_class"] == "extended"
    assert derived.graph.node_by_id("comp.r5").attrs["jlcpcb_class"] == "extended"


def test_application_is_deterministic() -> None:
    first = apply_rework_diff(_graph(), _diff())
    second = apply_rework_diff(_graph(), _diff())
    assert first.graph.model_dump(mode="json") == second.graph.model_dump(mode="json")
    assert first.touched_node_ids == second.touched_node_ids


def test_unknown_pin_fails() -> None:
    payload = _payload()
    payload["operations"] = [
        {
            "op": "cut",
            "pin_id": "pin.unknown",
            "reason": "Disconnect the signal-side resistor pin.",
        }
    ]
    with pytest.raises(ReworkDiffError, match="does not exist"):
        apply_rework_diff(_graph(), _diff(payload))


def test_already_no_connect_pin_fails() -> None:
    graph_payload = _graph().model_dump(mode="json")
    pin = next(item for item in graph_payload["nodes"] if item["id"] == "pin.r4.2")
    pin["attrs"]["net"] = None
    pin["attrs"]["no_connect"] = True
    graph = DesignGraph.model_validate(graph_payload)
    payload = _payload()
    payload["operations"] = [
        {
            "op": "cut",
            "pin_id": "pin.r4.2",
            "reason": "Disconnect the signal-side resistor pin.",
        }
    ]
    with pytest.raises(ReworkDiffError, match="already disconnected"):
        apply_rework_diff(graph, _diff(payload))


def test_duplicate_added_id_fails() -> None:
    payload = _payload()
    payload["operations"] = [
        {
            "op": "add",
            "node": {
                "id": "comp.r4",
                "kind": "electrical.component",
                "attrs": {},
                "depends_on": [],
            },
            "reason": "Duplicate node.",
        }
    ]
    with pytest.raises(ReworkDiffError, match="already exists"):
        apply_rework_diff(_graph(), _diff(payload))


def test_remove_dangling_dependency_fails() -> None:
    payload = _payload()
    payload["operations"] = [
        {
            "op": "add",
            "node": {
                "id": "net.rework",
                "kind": "electrical.net",
                "attrs": {},
                "depends_on": ["comp.r4"],
            },
            "reason": "Temporary dependency.",
        },
        {
            "op": "remove",
            "component_id": "comp.r4",
            "reason": "Remove the component.",
        },
    ]
    with pytest.raises(ReworkDiffError, match="dangling"):
        apply_rework_diff(_graph(), _diff(payload))


def test_mechanical_new_key_fails() -> None:
    payload = _payload()
    payload["operations"] = [
        {
            "op": "mechanical",
            "target_id": "mechanical.outline.gd1",
            "attrs": {"new_dimension_mm": 4.0},
            "reason": "Change enclosure clearance.",
        }
    ]
    with pytest.raises(ReworkDiffError, match="already exist"):
        apply_rework_diff(_graph(), _diff(payload))


def test_power_net_touch_without_declaration_fails() -> None:
    payload = _payload()
    payload["touches_safety_boundary"] = False
    payload["operations"] = [
        {
            "op": "cut",
            "pin_id": "pin.r4.1",
            "reason": "Disconnect the power pin.",
        }
    ]
    with pytest.raises(ReworkDiffError, match="safety boundary"):
        apply_rework_diff(_graph(), _diff(payload))


def test_revision_mismatch_fails() -> None:
    payload = _payload(base_revision="r2")
    with pytest.raises(ReworkDiffError, match="revision"):
        apply_rework_diff(_graph(), _diff(payload))


def test_output_inside_base_graph_directory_fails(tmp_path: Path) -> None:
    derived = apply_rework_diff(_graph(), _diff(), graph_path=GRAPH_PATH)
    with pytest.raises(ReworkDiffError, match="inside the base graph"):
        write_derived_graph(derived, ROOT / "fixtures/golden-design-1/derived")


def test_cli_exit_codes(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--graph",
                str(GRAPH_PATH),
                "--rework",
                str(REWORK_PATH),
                "--out-dir",
                str(tmp_path / "pass"),
            ]
        )
        == 0
    )
    assert (tmp_path / "pass/derived-graph.json").is_file()
    assert (tmp_path / "pass/derived-graph.provenance.json").is_file()

    payload = _payload(base_revision="r2")
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        main(
            [
                "--graph",
                str(GRAPH_PATH),
                "--rework",
                str(invalid),
                "--out-dir",
                str(tmp_path / "fail"),
            ]
        )
        == 1
    )


def test_derived_graph_is_reloadable_and_validated_by_graph_cli(
    tmp_path: Path,
) -> None:
    derived_dir = tmp_path / "derived"
    validation_payload = _payload()
    validation_payload["operations"] = [
        {
            "op": "cut",
            "pin_id": "pin.r4.2",
            "reason": "Disconnect the signal-side resistor pin.",
        }
    ]
    validation_payload["touches_safety_boundary"] = False
    derived = apply_rework_diff(_graph(), _diff(validation_payload))
    write_derived_graph(derived, derived_dir)
    derived_path = derived_dir / "derived-graph.json"
    reloaded = DesignGraph.model_validate_json(
        derived_path.read_text(encoding="utf-8")
    )
    assert reloaded.revision == "r1+WA-001"

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    shutil.copy2(derived_path, fixture_dir / "graph.json")
    for name in ("requirements.json", "rationale.json"):
        payload = json.loads(
            (ROOT / "fixtures/golden-design-1" / name).read_text(encoding="utf-8")
        )
        payload["revision"] = reloaded.revision
        if name == "rationale.json":
            for record in payload["records"]:
                record["target_revision"] = reloaded.revision
        (fixture_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_graph.py",
            "--fixture",
            str(fixture_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
