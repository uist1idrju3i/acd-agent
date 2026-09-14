"""Tests for the deterministic responsibility-assignment gate."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast

from acd.core.rationale import check_rationale_coverage
from acd.core.responsibility_gate import check_responsibility
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode
from acd.schema.rationale import RationaleDocument
from acd.schema.responsibility import (
    ResponsibilityDeclaration,
    ResponsibilityGateResult,
    SharedAssignmentContract,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "responsibility"
    / "sample"
)


def _load() -> tuple[DesignGraph, ResponsibilityDeclaration]:
    graph = DesignGraph.model_validate_json(
        (FIXTURE / "graph.json").read_text(encoding="utf-8")
    )
    declaration = ResponsibilityDeclaration.model_validate_json(
        (FIXTURE / "responsibility.json").read_text(encoding="utf-8")
    )
    return graph, declaration


def _resp_node(node_id: str, attrs: dict[str, object]) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind="design.responsibility",
        attrs=cast(dict[str, AttrValue], attrs),
        depends_on=[],
    )


def _codes(result: ResponsibilityGateResult) -> set[str]:
    return {finding.code for finding in result.findings}


def test_fixture_passes() -> None:
    graph, declaration = _load()
    result = check_responsibility(graph, declaration)
    assert result.status == "pass"
    assert result.findings == []
    assert len(result.assignments) == 3
    assert result.gate == "responsibility_assignment"


def test_fixture_rationale_covers_domain_attrs() -> None:
    graph, _ = _load()
    document = RationaleDocument.model_validate_json(
        (FIXTURE / "rationale.json").read_text(encoding="utf-8")
    )
    assert check_rationale_coverage(graph, document).status == "pass"


def test_determinism_and_sorting() -> None:
    graph, declaration = _load()
    mutated = declaration.model_copy(update={"functions": []})
    first = check_responsibility(graph, mutated)
    second = check_responsibility(graph, mutated)
    assert first == second
    keys = [(f.code, f.subject) for f in first.findings]
    assert keys == sorted(keys)


def test_graph_mismatch_returns_immediately() -> None:
    graph, declaration = _load()
    mutated = declaration.model_copy(update={"revision": "r9"})
    result = check_responsibility(graph, mutated)
    assert result.status == "fail"
    assert [f.code for f in result.findings] == ["graph_mismatch"]
    assert result.assignments == []


def test_unassigned_function() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                n for n in graph.nodes if n.id != "resp.fn-alert-push"
            ]
        }
    )
    result = check_responsibility(g, declaration)
    assert "unassigned" in _codes(result)
    assert result.status == "fail"


def test_multiple_assignment_without_contract() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                _resp_node(
                    "resp.fn-measure-temp-2",
                    {
                        "function_id": "fn-measure-temp",
                        "domain": "pc_software",
                        "criteria": ["cost"],
                    },
                ),
            ]
        }
    )
    result = check_responsibility(g, declaration)
    assert "multiple_assignment" in _codes(result)


def test_multiple_assignment_with_contract_passes_check() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                _resp_node(
                    "resp.fn-measure-temp-2",
                    {
                        "function_id": "fn-measure-temp",
                        "domain": "pc_software",
                        "criteria": ["cost"],
                    },
                ),
            ]
        }
    )
    mutated = declaration.model_copy(
        update={
            "shared_assignments": [
                *declaration.shared_assignments,
                SharedAssignmentContract(
            function_id="fn-measure-temp",
            domains=["firmware", "pc_software"],
                    split="firmware samples, pc_software records",
                ),
            ]
        }
    )
    result = check_responsibility(g, mutated)
    assert "multiple_assignment" not in _codes(result)


def test_undeclared_function() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                _resp_node(
                    "resp.fn-ghost",
                    {
                        "function_id": "fn-ghost",
                        "domain": "firmware",
                        "criteria": ["cost"],
                    },
                ),
            ]
        }
    )
    result = check_responsibility(g, declaration)
    assert "undeclared_function" in _codes(result)


def test_invalid_domain() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                _resp_node(
                    "resp.fn-measure-temp-x",
                    {
                        "function_id": "fn-measure-temp",
                        "domain": "quantum",
                        "criteria": ["cost"],
                    },
                ),
            ]
        }
    )
    result = check_responsibility(g, declaration)
    assert "invalid_domain" in _codes(result)


def test_invalid_criteria() -> None:
    graph, declaration = _load()
    g = graph.model_copy(
        update={
            "nodes": [
                *graph.nodes,
                _resp_node(
                    "resp.fn-measure-temp-y",
                    {
                        "function_id": "fn-measure-temp",
                        "domain": "firmware",
                        "criteria": ["vibes"],
                    },
                ),
            ]
        }
    )
    result = check_responsibility(g, declaration)
    assert "invalid_criteria" in _codes(result)


def test_missing_capability() -> None:
    graph, declaration = _load()
    mutated = declaration.model_copy(
        update={
            "capabilities": [
                c
                for c in declaration.capabilities
                if c.domain != "mobile_app"
            ]
        }
    )
    result = check_responsibility(graph, mutated)
    assert "missing_capability" in _codes(result)


def test_unknown_state_on_need_side() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.functions[0] = mutated.functions[0].model_copy(
        update={"memory_kb": "unknown"}
    )
    result = check_responsibility(graph, mutated)
    assert "unknown_state" in _codes(result)


def test_unknown_state_on_capability_side() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.capabilities[0] = mutated.capabilities[0].model_copy(
        update={"gpio_count": "unknown"}
    )
    result = check_responsibility(graph, mutated)
    assert "unknown_state" in _codes(result)


def test_capability_conflict_memory() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.functions[0] = mutated.functions[0].model_copy(
        update={"memory_kb": 1024}
    )
    result = check_responsibility(graph, mutated)
    assert "capability_conflict" in _codes(result)


def test_capability_conflict_communication() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.functions[0] = mutated.functions[0].model_copy(
        update={"communication": ["can", "usb"]}
    )
    result = check_responsibility(graph, mutated)
    assert "capability_conflict" in _codes(result)


def test_capability_conflict_motion() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.functions[0] = mutated.functions[0].model_copy(
        update={"motion": True}
    )
    result = check_responsibility(graph, mutated)
    assert "capability_conflict" in _codes(result)


def test_missing_interface() -> None:
    graph, declaration = _load()
    mutated = declaration.model_copy(
        update={
            "interfaces": [
                i
                for i in declaration.interfaces
                if i.interface_id != "if.alert-push"
            ]
        }
    )
    result = check_responsibility(graph, mutated)
    assert "missing_interface" in _codes(result)


def test_one_sided_interface() -> None:
    graph, declaration = _load()
    mutated = copy.deepcopy(declaration)
    mutated.interfaces[0] = mutated.interfaces[0].model_copy(
        update={"declared_by": ["firmware"]}
    )
    result = check_responsibility(graph, mutated)
    assert "one_sided_interface" in _codes(result)



def test_cli(tmp_path: Path) -> None:
    import subprocess
    import sys

    out_dir = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_responsibility_assignment.py",
            "--graph", str(FIXTURE / "graph.json"),
            "--declaration", str(FIXTURE / "responsibility.json"),
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(
        (out_dir / "responsibility-gate.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "pass"
    evidence = json.loads(
        (out_dir / "gate-evidence" / "responsibility-assignment.json")
        .read_text(encoding="utf-8")
    )
    assert evidence["gate"] == "responsibility_assignment"
    assert evidence["status"] == "pass"


def test_cli_fails_on_bad_input(tmp_path: Path) -> None:
    import subprocess
    import sys

    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_responsibility_assignment.py",
            "--graph", str(FIXTURE / "graph.json"),
            "--declaration", str(bad),
            "--out-dir", str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1


def test_cli_exit_1_on_gate_fail(tmp_path: Path) -> None:
    import subprocess
    import sys

    declaration = json.loads(
        (FIXTURE / "responsibility.json").read_text(encoding="utf-8")
    )
    declaration["functions"] = declaration["functions"][:2]
    bad_decl = tmp_path / "responsibility.json"
    bad_decl.write_text(
        json.dumps(declaration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_responsibility_assignment.py",
            "--graph", str(FIXTURE / "graph.json"),
            "--declaration", str(bad_decl),
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    result = json.loads(
        (out_dir / "responsibility-gate.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "fail"
