"""Functional-block declarations and predicate contract resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.functional_block import (
    FunctionalBlockContract,
    FunctionalBlockRegistryDocument,
)


class FunctionalBlockContractError(ValueError):
    """Raised when functional-block applicability cannot be resolved safely."""


@dataclass(frozen=True)
class FunctionalBlockRegistry:
    document: FunctionalBlockRegistryDocument
    registry_hash: str
    path: Path

    @property
    def registry_id(self) -> str:
        return self.document.registry_id

    @property
    def contracts(self) -> list[FunctionalBlockContract]:
        return self.document.contracts


def load_functional_block_registry(path: Path | None = None) -> FunctionalBlockRegistry:
    registry_path = path or repository_root() / "contracts" / "functional-block-registry.json"
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
        document = FunctionalBlockRegistryDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FunctionalBlockContractError(
            f"functional block registry is invalid: {registry_path}: {exc}"
        ) from exc
    return FunctionalBlockRegistry(
        document=document,
        registry_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=registry_path,
    )


def validate_predicate_coverage(
    catalog: tuple[str, ...], registry: FunctionalBlockRegistry | None = None
) -> None:
    registry = registry or load_functional_block_registry()
    catalog_set = set(catalog)
    required = {
        predicate
        for contract in registry.contracts
        for predicate in contract.required_predicates
    }
    unknown = sorted(required - catalog_set)
    uncovered = sorted(catalog_set - required)
    if unknown or uncovered:
        details: list[str] = []
        if unknown:
            details.append(f"registry predicates absent from catalog: {', '.join(unknown)}")
        if uncovered:
            details.append(
                "catalog predicates absent from registry contracts: "
                + ", ".join(uncovered)
            )
        raise FunctionalBlockContractError("predicate coverage is invalid: " + "; ".join(details))


def declared_functional_blocks(
    graph: DesignGraph, registry: FunctionalBlockRegistry | None = None
) -> tuple[str, ...]:
    registry = registry or load_functional_block_registry()
    declarations = tuple(node for node in graph.nodes if node.kind == "design.functional_block")
    if not declarations:
        raise FunctionalBlockContractError(
            "functional block declarations are missing (applicability is unknown)"
        )
    known_nodes = {node.id: node for node in graph.nodes}
    by_id = {contract.block_id: contract for contract in registry.contracts}
    block_ids: list[str] = []
    for node in declarations:
        block_id = node.attrs.get("block_id")
        if not isinstance(block_id, str) or not block_id:
            raise FunctionalBlockContractError(
                f"functional block node {node.id!r} has an invalid block_id"
            )
        if block_id in block_ids:
            raise FunctionalBlockContractError(
                f"functional block {block_id!r} is declared more than once"
            )
        if block_id not in by_id:
            raise FunctionalBlockContractError(f"functional block {block_id!r} is not registered")
        if not node.depends_on or any(
            dependency not in known_nodes
            or known_nodes[dependency].kind != "requirement"
            for dependency in node.depends_on
        ):
            raise FunctionalBlockContractError(
                f"functional block node {node.id!r} must reference a driving requirement"
            )
        block_ids.append(block_id)
    declared = set(block_ids)
    missing_mandatory = sorted(
        contract.block_id
        for contract in registry.contracts
        if contract.mandatory and contract.block_id not in declared
    )
    if missing_mandatory:
        raise FunctionalBlockContractError(
            "mandatory functional blocks are not declared: " + ", ".join(missing_mandatory)
        )
    return tuple(sorted(block_ids))


def required_predicate_names(
    declared: tuple[str, ...], registry: FunctionalBlockRegistry | None = None
) -> frozenset[str]:
    registry = registry or load_functional_block_registry()
    contracts = {contract.block_id: contract for contract in registry.contracts}
    try:
        return frozenset(
            predicate
            for block_id in declared
            for predicate in contracts[block_id].required_predicates
        )
    except KeyError as exc:
        raise FunctionalBlockContractError(
            f"functional block {exc.args[0]!r} is not registered"
        ) from exc


__all__ = [
    "FunctionalBlockContractError",
    "FunctionalBlockRegistry",
    "declared_functional_blocks",
    "load_functional_block_registry",
    "required_predicate_names",
    "validate_predicate_coverage",
]
