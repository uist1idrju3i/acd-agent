"""Impact derivation: affected nodes, gates to rerun, and stale evidence.

Unknown node references widen the impact to the whole graph instead of
narrowing it (fail-closed).
"""

from __future__ import annotations

from typing import Literal

from acd_schema import DesignGraph, Evidence

GateKind = Literal[
    "erc",
    "drc",
    "dfm",
    "fw_build",
    "fw_static_analysis",
    "fw_unit_test",
    "pin_net_consistency",
    "review_disposition",
    "safety_boundary",
]

# Gates that must rerun when a node of the given kind is affected.
GATES_BY_NODE_KIND: dict[str, tuple[GateKind, ...]] = {
    "requirement": (
        "erc",
        "drc",
        "fw_build",
        "fw_static_analysis",
        "fw_unit_test",
        "pin_net_consistency",
        "review_disposition",
        "safety_boundary",
    ),
    "electrical.net": ("erc", "drc", "pin_net_consistency", "safety_boundary"),
    "electrical.component": ("erc", "drc", "pin_net_consistency"),
    "electrical.board": ("drc", "review_disposition"),
    "fab.order_intent": ("drc", "dfm", "review_disposition"),
    "fab.process_allowance": ("drc", "dfm", "review_disposition"),
    "electrical.pin": ("erc", "drc", "pin_net_consistency"),
    "firmware.module": ("fw_build", "fw_static_analysis", "fw_unit_test"),
    "firmware.pin_assignment": (
        "fw_build",
        "fw_static_analysis",
        "fw_unit_test",
        "pin_net_consistency",
    ),
    "safety.boundary": ("safety_boundary",),
    "evidence.anchor": (),
}


def affected_node_ids(graph: DesignGraph, changed_ids: set[str]) -> set[str]:
    """Changed nodes plus all transitive dependents.

    A changed id not present in the graph (for example a removed node) widens
    the impact to every node in the graph.
    """
    known = {node.id for node in graph.nodes}
    if not changed_ids <= known:
        return known | changed_ids
    dependents: dict[str, set[str]] = {node_id: set() for node_id in known}
    for node in graph.nodes:
        for dep in node.depends_on:
            dependents[dep].add(node.id)
    affected = set(changed_ids)
    frontier = list(changed_ids)
    while frontier:
        current = frontier.pop()
        for dependent in dependents[current]:
            if dependent not in affected:
                affected.add(dependent)
                frontier.append(dependent)
    return affected


def gates_to_rerun(graph: DesignGraph, affected_ids: set[str]) -> set[GateKind]:
    """Gate kinds that must rerun for the affected nodes.

    Affected ids missing from the graph widen the rerun set to all gates.
    """
    all_gates: set[GateKind] = set()
    for kinds in GATES_BY_NODE_KIND.values():
        all_gates.update(kinds)
    known = {node.id: node for node in graph.nodes}
    if not affected_ids <= set(known):
        return all_gates
    rerun: set[GateKind] = set()
    for node_id in affected_ids:
        rerun.update(GATES_BY_NODE_KIND[known[node_id].kind])
    return rerun


def stale_evidence_ids(
    evidence_records: list[Evidence],
    current_revision: str,
    affected_ids: set[str],
) -> set[str]:
    """Evidence that no longer supports pass verdicts.

    Evidence is stale when its target revision is not the current one, when it
    claims properties of an affected node, or when it is already non-valid.
    """
    stale: set[str] = set()
    for evidence in evidence_records:
        if evidence.status != "valid":
            stale.add(evidence.evidence_id)
            continue
        if evidence.target_revision != current_revision:
            stale.add(evidence.evidence_id)
            continue
        if any(claim.subject_node in affected_ids for claim in evidence.claims):
            stale.add(evidence.evidence_id)
    return stale
