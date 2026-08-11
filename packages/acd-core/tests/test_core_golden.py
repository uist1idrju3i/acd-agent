"""Golden task for acd-core using the tracked design-graph fixture.

Scenario: change the LED drive net, verify revision bump, affected-node
derivation, gate rerun derivation, and evidence invalidation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd_core import (
    GraphPatch,
    RevisionMismatchError,
    affected_node_ids,
    apply_patch,
    gates_to_rerun,
    next_revision,
    revision_number,
    stale_evidence_ids,
)
from acd_schema import DesignGraph, Evidence

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "contracts" / "valid"


def load_graph() -> DesignGraph:
    data = json.loads((FIXTURES / "design-graph.json").read_text(encoding="utf-8"))
    return DesignGraph.model_validate(data)


def load_evidence() -> Evidence:
    data = json.loads((FIXTURES / "evidence.json").read_text(encoding="utf-8"))
    return Evidence.model_validate(data)


def test_revision_parsing_and_increment() -> None:
    assert revision_number("r3") == 3
    assert next_revision("r3") == "r4"
    with pytest.raises(ValueError, match="invalid revision"):
        revision_number("latest")


def test_golden_patch_and_impact() -> None:
    graph = load_graph()
    patch = GraphPatch.model_validate(
        {
            "base_revision": "r3",
            "ops": [
                {"op": "set_attrs", "node_id": "net.led_drive", "attrs": {"width_mm": 0.3}}
            ],
        }
    )
    new_graph = apply_patch(graph, patch)
    assert new_graph.revision == "r4"
    assert new_graph.node_by_id("net.led_drive").attrs["width_mm"] == 0.3

    affected = affected_node_ids(new_graph, patch.changed_node_ids())
    assert affected == {"net.led_drive", "pin.mcu_pa4", "fw.pin_pa4", "sb.max_voltage"}

    rerun = gates_to_rerun(new_graph, affected)
    assert rerun == {
        "erc",
        "drc",
        "pin_net_consistency",
        "safety_boundary",
        "fw_build",
        "fw_static_analysis",
        "fw_unit_test",
    }

    evidence = load_evidence()  # targets r3, claims about net.led_drive
    stale = stale_evidence_ids([evidence], new_graph.revision, affected)
    assert stale == {evidence.evidence_id}


def test_patch_revision_mismatch_is_rejected() -> None:
    graph = load_graph()
    patch = GraphPatch.model_validate(
        {
            "base_revision": "r2",
            "ops": [{"op": "remove_node", "node_id": "sb.max_voltage"}],
        }
    )
    with pytest.raises(RevisionMismatchError):
        apply_patch(graph, patch)


def test_patch_on_missing_node_is_rejected() -> None:
    graph = load_graph()
    patch = GraphPatch.model_validate(
        {
            "base_revision": "r3",
            "ops": [{"op": "set_attrs", "node_id": "no.such_node", "attrs": {"x": 1}}],
        }
    )
    with pytest.raises(ValueError, match="does not exist"):
        apply_patch(graph, patch)


def test_removed_node_widens_impact_to_whole_graph() -> None:
    graph = load_graph()
    all_ids = {node.id for node in graph.nodes}
    affected = affected_node_ids(graph, {"ghost.node"})
    assert affected == all_ids | {"ghost.node"}
    assert gates_to_rerun(graph, affected) == {
        "erc",
        "drc",
        "fw_build",
        "fw_static_analysis",
        "fw_unit_test",
        "pin_net_consistency",
        "review_disposition",
        "safety_boundary",
    }


def test_non_valid_and_revision_mismatched_evidence_is_stale() -> None:
    evidence = load_evidence()
    assert stale_evidence_ids([evidence], "r4", set()) == {evidence.evidence_id}
    unknown = evidence.model_copy(update={"status": "unknown"})
    assert stale_evidence_ids([unknown], "r3", set()) == {evidence.evidence_id}
    assert stale_evidence_ids([evidence], "r3", set()) == set()
