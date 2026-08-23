"""Requirement compiler tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from acd.core.requirement_compiler import (
    RequirementCompilationError,
    compile_requirement_change,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1"


def _copy_fixture(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    destination = tmp_path / "fixture"
    shutil.copytree(FIXTURE, destination)
    return destination


def _update(
    tmp_path: Path, *, gpio: int = 6, statement: str = "LEDはIO6へ移動する"
) -> Path:
    path = tmp_path / "requirement.json"
    path.write_text(
        json.dumps(
            {
                "requirement_id": "gd1-req-010",
                "statement": statement,
                "drives_functional_blocks": ["esp32c3_strapping_boot"],
                "constrains_node_ids": [],
                "constrains_node_kinds": [],
                "expectation": {"kind": "gpio_assignment", "net": "LED", "gpio": gpio},
                "graph_anchored": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_gpio_requirement_change_updates_coupled_nodes(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    result = compile_requirement_change(fixture, _update(tmp_path))
    graph = json.loads((fixture / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["fw.pin.led"]["attrs"]["gpio"] == 6
    assert nodes["pin.u1.20"]["attrs"]["net"] == "net.led"
    assert nodes["pin.u1.21"]["attrs"]["no_connect"] is True
    assert nodes["comp.tp5"]["attrs"]["value"] == "TP_IO6"
    assert nodes["req.gd1-req-010"]["attrs"]["text"] == "LEDはIO6へ移動する"
    assert result.report["pass_evidence"] is False
    assert "fw.pin.led" in result.report["changed_node_ids"]


def test_requirement_compilation_is_deterministic(tmp_path: Path) -> None:
    first = _copy_fixture(tmp_path / "one")
    second = _copy_fixture(tmp_path / "two")
    first_result = compile_requirement_change(first, _update(tmp_path / "one"))
    second_result = compile_requirement_change(second, _update(tmp_path / "two"))
    assert {
        key: value
        for key, value in first_result.report.items()
        if key != "provenance"
    } == {
        key: value
        for key, value in second_result.report.items()
        if key != "provenance"
    }
    assert (first / "graph.json").read_bytes() == (second / "graph.json").read_bytes()
    assert (first / "rationale.json").read_bytes() == (second / "rationale.json").read_bytes()


def test_unknown_expectation_does_not_write(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    update = _update(tmp_path)
    payload = json.loads(update.read_text(encoding="utf-8"))
    payload["expectation"]["kind"] = "unsupported"
    update.write_text(json.dumps(payload), encoding="utf-8")
    before = {
        name: (fixture / name).read_bytes()
        for name in ("graph.json", "requirements.json", "rationale.json")
    }
    with pytest.raises(RequirementCompilationError, match="unknown expectation"):
        compile_requirement_change(fixture, update)
    assert before == {
        name: (fixture / name).read_bytes()
        for name in ("graph.json", "requirements.json", "rationale.json")
    }


def test_missing_coupled_requirement_node_fails_without_write(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    graph_path = fixture / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"] = [
        node for node in graph["nodes"] if node["id"] != "req.gd1-req-010"
    ]
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    before = graph_path.read_bytes()
    with pytest.raises(RequirementCompilationError):
        compile_requirement_change(fixture, _update(tmp_path))
    assert graph_path.read_bytes() == before


def test_text_only_requirement_update_uses_existing_expectation(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    update = _update(tmp_path, statement="LED要件の説明を更新")
    payload = json.loads(update.read_text(encoding="utf-8"))
    payload["expectation"] = None
    update.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = compile_requirement_change(fixture, update, dry_run=True)
    assert result.report["status"] == "dry_run"
