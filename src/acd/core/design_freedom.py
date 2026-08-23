"""Design-freedom declarations and fail-closed consistency checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acd.core.functional_blocks import (
    FunctionalBlockRegistry,
    load_functional_block_registry,
)
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.design_freedom import (
    DesignFreedomDeclarationDocument,
    DesignFreedomDimension,
)


class DesignFreedomDeclarationError(ValueError):
    """Raised when design-freedom applicability cannot be resolved safely."""


@dataclass(frozen=True)
class DesignFreedomDeclaration:
    document: DesignFreedomDeclarationDocument
    declaration_hash: str
    path: Path

    @property
    def declaration_id(self) -> str:
        return self.document.declaration_id

    @property
    def dimensions(self) -> list[DesignFreedomDimension]:
        return self.document.dimensions


def load_design_freedom_declaration(
    path: Path | None = None,
) -> DesignFreedomDeclaration:
    declaration_path = path or repository_root() / "contracts" / "design-freedom-declaration.json"
    try:
        value = json.loads(declaration_path.read_text(encoding="utf-8"))
        document = DesignFreedomDeclarationDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DesignFreedomDeclarationError(
            f"design freedom declaration is invalid: {declaration_path}: {exc}"
        ) from exc
    return DesignFreedomDeclaration(
        document=document,
        declaration_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=declaration_path,
    )


def design_freedom_dimension(
    dimension_id: str,
    declaration: DesignFreedomDeclaration | None = None,
) -> DesignFreedomDimension:
    loaded = declaration or load_design_freedom_declaration()
    for item in loaded.dimensions:
        if item.dimension_id == dimension_id:
            return item
    raise DesignFreedomDeclarationError(f"design freedom dimension is unknown: {dimension_id!r}")


def searchable_dimensions(
    declaration: DesignFreedomDeclaration | None = None,
) -> tuple[str, ...]:
    loaded = declaration or load_design_freedom_declaration()
    return tuple(sorted(item.dimension_id for item in loaded.dimensions if item.search_enabled))


def validate_change_dimension_alignment(
    declaration: DesignFreedomDeclaration | None = None,
    registry: FunctionalBlockRegistry | None = None,
) -> None:
    loaded = declaration or load_design_freedom_declaration()
    functional = registry or load_functional_block_registry()
    by_id = {item.dimension_id: item for item in loaded.dimensions}
    entries = {
        dimension
        for contract in functional.contracts
        for dimension in contract.allowed_change_dimensions
    }
    unknown = sorted(entries - set(by_id))
    disabled = sorted(
        dimension
        for dimension in entries
        if dimension in by_id and not by_id[dimension].search_enabled
    )
    if unknown or disabled:
        details: list[str] = []
        if unknown:
            details.append("undeclared: " + ", ".join(unknown))
        if disabled:
            details.append("not searchable: " + ", ".join(disabled))
        raise DesignFreedomDeclarationError(
            "functional-block change dimensions are not aligned: " + "; ".join(details)
        )


__all__ = [
    "DesignFreedomDeclaration",
    "DesignFreedomDeclarationError",
    "design_freedom_dimension",
    "load_design_freedom_declaration",
    "searchable_dimensions",
    "validate_change_dimension_alignment",
]
