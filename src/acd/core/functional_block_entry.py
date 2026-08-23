"""Deterministic entrypoint for functional-block contract declarations."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from acd.core.design_freedom import load_design_freedom_declaration
from acd.core.design_predicates import PREDICATE_CATALOG
from acd.core.functional_blocks import (
    FunctionalBlockContractError,
    FunctionalBlockRegistry,
    load_functional_block_registry,
    validate_predicate_coverage,
)
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.functional_block import (
    FunctionalBlockContract,
    FunctionalBlockRegistryDocument,
)


@dataclass(frozen=True)
class FunctionalBlockEntryResult:
    """Validated declaration entry result and its provenance."""

    registry_id: str
    prior_registry_hash: str
    new_registry_hash: str
    contract_source: str
    contract: FunctionalBlockContract
    written: bool

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible result payload."""
        value = asdict(self)
        value["contract"] = self.contract.model_dump(mode="json")
        return value


def _default_registry_path() -> Path:
    return repository_root() / "contracts" / "functional-block-registry.json"


def _read_contract_input(
    value: FunctionalBlockContract | Mapping[str, Any] | str | Path,
) -> tuple[FunctionalBlockContract, str]:
    if isinstance(value, FunctionalBlockContract):
        return value, "model"
    if isinstance(value, Mapping):
        return FunctionalBlockContract.model_validate(value), "mapping"
    if isinstance(value, Path):
        source = str(value)
        try:
            payload = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise FunctionalBlockContractError(
                f"functional block contract is invalid: {source}: {exc}"
            ) from exc
        return FunctionalBlockContract.model_validate(payload), source
    stripped = value.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FunctionalBlockContractError(
                f"functional block contract JSON is invalid: {exc}"
            ) from exc
        return FunctionalBlockContract.model_validate(payload), "inline"

    path = Path(value)
    try:
        if path.is_file():
            return _read_contract_input(path)
    except OSError as exc:
        raise FunctionalBlockContractError(
            f"functional block contract path cannot be read: {value}: {exc}"
        ) from exc
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise FunctionalBlockContractError(
            f"functional block contract is neither a JSON object nor a readable file: "
            f"{value}: {exc}"
        ) from exc
    return FunctionalBlockContract.model_validate(payload), "inline"


def _registry_json(document: FunctionalBlockRegistryDocument) -> str:
    lines = [
        "{",
        f'  "schema_version": {json.dumps(document.schema_version)},',
        f'  "registry_id": {json.dumps(document.registry_id, ensure_ascii=False)},',
        '  "contracts": [',
    ]
    for index, contract in enumerate(document.contracts):
        lines.extend(
            [
                "    {",
                f'      "block_id": {json.dumps(contract.block_id, ensure_ascii=False)},',
                f'      "title": {json.dumps(contract.title, ensure_ascii=False)},',
                (
                    f'      "description": '
                    f'{json.dumps(contract.description, ensure_ascii=False)},'
                ),
            ]
        )
        if contract.allowed_change_dimensions:
            lines.append('      "allowed_change_dimensions": [')
            lines.extend(
                "        "
                + json.dumps(dimension, ensure_ascii=False)
                + ("," if position < len(contract.allowed_change_dimensions) - 1 else "")
                for position, dimension in enumerate(contract.allowed_change_dimensions)
            )
            lines.append("      ],")
        else:
            lines.append('      "allowed_change_dimensions": [],')
        lines.extend(
            [
                f'      "mandatory": {str(contract.mandatory).lower()},',
                (
                    f'      "required_predicates": '
                    f'{json.dumps(contract.required_predicates, ensure_ascii=False)}'
                ),
                "    }" + ("," if index < len(document.contracts) - 1 else ""),
            ]
        )
    lines.extend(["  ]", "}"])
    return "\n".join(lines) + "\n"


def _validate_new_contract(
    contract: FunctionalBlockContract,
    registry: FunctionalBlockRegistry,
) -> None:
    existing_ids = {item.block_id for item in registry.contracts}
    if contract.block_id in existing_ids:
        raise FunctionalBlockContractError(
            f"functional block block_id is already registered: {contract.block_id!r}"
        )

    catalog = set(PREDICATE_CATALOG)
    unknown_predicates = sorted(set(contract.required_predicates) - catalog)
    if unknown_predicates:
        raise FunctionalBlockContractError(
            "functional block contract references unknown predicates: "
            + ", ".join(unknown_predicates)
        )

    declaration = load_design_freedom_declaration()
    dimensions = {item.dimension_id: item for item in declaration.dimensions}
    unknown_dimensions = sorted(
        set(contract.allowed_change_dimensions) - set(dimensions)
    )
    if unknown_dimensions:
        raise FunctionalBlockContractError(
            "functional block contract references unknown change dimensions: "
            + ", ".join(unknown_dimensions)
        )
    disabled_dimensions = sorted(
        dimension
        for dimension in contract.allowed_change_dimensions
        if not dimensions[dimension].search_enabled
    )
    if disabled_dimensions:
        raise FunctionalBlockContractError(
            "functional block contract references non-explorable change dimensions: "
            + ", ".join(disabled_dimensions)
        )

    validate_predicate_coverage(PREDICATE_CATALOG, registry)


def _write_registry(path: Path, document: FunctionalBlockRegistryDocument) -> None:
    payload = _registry_json(document)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        raise FunctionalBlockContractError(
            f"functional block registry cannot be written: {path}: {exc}"
        ) from exc


def register_functional_block_contract(
    contract: FunctionalBlockContract | Mapping[str, Any] | str | Path,
    registry_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> FunctionalBlockEntryResult:
    """Validate and optionally append one immutable contract declaration."""
    proposed, detected_source = _read_contract_input(contract)
    registry = load_functional_block_registry(registry_path or _default_registry_path())
    _validate_new_contract(proposed, registry)
    updated_document = registry.document.model_copy(
        update={"contracts": [*registry.contracts, proposed]}
    )
    updated_registry = FunctionalBlockRegistry(
        document=updated_document,
        registry_hash=canonical_json_sha256(updated_document.model_dump(mode="json")),
        path=registry.path,
    )
    if not dry_run:
        _write_registry(registry.path, updated_document)
    return FunctionalBlockEntryResult(
        registry_id=registry.registry_id,
        prior_registry_hash=registry.registry_hash,
        new_registry_hash=updated_registry.registry_hash,
        contract_source=detected_source,
        contract=proposed,
        written=not dry_run,
    )


__all__ = [
    "FunctionalBlockEntryResult",
    "register_functional_block_contract",
]
