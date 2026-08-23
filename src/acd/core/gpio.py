"""Shared deterministic GPIO assignment graph updates."""

from __future__ import annotations

from acd.schema.design_graph import DesignGraph, GraphNode


class GpioAssignmentError(ValueError):
    """Raised when a GPIO assignment cannot be mapped unambiguously."""


def _aliases(component: GraphNode) -> dict[str, str]:
    raw = component.attrs.get("cpl_rotation_pin_aliases", [])
    if not isinstance(raw, list):
        return {}
    aliases: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            continue
        left, right = item.split("=", 1)
        aliases[left.strip()] = right.strip()
    return aliases


def gpio_pad_map(graph: DesignGraph) -> dict[int, str]:
    """Resolve graph-declared MCU GPIO numbers to electrical pin node IDs."""
    components = [
        node
        for node in graph.nodes
        if node.kind == "electrical.component"
        and isinstance(node.attrs.get("cpl_rotation_pin_functions"), list)
    ]
    preferred = [
        node
        for node in components
        if node.attrs.get("refdes") == "U1" or node.attrs.get("radio_module") is True
    ]
    if len(preferred) == 1:
        components = preferred
    if len(components) != 1:
        raise GpioAssignmentError("GPIO mapping requires exactly one declared MCU")
    component = components[0]
    aliases = _aliases(component)
    functions = component.attrs["cpl_rotation_pin_functions"]
    assert isinstance(functions, list)
    pad_to_function: dict[str, str] = {}
    for item in functions:
        if "=" not in item:
            continue
        pad, function = item.split("=", 1)
        pad_to_function[pad.strip()] = function.strip()
    pins = {
        str(node.attrs.get("pad")): node.id
        for node in graph.nodes
        if node.kind == "electrical.pin"
        and node.attrs.get("component") == component.id
    }
    result: dict[int, str] = {}
    for gpio in range(0, 50):
        names = (f"GPIO{gpio}", f"IO{gpio}")
        functions_for_gpio = {aliases.get(name, name) for name in names}
        matches = sorted(
            pins[pad]
            for pad, function in pad_to_function.items()
            if function in functions_for_gpio and pad in pins
        )
        if len(matches) == 1:
            result[gpio] = matches[0]
        elif len(matches) > 1:
            raise GpioAssignmentError(f"GPIO{gpio} maps to multiple MCU pads")
    return result


def apply_gpio_assignment(
    graph: DesignGraph, net_id: str, gpio: int
) -> tuple[DesignGraph, tuple[str, ...]]:
    """Move one firmware net to a graph-declared MCU GPIO pad."""
    fw_nodes = [
        node
        for node in graph.nodes
        if node.kind == "firmware.pin_assignment" and node.attrs.get("net") == net_id
    ]
    if len(fw_nodes) != 1:
        raise GpioAssignmentError(
            f"expected one firmware assignment for net {net_id!r}, found {len(fw_nodes)}"
        )
    target = gpio_pad_map(graph).get(gpio)
    if target is None:
        raise GpioAssignmentError(f"GPIO{gpio} has no graph-declared MCU pad")
    current = [
        node
        for node in graph.nodes
        if node.kind == "electrical.pin"
        and node.attrs.get("net") == net_id
        and node.attrs.get("component") == graph.node_by_id(target).attrs.get("component")
    ]
    if len(current) != 1:
        raise GpioAssignmentError(
            f"net {net_id!r} has {len(current)} MCU pads; expected one"
        )
    if current[0].id == target:
        return graph, ()
    target_node = graph.node_by_id(target)
    if target_node.attrs.get("net") not in (None, net_id):
        raise GpioAssignmentError(f"GPIO{gpio} target pad is occupied")
    old = current[0]
    changed: list[str] = []
    updated: list[GraphNode] = []
    for node in graph.nodes:
        if node.id == old.id:
            updated.append(
                node.model_copy(
                    update={
                        "attrs": {
                            "component": node.attrs["component"],
                            "pad": node.attrs["pad"],
                            "net": None,
                            "no_connect": True,
                        },
                        "depends_on": [node.attrs["component"]],
                    }
                )
            )
            changed.append(node.id)
        elif node.id == target:
            updated.append(
                node.model_copy(
                    update={
                        "attrs": {
                            "component": node.attrs["component"],
                            "pad": node.attrs["pad"],
                            "net": net_id,
                            "no_connect": False,
                        },
                        "depends_on": [node.attrs["component"], net_id],
                    }
                )
            )
            changed.append(node.id)
        elif node.id == fw_nodes[0].id:
            updated.append(node.model_copy(update={"attrs": {**node.attrs, "gpio": gpio}}))
            changed.append(node.id)
        else:
            updated.append(node)
    return graph.model_copy(update={"nodes": updated}), tuple(sorted(changed))


__all__ = ["GpioAssignmentError", "apply_gpio_assignment", "gpio_pad_map"]
