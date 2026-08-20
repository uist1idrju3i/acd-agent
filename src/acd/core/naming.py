"""Deterministic output naming derived from the Design Graph.

Output prefixes, firmware project names and Evidence subject nodes are derived
from the graph instead of a fixed project name. Every derivation is
fail-closed: an undeclared or unsafe ``graph_id`` stops the pipeline rather
than falling back to a default name.
"""

from __future__ import annotations

import re

from acd.schema.design_graph import DesignGraph, NodeKind

__all__ = [
    "firmware_project_name",
    "output_prefix",
    "subject_node_id",
]

_OUTPUT_PREFIX_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")


def output_prefix(graph_id: str) -> str:
    """Return the deterministic output file prefix for a Design Graph id."""
    normalized = _SEPARATOR_PATTERN.sub("-", graph_id.strip().lower()).strip("-")
    if not normalized or not _OUTPUT_PREFIX_PATTERN.fullmatch(normalized):
        raise ValueError(f"graph_id does not yield an output prefix: {graph_id!r}")
    return normalized


def firmware_project_name(graph_id: str) -> str:
    """Return the ESP-IDF project name for a Design Graph id."""
    return "acd_" + output_prefix(graph_id).replace("-", "_") + "_fw"


def subject_node_id(graph: DesignGraph, kind: NodeKind) -> str:
    """Return the single graph node id of ``kind`` used as Evidence subject."""
    identifiers = sorted(node.id for node in graph.nodes if node.kind == kind)
    if len(identifiers) != 1:
        raise ValueError(
            f"graph declares {len(identifiers)} {kind} nodes; "
            "an Evidence subject node cannot be derived"
        )
    return identifiers[0]
