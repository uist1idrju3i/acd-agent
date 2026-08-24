"""Deterministic functional-block topology synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.core.functional_blocks import (
    FunctionalBlockRegistry,
    load_functional_block_registry,
)
from acd.pipeline.repository import repository_root
from acd.schema import FixtureComponentSpec, FixtureNetSpec, TopologyTemplatesDocument


class TopologySynthesisError(ValueError):
    """Raised when a declared functional block has no safe template."""


@dataclass(frozen=True)
class TopologyFragment:
    components: tuple[FixtureComponentSpec, ...]
    nets: tuple[FixtureNetSpec, ...]
    constraints: tuple[str, ...] = ()


def default_topology_templates_path() -> Path:
    return repository_root() / "contracts" / "topology-templates.json"


def load_topology_templates(
    path: Path | None = None,
) -> TopologyTemplatesDocument:
    template_path = path or default_topology_templates_path()
    try:
        document = TopologyTemplatesDocument.model_validate_json(
            template_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TopologySynthesisError(
            f"topology templates are invalid or unreadable: {template_path}: {exc}"
        ) from exc
    return document


def _validate_registry_coverage(
    document: TopologyTemplatesDocument,
    registry: FunctionalBlockRegistry,
) -> None:
    known = {contract.block_id for contract in registry.contracts}
    unknown = sorted({template.block_id for template in document.templates} - known)
    if unknown:
        raise TopologySynthesisError(
            "topology template references unknown functional block: " + ", ".join(unknown)
        )


def synthesize_topology(
    block_ids: tuple[str, ...] | list[str],
    *,
    registry: FunctionalBlockRegistry | None = None,
    templates_path: Path | None = None,
) -> TopologyFragment:
    """Return the deterministic fixture fragment for declared blocks."""
    loaded = registry or load_functional_block_registry()
    templates = load_topology_templates(templates_path)
    _validate_registry_coverage(templates, loaded)
    known = {contract.block_id for contract in loaded.contracts}
    requested = set(block_ids)
    unknown = sorted(requested - known)
    if unknown:
        raise TopologySynthesisError("unknown functional block: " + ", ".join(unknown))
    by_block_id = {template.block_id: template for template in templates.templates}
    missing_templates = sorted(requested - set(by_block_id))
    if missing_templates:
        raise TopologySynthesisError(
            "functional block has no topology template (検証不能): "
            + ", ".join(missing_templates)
        )
    components: dict[str, FixtureComponentSpec] = {}
    nets: dict[str, FixtureNetSpec] = {}
    shared_nets = {
        net.net_id: FixtureNetSpec(net_id=net.net_id, attrs=net.attrs)
        for net in templates.shared_nets
    }
    constraints: set[str] = set()
    for block_id in sorted(requested):
        template = by_block_id[block_id]
        for declared in template.components:
            component = FixtureComponentSpec(
                refdes=declared.refdes,
                part_request=declared.part_request,
                pads=declared.pads,
                attrs=declared.attrs,
            )
            previous = components.get(component.refdes)
            if previous is not None and previous != component:
                raise TopologySynthesisError(
                    f"topology templates conflict for component: {component.refdes}"
                )
            components[component.refdes] = component
        for declared in template.nets:
            net = FixtureNetSpec(net_id=declared.net_id, attrs=declared.attrs)
            previous = nets.get(net.net_id)
            if previous is not None and previous != net:
                raise TopologySynthesisError(f"topology templates conflict for net: {net.net_id}")
            nets[net.net_id] = net
        constraints.update(template.constraints)
    referenced_nets = {
        net_id
        for component in components.values()
        for net_id in component.pads.values()
        if net_id is not None
    }
    for net_id in sorted(referenced_nets - set(nets)):
        shared = shared_nets.get(net_id)
        if shared is None:
            raise TopologySynthesisError(
                f"topology template references unavailable shared net: {net_id}"
            )
        nets[net_id] = shared
    return TopologyFragment(
        components=tuple(components[key] for key in sorted(components)),
        nets=tuple(nets[key] for key in sorted(nets)),
        constraints=tuple(sorted(constraints)),
    )


__all__ = [
    "TopologyFragment",
    "TopologySynthesisError",
    "default_topology_templates_path",
    "load_topology_templates",
    "synthesize_topology",
]
