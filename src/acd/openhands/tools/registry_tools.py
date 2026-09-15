"""ToolDefinitions that register functional blocks, firmware capabilities, and parts entries."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from openhands.sdk.tool import (
    Action,
    DeclaredResources,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
)
from pydantic import Field

from acd.core.firmware_capability_entry import register_firmware_capability
from acd.core.functional_block_entry import register_functional_block_contract
from acd.core.parts_catalog_entry import register_parts_catalog_entry

if TYPE_CHECKING:
    from openhands.sdk.conversation.state import ConversationState
from acd.openhands.tools._base import (
    AcdObservation,
    error_payload,
    resolved_resource_path,
)


class AcdRegisterFunctionalBlockAction(Action):
    """Validate and append one functional-block contract declaration."""

    contract: str = Field(
        description="FunctionalBlockContract JSON path or inline JSON object."
    )
    registry: str = Field(
        default="contracts/functional-block-registry.json",
        description="Functional-block registry JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the registry.",
    )


class AcdRegisterFirmwareCapabilityAction(Action):
    """Validate and append one firmware capability declaration."""

    capability: str = Field(
        description="FirmwareCapabilityContract JSON path or inline JSON object."
    )
    registry: str = Field(
        default="contracts/firmware-capability-registry.json",
        description="Firmware capability registry JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the registry.",
    )


class AcdRegisterPartsCatalogEntryAction(Action):
    """Validate and append one parts-catalog entry declaration."""

    entry: str = Field(description="PartCatalogEntry JSON path or inline JSON object.")
    catalog: str = Field(
        default="contracts/parts-catalog.json",
        description="Parts catalog JSON path.",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without writing the catalog.",
    )


class AcdRegisterFunctionalBlockObservation(AcdObservation):
    """Observation returned by functional-block contract registration."""


class AcdRegisterFirmwareCapabilityObservation(AcdObservation):
    """Observation returned by firmware capability registration."""


class AcdRegisterPartsCatalogEntryObservation(AcdObservation):
    """Observation returned by parts-catalog entry registration."""


class AcdRegisterFunctionalBlockExecutor(
    ToolExecutor[AcdRegisterFunctionalBlockAction, AcdRegisterFunctionalBlockObservation]
):
    def __call__(
        self,
        action: AcdRegisterFunctionalBlockAction,
        conversation: Any = None,
    ) -> AcdRegisterFunctionalBlockObservation:
        del conversation
        try:
            result = register_functional_block_contract(
                action.contract,
                Path(action.registry),
                dry_run=action.dry_run,
            )
            return AcdRegisterFunctionalBlockObservation(
                ok=True,
                operation="register_functional_block",
                registry_id=result.registry_id,
                prior_registry_hash=result.prior_registry_hash,
                new_registry_hash=result.new_registry_hash,
                contract_source=result.contract_source,
                contract=result.contract.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterFunctionalBlockObservation(
                **error_payload(str(exc), operation="register_functional_block")
            )


class AcdRegisterFirmwareCapabilityExecutor(
    ToolExecutor[
        AcdRegisterFirmwareCapabilityAction,
        AcdRegisterFirmwareCapabilityObservation,
    ]
):
    def __call__(
        self,
        action: AcdRegisterFirmwareCapabilityAction,
        conversation: Any = None,
    ) -> AcdRegisterFirmwareCapabilityObservation:
        del conversation
        try:
            result = register_firmware_capability(
                action.capability,
                Path(action.registry),
                dry_run=action.dry_run,
            )
            return AcdRegisterFirmwareCapabilityObservation(
                ok=True,
                operation="register_firmware_capability",
                registry_id=result.registry_id,
                prior_registry_hash=result.prior_registry_hash,
                new_registry_hash=result.new_registry_hash,
                contract_source=result.capability_source,
                contract=result.capability.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterFirmwareCapabilityObservation(
                **error_payload(str(exc), operation="register_firmware_capability")
            )


class AcdRegisterPartsCatalogEntryExecutor(
    ToolExecutor[
        AcdRegisterPartsCatalogEntryAction,
        AcdRegisterPartsCatalogEntryObservation,
    ]
):
    def __call__(
        self,
        action: AcdRegisterPartsCatalogEntryAction,
        conversation: Any = None,
    ) -> AcdRegisterPartsCatalogEntryObservation:
        del conversation
        try:
            result = register_parts_catalog_entry(
                action.entry,
                Path(action.catalog),
                dry_run=action.dry_run,
            )
            return AcdRegisterPartsCatalogEntryObservation(
                ok=True,
                operation="register_parts_catalog_entry",
                catalog_id=result.catalog_id,
                prior_catalog_hash=result.prior_catalog_hash,
                new_catalog_hash=result.new_catalog_hash,
                entry_source=result.entry_source,
                entry=result.entry.model_dump(mode="json"),
                written=result.written,
                fail_closed=False,
            )
        except Exception as exc:
            return AcdRegisterPartsCatalogEntryObservation(
                **error_payload(str(exc), operation="register_parts_catalog_entry")
            )


class AcdRegisterFunctionalBlock(
    ToolDefinition[
        AcdRegisterFunctionalBlockAction,
        AcdRegisterFunctionalBlockObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterFunctionalBlockAction):
            return DeclaredResources(keys=(), declared=False)
        registry_path = resolved_resource_path(action.registry)
        if registry_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{registry_path}"]
        contract_path = resolved_resource_path(action.contract)
        if contract_path is not None and contract_path.is_file():
            keys.insert(0, f"file:{contract_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_register_functional_block does not accept parameters")
        return [
            cls(
                action_type=AcdRegisterFunctionalBlockAction,
                observation_type=AcdRegisterFunctionalBlockObservation,
                description=(
                    "Validate and register one functional-block contract declaration."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_functional_block",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterFunctionalBlockExecutor(),
            )
        ]


class AcdRegisterFirmwareCapability(
    ToolDefinition[
        AcdRegisterFirmwareCapabilityAction,
        AcdRegisterFirmwareCapabilityObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterFirmwareCapabilityAction):
            return DeclaredResources(keys=(), declared=False)
        registry_path = resolved_resource_path(action.registry)
        if registry_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{registry_path}"]
        capability_path = resolved_resource_path(action.capability)
        if capability_path is not None and capability_path.is_file():
            keys.insert(0, f"file:{capability_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(
        cls,
        conv_state: ConversationState | None = None,
        **params: Any,
    ) -> list[Self]:
        del conv_state
        if params:
            raise ValueError(
                "acd_register_firmware_capability does not accept parameters"
            )
        return [
            cls(
                action_type=AcdRegisterFirmwareCapabilityAction,
                observation_type=AcdRegisterFirmwareCapabilityObservation,
                description=(
                    "Validate and register one firmware capability declaration. "
                    "This is a declaration path, not gate evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_firmware_capability",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterFirmwareCapabilityExecutor(),
            )
        ]


class AcdRegisterPartsCatalogEntry(
    ToolDefinition[
        AcdRegisterPartsCatalogEntryAction,
        AcdRegisterPartsCatalogEntryObservation,
    ]
):
    def declared_resources(self, action: Action) -> DeclaredResources:
        if not isinstance(action, AcdRegisterPartsCatalogEntryAction):
            return DeclaredResources(keys=(), declared=False)
        catalog_path = resolved_resource_path(action.catalog)
        if catalog_path is None:
            return DeclaredResources(keys=(), declared=False)
        keys = [f"file:{catalog_path}"]
        entry_path = resolved_resource_path(action.entry)
        if entry_path is not None and entry_path.is_file():
            keys.insert(0, f"file:{entry_path}")
        return DeclaredResources(keys=tuple(keys), declared=True)

    @classmethod
    def create(cls, conv_state: ConversationState | None = None, **params: Any) -> list[Self]:
        del conv_state
        if params:
            raise ValueError("acd_register_parts_catalog_entry does not accept parameters")
        return [
            cls(
                action_type=AcdRegisterPartsCatalogEntryAction,
                observation_type=AcdRegisterPartsCatalogEntryObservation,
                description=(
                    "Validate and register one parts-catalog entry declaration "
                    "without granting L1 authority or creating Evidence."
                ),
                annotations=ToolAnnotations(
                    title="acd_register_parts_catalog_entry",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AcdRegisterPartsCatalogEntryExecutor(),
            )
        ]
