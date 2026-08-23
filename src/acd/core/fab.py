"""Typed extraction and validation of fab declarations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acd.core.electrical import GraphExtractionError
from acd.pipeline.repository import repository_root
from acd.schema import (
    DesignGraph,
    FabProfileDocument,
    FabProfileRegistryDocument,
    GraphNode,
)


@dataclass(frozen=True)
class FabOrderIntentView:
    node_id: str
    fab_profile: str
    profile_source: str
    profile_fetched_at: str
    pcba_class_target: str
    quantity_pcs: int
    delivery_format: str
    soldermask_color: str
    surface_finish: str
    assembly_sides: str


@dataclass(frozen=True)
class ProcessAllowanceView:
    node_id: str
    rule_id: str
    reason: str
    requirement: str
    impact_accepted: tuple[str, ...]


@dataclass(frozen=True)
class FabProfile:
    data: dict[str, Any]

    @property
    def profile_id(self) -> str:
        return cast(str, self.data["profile_id"])

    @property
    def preference_rule_ids(self) -> frozenset[str]:
        return frozenset(
            preference["rule_id"] for preference in self.data["preferences"]
        )


@dataclass(frozen=True)
class FabProfileRegistry:
    document: FabProfileRegistryDocument
    registry_hash: str
    path: Path


def load_fab_profile_registry(path: Path | None = None) -> FabProfileRegistry:
    registry_path = path or repository_root() / "profiles" / "fab-profile-registry.json"
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        document = FabProfileRegistryDocument.model_validate(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"fab profile registry is invalid: {registry_path}: {exc}") from exc
    from acd.schema.common import canonical_json_sha256

    return FabProfileRegistry(
        document=document,
        registry_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=registry_path,
    )


def resolve_fab_profile_path(
    profile_id: str, registry: FabProfileRegistry | None = None
) -> Path:
    loaded = registry or load_fab_profile_registry()
    entries = [entry for entry in loaded.document.profiles if entry.profile_id == profile_id]
    if len(entries) != 1:
        raise ValueError(f"unknown fab profile id: {profile_id}")
    raw_path = Path(entries[0].path)
    profile_path = raw_path if raw_path.is_absolute() else loaded.path.parent / raw_path
    if not profile_path.is_file():
        raise ValueError(f"fab profile path does not exist: {profile_path}")
    profile = load_fab_profile(profile_path)
    if profile.profile_id != profile_id:
        raise ValueError(
            f"fab profile id mismatch: registry={profile_id!r}, file={profile.profile_id!r}"
        )
    if profile.data["fab"] != entries[0].fab or profile.data["process"] != entries[0].process:
        raise ValueError(f"fab profile metadata mismatch for id: {profile_id}")
    return profile_path


def load_fab_profile_by_id(
    profile_id: str, registry: FabProfileRegistry | None = None
) -> FabProfile:
    return load_fab_profile(resolve_fab_profile_path(profile_id, registry))


def _required_str(node: GraphNode, key: str) -> str:
    value = node.attrs.get(key)
    if not isinstance(value, str) or not value:
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or invalid")
    return value


def _required_int(node: GraphNode, key: str) -> int:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphExtractionError(f"node {node.id!r}: attr {key!r} missing or invalid")
    return value


def _required_impacts(node: GraphNode) -> tuple[str, ...]:
    value = node.attrs.get("impact_accepted")
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list):
        values = tuple(value)
    else:
        raise GraphExtractionError(f"node {node.id!r}: attr 'impact_accepted' missing or invalid")
    if not values or any(item not in {"cost", "lead_time", "quality"} for item in values):
        raise GraphExtractionError(f"node {node.id!r}: invalid impact_accepted")
    return values


def extract_fab_intent(
    graph: DesignGraph,
) -> tuple[FabOrderIntentView, tuple[ProcessAllowanceView, ...]]:
    intents: list[FabOrderIntentView] = []
    allowances: list[ProcessAllowanceView] = []
    node_ids = {node.id for node in graph.nodes}
    for node in graph.nodes:
        if node.kind == "fab.order_intent":
            target = _required_str(node, "pcba_class_target")
            if target not in {"economic", "standard"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid pcba_class_target")
            sides = _required_str(node, "assembly_sides")
            if sides not in {"top", "bottom", "both"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid assembly_sides")
            delivery = _required_str(node, "delivery_format")
            if delivery not in {"single", "panel_mouse_bites", "panel_v_cut"}:
                raise GraphExtractionError(f"node {node.id!r}: invalid delivery_format")
            intents.append(
                FabOrderIntentView(
                    node_id=node.id,
                    fab_profile=_required_str(node, "fab_profile"),
                    profile_source=_required_str(node, "profile_source"),
                    profile_fetched_at=_required_str(node, "profile_fetched_at"),
                    pcba_class_target=target,
                    quantity_pcs=_required_int(node, "quantity_pcs"),
                    delivery_format=delivery,
                    soldermask_color=_required_str(node, "soldermask_color"),
                    surface_finish=_required_str(node, "surface_finish"),
                    assembly_sides=sides,
                )
            )
        elif node.kind == "fab.process_allowance":
            requirement = _required_str(node, "requirement")
            if requirement not in node_ids or requirement not in node.depends_on:
                raise GraphExtractionError(f"node {node.id!r}: requirement reference is missing")
            allowances.append(
                ProcessAllowanceView(
                    node_id=node.id,
                    rule_id=_required_str(node, "rule_id"),
                    reason=_required_str(node, "reason"),
                    requirement=requirement,
                    impact_accepted=_required_impacts(node),
                )
            )
    if len(intents) != 1:
        raise GraphExtractionError(
            f"expected exactly one fab.order_intent node, got {len(intents)}"
        )
    return intents[0], tuple(allowances)


def load_fab_profile(path: Path) -> FabProfile:
    """Load and validate a tracked fab profile, including provenance invariants."""
    profile = json.loads(path.read_text(encoding="utf-8"))
    FabProfileDocument.model_validate(profile)
    source_count = len(profile["sources"])
    for item in profile["capabilities"].values():
        if item["source_index"] >= source_count:
            raise ValueError("fab profile capability source_index is out of range")
    rule_ids = [item["rule_id"] for item in profile["preferences"]]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("fab profile preference rule_id values must be unique")
    for item in profile["preferences"]:
        if item["source_index"] >= source_count:
            raise ValueError("fab profile preference source_index is out of range")
    contract = profile["cpl_contract"]
    for key in ("position_source_index", "rotation_source_index"):
        if contract[key] >= source_count:
            raise ValueError(f"fab profile CPL contract {key} is out of range")
    return FabProfile(data=profile)


def validate_allowances_against_profile(
    allowances: tuple[ProcessAllowanceView, ...], profile: FabProfile
) -> None:
    unknown = [
        item.rule_id for item in allowances if item.rule_id not in profile.preference_rule_ids
    ]
    if unknown:
        raise GraphExtractionError(
            f"unknown fab process allowance rule_id(s): {', '.join(unknown)}"
        )
