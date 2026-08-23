"""Loading and validating conversation-derived requirements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acd.core.functional_blocks import (
    FunctionalBlockRegistry,
    load_functional_block_registry,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.requirement import RequirementDocument


class RequirementError(ValueError):
    """Raised when requirements cannot be resolved safely."""


@dataclass(frozen=True)
class LoadedRequirements:
    document: RequirementDocument
    document_hash: str
    path: Path


def load_requirements(path: Path) -> LoadedRequirements:
    """Load and validate a requirement document."""
    try:
        document = RequirementDocument.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RequirementError(f"requirements document is invalid: {path}: {exc}") from exc
    return LoadedRequirements(
        document=document,
        document_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=path,
    )


def validate_requirements(
    document: RequirementDocument,
    graph: DesignGraph | None = None,
    registry: FunctionalBlockRegistry | None = None,
) -> None:
    """Validate links to the graph and functional-block registry fail-closed."""
    loaded_registry = registry or load_functional_block_registry()
    known_blocks = {contract.block_id for contract in loaded_registry.contracts}
    unknown_blocks = sorted(
        {
            block_id
            for record in document.records
            for block_id in record.drives_functional_blocks
            if block_id not in known_blocks
        }
    )
    if unknown_blocks:
        raise RequirementError(
            "requirements reference unknown functional blocks: "
            + ", ".join(unknown_blocks)
        )
    if graph is None:
        return
    if document.graph_id != graph.graph_id or document.revision != graph.revision:
        raise RequirementError("requirements graph_id or revision does not match graph")
    known_nodes = {node.id: node for node in graph.nodes}
    for record in document.records:
        missing = sorted(set(record.constrains_node_ids) - known_nodes.keys())
        if missing:
            raise RequirementError(
                f"requirement {record.requirement_id!r} references unknown graph nodes: "
                + ", ".join(missing)
            )
        expected_kinds = set(record.constrains_node_kinds)
        actual_kinds = {known_nodes[node_id].kind for node_id in record.constrains_node_ids}
        if not actual_kinds.issubset(expected_kinds) and expected_kinds:
            raise RequirementError(
                f"requirement {record.requirement_id!r} constrains nodes outside declared kinds"
            )
    validate_requirement_graph_consistency(document, graph)


def validate_requirement_graph_consistency(
    document: RequirementDocument, graph: DesignGraph
) -> None:
    """Require graph-anchored records and ``req.*`` nodes to agree exactly."""
    records_by_id = {
        f"req.{record.requirement_id}": record
        for record in document.records
        if record.graph_anchored
    }
    graph_requirements = {
        node.id: node
        for node in graph.nodes
        if node.kind == "requirement" and node.id.startswith("req.")
    }
    missing = sorted(set(records_by_id) - set(graph_requirements))
    extra = sorted(set(graph_requirements) - set(records_by_id))
    if missing or extra:
        detail: list[str] = []
        if missing:
            detail.append("missing graph nodes: " + ", ".join(missing))
        if extra:
            detail.append("unlinked graph nodes: " + ", ".join(extra))
        raise RequirementError("requirement graph consistency failed: " + "; ".join(detail))
    mismatches = sorted(
        node_id
        for node_id, record in records_by_id.items()
        if graph_requirements[node_id].attrs.get("text") != record.statement
    )
    if mismatches:
        raise RequirementError(
            "requirement graph text mismatch: " + ", ".join(mismatches)
        )


def default_requirements_path(fixture_dir: Path) -> Path:
    return fixture_dir / "requirements.json"


__all__ = [
    "LoadedRequirements",
    "RequirementError",
    "default_requirements_path",
    "load_requirements",
    "validate_requirement_graph_consistency",
    "validate_requirements",
]
