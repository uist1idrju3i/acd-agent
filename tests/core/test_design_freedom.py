"""Design-freedom declaration and alignment tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.design_freedom import (
    DesignFreedomDeclarationError,
    design_freedom_dimension,
    load_design_freedom_declaration,
    searchable_dimensions,
    validate_change_dimension_alignment,
)
from acd.core.functional_blocks import (
    FunctionalBlockRegistry,
    load_functional_block_registry,
)
from acd.schema.functional_block import FunctionalBlockContract

ROOT = Path(__file__).resolve().parents[2]


def test_real_design_freedom_declaration_loads_and_is_deterministic() -> None:
    declaration = load_design_freedom_declaration()
    assert len(declaration.document.dimensions) == 9
    assert searchable_dimensions(declaration) == (
        "clearance_mm",
        "component_placement_xy",
        "component_rotation_deg",
        "gpio_assignment",
        "router_max_passes",
        "track_width_mm",
        "via_rule",
    )
    assert design_freedom_dimension("component_placement_xy", declaration).search_enabled


def test_alignment_passes_for_real_registry() -> None:
    validate_change_dimension_alignment(
        load_design_freedom_declaration(),
        load_functional_block_registry(),
    )


def test_alignment_rejects_undeclared_dimension(tmp_path: Path) -> None:
    declaration = load_design_freedom_declaration()
    registry = load_functional_block_registry()
    contract = FunctionalBlockContract(
        block_id="test_block",
        title="Test block",
        description="Test block",
        required_predicates=["power_boundary"],
        allowed_change_dimensions=["component_placement_xy"],
    )
    invalid_contract = contract.model_copy(
        update={"allowed_change_dimensions": ["undeclared_dimension"]}
    )
    changed_registry = FunctionalBlockRegistry(
        document=registry.document.model_copy(
            update={"contracts": [*registry.document.contracts, invalid_contract]}
        ),
        registry_hash=registry.registry_hash,
        path=registry.path,
    )
    with pytest.raises(DesignFreedomDeclarationError):
        validate_change_dimension_alignment(declaration, changed_registry)


def test_alignment_rejects_disabled_dimension() -> None:
    declaration = load_design_freedom_declaration()
    registry = load_functional_block_registry()
    contract = FunctionalBlockContract(
        block_id="test_block",
        title="Test block",
        description="Test block",
        required_predicates=["power_boundary"],
        allowed_change_dimensions=["copper_layer_count"],
    )
    changed_registry = FunctionalBlockRegistry(
        document=registry.document.model_copy(
            update={"contracts": [*registry.document.contracts, contract]}
        ),
        registry_hash=registry.registry_hash,
        path=registry.path,
    )
    with pytest.raises(DesignFreedomDeclarationError):
        validate_change_dimension_alignment(declaration, changed_registry)


def test_loader_fails_closed_on_missing_or_corrupt_file(tmp_path: Path) -> None:
    with pytest.raises(DesignFreedomDeclarationError):
        load_design_freedom_declaration(tmp_path / "missing.json")
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    with pytest.raises(DesignFreedomDeclarationError):
        load_design_freedom_declaration(corrupt)
