"""Functional-block applicability and fail-closed contract tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from acd.core.design_predicates import (
    PREDICATE_CATALOG,
    PredicateResult,
    evaluate_design_predicates,
)
from acd.core.electrical import extract_electrical_lane
from acd.core.functional_blocks import (
    FunctionalBlockContractError,
    declared_functional_blocks,
    load_functional_block_registry,
    validate_predicate_coverage,
)
from acd.schema import DesignGraph, FunctionalBlockContract

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "fixtures" / "golden-design-1"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads((FIXTURE_DIR / "graph.json").read_text(encoding="utf-8"))
    )


def _without_blocks(graph: DesignGraph, block_ids: set[str]) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node
                for node in graph.nodes
                if node.attrs.get("block_id") not in block_ids
            ]
        }
    )


def _skip_if_gd1_geometry_library_is_missing(graph: DesignGraph) -> None:
    lane = extract_electrical_lane(graph)
    required_refs = {"C3", "C4", "C5", "U1", "U2", "U3"}
    for component in lane.components:
        if component.refdes not in required_refs:
            continue
        path = Path(component.library.footprint_file)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        if not path.is_file():
            pytest.skip(f"pinned KiCad library not present in this environment: {path}")


def _assert_predicates_pass(results: Iterable[PredicateResult]) -> None:
    failures = [
        f"{result.name}: status={result.status!r}, detail={result.detail}"
        for result in results
        if result.status != "pass"
    ]
    assert not failures, "unexpected predicate results: " + "; ".join(failures)


def _without_all_functional_blocks(graph: DesignGraph) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node
                for node in graph.nodes
                if node.kind != "design.functional_block"
            ]
        }
    )


def _replace_i2c_block_id(graph: DesignGraph) -> DesignGraph:
    return _replace_block_id(graph, "unknown_block")


def _replace_block_id(graph: DesignGraph, block_id: str) -> DesignGraph:
    return graph.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, "block_id": block_id}})
                if node.kind == "design.functional_block"
                and node.attrs.get("block_id") == "i2c_bus_pullup"
                else node
                for node in graph.nodes
            ]
        }
    )


def _without_safety_power_boundary(graph: DesignGraph) -> DesignGraph:
    return _without_blocks(graph, {"safety_power_boundary"})


TRANSFORMS: list[Callable[[DesignGraph], DesignGraph]] = [
    _without_all_functional_blocks,
    _replace_i2c_block_id,
    _without_safety_power_boundary,
]


def test_all_gd1_functional_blocks_are_declared() -> None:
    declared = declared_functional_blocks(_graph())
    assert declared == (
        "esp32c3_strapping_boot",
        "firmware_pin_map",
        "i2c_bus_pullup",
        "safety_power_boundary",
        "single_ldo_power_tree",
        "usb_c_cc_termination",
    )


def test_removing_i2c_declaration_is_not_applicable_only_for_i2c() -> None:
    graph = _without_blocks(_graph(), {"i2c_bus_pullup"})
    _skip_if_gd1_geometry_library_is_missing(graph)
    lane = extract_electrical_lane(graph)
    results = evaluate_design_predicates(graph, lane, FIXTURE_DIR)
    assert results[1].status == "not_applicable"
    _assert_predicates_pass(result for result in results if result.name != "i2c_pullup")


def test_i2c_declaration_with_missing_net_remains_unknown() -> None:
    graph = _graph().model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": {**node.attrs, "name": "MISSING"}})
                if node.kind == "electrical.net"
                and node.attrs.get("name") == "I2C_SDA"
                else node
                for node in _graph().nodes
            ]
        }
    )
    lane = extract_electrical_lane(graph)
    results = evaluate_design_predicates(graph, lane, FIXTURE_DIR)
    assert results[1].status == "unknown"


@pytest.mark.parametrize(
    "transform",
    TRANSFORMS,
)
def test_invalid_functional_block_declarations_fail_closed(
    transform: Callable[[DesignGraph], DesignGraph],
) -> None:
    with pytest.raises(FunctionalBlockContractError):
        declared_functional_blocks(transform(_graph()))


def test_registry_predicate_coverage_gaps_fail_closed(tmp_path: Path) -> None:
    registry = load_functional_block_registry()
    incomplete = registry.document.model_copy(
        update={
            "contracts": [
                contract
                for contract in registry.document.contracts
                if "i2c_pullup" not in contract.required_predicates
            ]
        }
    )
    path = tmp_path / "registry.json"
    path.write_text(incomplete.model_dump_json(), encoding="utf-8")
    with pytest.raises(FunctionalBlockContractError):
        validate_predicate_coverage(
            PREDICATE_CATALOG,
            load_functional_block_registry(path),
        )


def test_topology_without_usb_and_i2c_blocks_uses_other_contracts() -> None:
    graph = _without_blocks(
        _graph(),
        {"usb_c_cc_termination", "i2c_bus_pullup"},
    )
    _skip_if_gd1_geometry_library_is_missing(graph)
    lane = extract_electrical_lane(graph)
    results = evaluate_design_predicates(graph, lane, FIXTURE_DIR)
    assert results[0].status == "not_applicable"
    assert results[1].status == "not_applicable"
    _assert_predicates_pass(results[2:])


def test_new_topology_contract_extends_applicability_without_predicate_changes(
    tmp_path: Path,
) -> None:
    registry = load_functional_block_registry()
    extended = registry.document.model_copy(
        update={
            "contracts": [
                *registry.document.contracts,
                FunctionalBlockContract(
                    block_id="alternate_i2c_bus_pullup",
                    title="Alternate I2C bus pull-up",
                    description="Applies the existing I2C pull-up predicate to another topology.",
                    required_predicates=["i2c_pullup"],
                ),
            ]
        }
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(extended.model_dump_json(), encoding="utf-8")
    alternate_registry = load_functional_block_registry(registry_path)
    graph = _replace_block_id(_graph(), "alternate_i2c_bus_pullup")
    lane = extract_electrical_lane(graph)
    results = evaluate_design_predicates(
        graph,
        lane,
        FIXTURE_DIR,
        alternate_registry,
    )
    assert results[1].name == "i2c_pullup"
    assert results[1].status == "pass"
