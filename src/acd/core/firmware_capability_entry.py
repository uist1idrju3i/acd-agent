"""Deterministic entrypoint for firmware capability declarations.

Firmware capabilities and their actions are declarations, not Evidence. This
entrypoint validates one proposed capability against the current registry and
appends it atomically, so a conversation can declare a firmware capability
without hand-editing the registry. The firmware Skill keeps refusing any graph
action that this registry does not declare, and a declared action without a
Skill implementation still fails closed inside the Skill.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from acd.core.firmware_capability import (
    FirmwareCapabilityContractError,
    FirmwareCapabilityRegistry,
    load_firmware_capability_registry,
)
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.firmware_capability import (
    FirmwareCapabilityContract,
    FirmwareCapabilityRegistryDocument,
)


@dataclass(frozen=True)
class FirmwareCapabilityEntryResult:
    """Validated firmware capability declaration result and its provenance."""

    registry_id: str
    prior_registry_hash: str
    new_registry_hash: str
    capability_source: str
    capability: FirmwareCapabilityContract
    written: bool

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible result payload."""
        value = asdict(self)
        value["capability"] = self.capability.model_dump(mode="json")
        return value


def _default_registry_path() -> Path:
    return repository_root() / "contracts" / "firmware-capability-registry.json"


def _read_capability_input(
    value: FirmwareCapabilityContract | Mapping[str, Any] | str | Path,
) -> tuple[FirmwareCapabilityContract, str]:
    if isinstance(value, FirmwareCapabilityContract):
        return value, "model"
    if isinstance(value, Mapping):
        return FirmwareCapabilityContract.model_validate(value), "mapping"
    if isinstance(value, Path):
        try:
            payload = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise FirmwareCapabilityContractError(
                f"firmware capability declaration is invalid: {value}: {exc}"
            ) from exc
        return FirmwareCapabilityContract.model_validate(payload), str(value)
    if value.lstrip().startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FirmwareCapabilityContractError(
                f"firmware capability declaration JSON is invalid: {exc}"
            ) from exc
        return FirmwareCapabilityContract.model_validate(payload), "inline"
    path = Path(value)
    try:
        if path.is_file():
            return _read_capability_input(path)
    except OSError as exc:
        raise FirmwareCapabilityContractError(
            f"firmware capability declaration cannot be read: {value}: {exc}"
        ) from exc
    raise FirmwareCapabilityContractError(
        "firmware capability declaration is neither a JSON object nor a readable "
        f"file: {value}"
    )


def _validate_new_capability(
    capability: FirmwareCapabilityContract,
    registry: FirmwareCapabilityRegistry,
) -> None:
    if capability.capability_id in {
        item.capability_id for item in registry.capabilities
    }:
        raise FirmwareCapabilityContractError(
            "firmware capability_id is already registered: "
            f"{capability.capability_id!r}"
        )
    declared_actions = {
        action for item in registry.capabilities for action in item.actions
    }
    conflicting = sorted(declared_actions & set(capability.actions))
    if conflicting:
        raise FirmwareCapabilityContractError(
            "firmware capability actions are already registered: "
            + ", ".join(conflicting)
        )
    unknown_roles = sorted(
        set(capability.required_pin_roles) - set(registry.document.pin_role_order)
    )
    if unknown_roles:
        raise FirmwareCapabilityContractError(
            "firmware capability requires undeclared pin roles: "
            + ", ".join(unknown_roles)
        )
    if capability.requires_device and not registry.devices:
        raise FirmwareCapabilityContractError(
            "firmware capability requires a device but the registry declares none"
        )


def _write_registry(path: Path, document: FirmwareCapabilityRegistryDocument) -> None:
    payload = (
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
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
        raise FirmwareCapabilityContractError(
            f"firmware capability registry cannot be written: {path}: {exc}"
        ) from exc


def register_firmware_capability(
    capability: FirmwareCapabilityContract | Mapping[str, Any] | str | Path,
    registry_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> FirmwareCapabilityEntryResult:
    """Validate and optionally append one firmware capability declaration."""
    proposed, detected_source = _read_capability_input(capability)
    registry = load_firmware_capability_registry(
        registry_path or _default_registry_path()
    )
    _validate_new_capability(proposed, registry)
    updated_document = registry.document.model_copy(
        update={"capabilities": [*registry.capabilities, proposed]}
    )
    # Revalidate the whole document so registry-wide invariants decide the
    # outcome instead of the incremental checks alone.
    updated_document = FirmwareCapabilityRegistryDocument.model_validate(
        updated_document.model_dump(mode="json")
    )
    new_hash = canonical_json_sha256(updated_document.model_dump(mode="json"))
    if not dry_run:
        _write_registry(registry.path, updated_document)
    return FirmwareCapabilityEntryResult(
        registry_id=registry.document.registry_id,
        prior_registry_hash=registry.registry_hash,
        new_registry_hash=new_hash,
        capability_source=detected_source,
        capability=proposed,
        written=not dry_run,
    )


__all__ = [
    "FirmwareCapabilityEntryResult",
    "register_firmware_capability",
]
