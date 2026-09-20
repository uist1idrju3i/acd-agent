"""Apply fail-closed, deterministic rework differences to design graphs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acd.core.runtime.fileio import read_json
from acd.schema.common import canonical_json_sha256, canonical_sha256
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode
from acd.schema.rework_diff import (
    ReworkAdd,
    ReworkCut,
    ReworkDiff,
    ReworkMechanical,
    ReworkRemove,
    ReworkReplace,
)


class ReworkDiffError(ValueError):
    """Raised when a rework difference cannot be loaded or applied."""


@dataclass(frozen=True)
class LoadedReworkDiff:
    diff: ReworkDiff
    diff_hash: str
    path: Path


@dataclass(frozen=True)
class DerivedGraph:
    graph: DesignGraph
    base_graph_hash: str
    diff_hash: str
    derived_revision: str
    safety_boundary_touched: bool
    touched_node_ids: tuple[str, ...]
    base_graph_path: Path | None = None


def load_rework_diff(path: Path) -> LoadedReworkDiff:
    try:
        diff = ReworkDiff.model_validate(read_json(path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReworkDiffError(f"rework diff is invalid: {path}: {exc}") from exc
    return LoadedReworkDiff(
        diff=diff,
        diff_hash=canonical_sha256(diff),
        path=path,
    )


def _node_map(nodes: list[GraphNode]) -> dict[str, GraphNode]:
    return {node.id: node for node in nodes}


def _replace_node(
    node: GraphNode,
    *,
    attrs: dict[str, AttrValue] | None = None,
    depends_on: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        id=node.id,
        kind=node.kind,
        attrs=attrs if attrs is not None else dict(node.attrs),
        depends_on=depends_on if depends_on is not None else list(node.depends_on),
    )


def _is_number(value: AttrValue) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _power_nets(nodes: dict[str, GraphNode]) -> set[str]:
    return {
        node.id
        for node in nodes.values()
        if node.kind == "electrical.net" and node.attrs.get("power_rail") is True
    }


def _component_power_touched(
    node: GraphNode, nodes: dict[str, GraphNode], power_nets: set[str]
) -> bool:
    if node.kind != "electrical.component":
        return False
    return any(
        pin.attrs.get("net") in power_nets
        for pin in nodes.values()
        if pin.kind == "electrical.pin" and pin.attrs.get("component") == node.id
    )


def _safety_related_ids(nodes: dict[str, GraphNode]) -> frozenset[str]:
    power_nets = _power_nets(nodes)
    boundary_dependencies = {
        dependency
        for node in nodes.values()
        if node.kind == "safety.boundary"
        for dependency in node.depends_on
    }
    related = {
        node.id
        for node in nodes.values()
        if (
            node.kind == "safety.boundary"
            or node.id in boundary_dependencies
            or (node.kind == "electrical.net" and node.id in power_nets)
            or (node.kind == "electrical.pin" and node.attrs.get("net") in power_nets)
            or _component_power_touched(node, nodes, power_nets)
        )
    }
    return frozenset(related)


def safety_related_node_ids(graph: DesignGraph) -> frozenset[str]:
    """Return graph nodes conservatively related to a safety boundary."""
    return _safety_related_ids(_node_map(list(graph.nodes)))


def _safety_touched(touched_ids: set[str], nodes: dict[str, GraphNode]) -> bool:
    return bool(touched_ids & _safety_related_ids(nodes))


def _apply_cut(
    operation: ReworkCut,
    nodes: dict[str, GraphNode],
    touched: set[str],
) -> None:
    node = nodes.get(operation.pin_id)
    if node is None:
        raise ReworkDiffError(f"cut pin does not exist: {operation.pin_id}")
    if node.kind != "electrical.pin":
        raise ReworkDiffError(f"cut target is not an electrical pin: {operation.pin_id}")
    net = node.attrs.get("net")
    if not isinstance(net, str) or node.attrs.get("no_connect") is not False:
        raise ReworkDiffError(f"cut pin is already disconnected: {operation.pin_id}")
    if net not in nodes or nodes[net].kind != "electrical.net":
        raise ReworkDiffError(f"cut pin has an invalid net reference: {operation.pin_id}")
    attrs = dict(node.attrs)
    attrs["net"] = None
    attrs["no_connect"] = True
    nodes[operation.pin_id] = _replace_node(
        node,
        attrs=attrs,
        depends_on=[dependency for dependency in node.depends_on if dependency != net],
    )
    touched.add(operation.pin_id)


def _apply_add(
    operation: ReworkAdd,
    nodes: dict[str, GraphNode],
    touched: set[str],
) -> None:
    node = operation.node
    if node.id in nodes:
        raise ReworkDiffError(f"added node already exists: {node.id}")
    missing = sorted(set(node.depends_on) - set(nodes))
    if missing:
        raise ReworkDiffError(
            f"added node {node.id} depends on unknown nodes: {', '.join(missing)}"
        )
    if node.kind == "electrical.pin":
        component = node.attrs.get("component")
        net = node.attrs.get("net")
        if (
            not isinstance(component, str)
            or component not in nodes
            or nodes[component].kind != "electrical.component"
            or not isinstance(net, str)
            or net not in nodes
            or nodes[net].kind != "electrical.net"
        ):
            raise ReworkDiffError(
                f"added electrical pin {node.id} requires existing component and net"
            )
    nodes[node.id] = node
    touched.add(node.id)


def _apply_remove(
    operation: ReworkRemove,
    nodes: dict[str, GraphNode],
    touched: set[str],
) -> None:
    component = nodes.get(operation.component_id)
    if component is None:
        raise ReworkDiffError(f"remove component does not exist: {operation.component_id}")
    if component.kind != "electrical.component":
        raise ReworkDiffError(
            f"remove target is not an electrical component: {operation.component_id}"
        )
    removed = {
        node.id
        for node in nodes.values()
        if node.id == operation.component_id
        or (node.kind == "electrical.pin" and node.attrs.get("component") == operation.component_id)
        or (node.kind == "mechanical.component_body" and operation.component_id in node.depends_on)
    }
    remaining = {node.id: node for node in nodes.values() if node.id not in removed}
    dangling = sorted(node.id for node in remaining.values() if set(node.depends_on) & removed)
    if dangling:
        raise ReworkDiffError(
            "removing component would leave dangling dependencies: " + ", ".join(dangling)
        )
    nodes.clear()
    nodes.update(remaining)
    touched.update(removed)


def _apply_replace(
    operation: ReworkReplace,
    nodes: dict[str, GraphNode],
    touched: set[str],
) -> None:
    node = nodes.get(operation.component_id)
    if node is None or node.kind != "electrical.component":
        raise ReworkDiffError(
            f"replace target is not an electrical component: {operation.component_id}"
        )
    if all(node.attrs.get(key) == value for key, value in operation.attrs.items()):
        raise ReworkDiffError("replace operation does not change any attribute")
    attrs = dict(node.attrs)
    attrs.update(operation.attrs)
    nodes[operation.component_id] = _replace_node(node, attrs=attrs)
    touched.add(operation.component_id)


def _apply_mechanical(
    operation: ReworkMechanical,
    nodes: dict[str, GraphNode],
    touched: set[str],
) -> None:
    node = nodes.get(operation.target_id)
    if node is None or node.kind not in {
        "mechanical.enclosure",
        "mechanical.connector_opening",
        "mechanical.outline",
    }:
        raise ReworkDiffError(
            f"mechanical target is not an allowed existing node: {operation.target_id}"
        )
    for key, value in operation.attrs.items():
        current = node.attrs.get(key)
        if key not in node.attrs or not _is_number(current) or not _is_number(value):
            raise ReworkDiffError(f"mechanical attribute {key!r} must already exist as numeric")
    attrs = dict(node.attrs)
    attrs.update(operation.attrs)
    nodes[operation.target_id] = _replace_node(node, attrs=attrs)
    touched.add(operation.target_id)


def apply_rework_diff(
    graph: DesignGraph,
    diff: ReworkDiff,
    *,
    graph_path: Path | None = None,
) -> DerivedGraph:
    """Apply operations in declaration order without mutating the base graph."""
    if graph.graph_id != diff.graph_id:
        raise ReworkDiffError(
            f"rework graph_id {diff.graph_id!r} does not match {graph.graph_id!r}"
        )
    if graph.revision != diff.base_revision:
        raise ReworkDiffError(
            f"rework base revision {diff.base_revision!r} does not match {graph.revision!r}"
        )
    nodes = _node_map(
        [GraphNode.model_validate(node.model_dump(mode="json")) for node in graph.nodes]
    )
    original_nodes = dict(nodes)
    touched: set[str] = set()
    for operation in diff.operations:
        if isinstance(operation, ReworkCut):
            _apply_cut(operation, nodes, touched)
        elif isinstance(operation, ReworkAdd):
            _apply_add(operation, nodes, touched)
        elif isinstance(operation, ReworkRemove):
            _apply_remove(operation, nodes, touched)
        elif isinstance(operation, ReworkReplace):
            _apply_replace(operation, nodes, touched)
        else:
            _apply_mechanical(operation, nodes, touched)

    safety_nodes = dict(original_nodes)
    safety_nodes.update(
        {node_id: node for node_id, node in nodes.items() if node_id not in original_nodes}
    )
    touched_safety = _safety_touched(touched, safety_nodes)
    if touched_safety and not diff.touches_safety_boundary:
        raise ReworkDiffError("safety boundary touched but not declared")

    derived = DesignGraph.model_validate(
        {
            "schema_version": graph.schema_version,
            "graph_id": graph.graph_id,
            "revision": diff.derived_revision,
            "nodes": [node.model_dump(mode="json") for node in nodes.values()],
        }
    )
    return DerivedGraph(
        graph=derived,
        base_graph_hash=canonical_sha256(graph),
        diff_hash=canonical_sha256(diff),
        derived_revision=diff.derived_revision,
        safety_boundary_touched=touched_safety,
        touched_node_ids=tuple(sorted(touched)),
        base_graph_path=graph_path,
    )


def write_derived_graph(derived: DerivedGraph, out_dir: Path) -> Path:
    """Write an L3 derived graph projection and its provenance."""
    output_dir = out_dir.resolve()
    if derived.base_graph_path is not None:
        base_parent = derived.base_graph_path.resolve().parent
        if output_dir == base_parent or base_parent in output_dir.parents:
            raise ReworkDiffError(
                "derived graph output must not be inside the base graph directory"
            )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        graph_path = output_dir / "derived-graph.json"
        provenance_path = output_dir / "derived-graph.provenance.json"
        graph_payload = derived.graph.model_dump(mode="json")
        graph_path.write_text(
            json.dumps(graph_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        derived_hash = canonical_json_sha256(graph_payload)
        provenance = {
            "artifact_kind": "rework_derived_graph",
            "pass_evidence": False,
            "record_class": "L3",
            "base_graph_sha256": derived.base_graph_hash,
            "rework_diff_sha256": derived.diff_hash,
            "derived_graph_sha256": derived_hash,
            "derived_revision": derived.derived_revision,
            "touched_node_ids": list(derived.touched_node_ids),
            "safety_boundary_touched": derived.safety_boundary_touched,
            "tool": "acd.core.manufacturing.rework_diff",
            "acd_version": "0.0.2",
        }
        provenance_path.write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ReworkDiffError(f"cannot write derived graph: {output_dir}: {exc}") from exc
    return graph_path


__all__ = [
    "DerivedGraph",
    "LoadedReworkDiff",
    "ReworkDiffError",
    "apply_rework_diff",
    "load_rework_diff",
    "safety_related_node_ids",
    "write_derived_graph",
]
