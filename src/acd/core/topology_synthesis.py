"""Deterministic functional-block topology synthesis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from acd.core.functional_blocks import (
    FunctionalBlockRegistry,
    load_functional_block_registry,
)
from acd.schema import (
    FixtureComponentSpec,
    FixtureNetSpec,
)
from acd.schema.parts_catalog import ComponentPartRequest


class TopologySynthesisError(ValueError):
    """Raised when a declared functional block has no safe template."""


@dataclass(frozen=True)
class TopologyFragment:
    components: tuple[FixtureComponentSpec, ...]
    nets: tuple[FixtureNetSpec, ...]
    constraints: tuple[str, ...] = ()


def _part(
    refdes: str,
    kind: str,
    value: str,
    package: str,
    pads: dict[str, str | None],
) -> FixtureComponentSpec:
    return FixtureComponentSpec(
        refdes=refdes,
        part_request=ComponentPartRequest(
            kind=kind,
            value=value,
            package=package,
        ),
        pads=pads,
        attrs={"value": value},
    )


def _net(net_id: str, name: str) -> FixtureNetSpec:
    return FixtureNetSpec(net_id=net_id, attrs={"name": name})


def _usb() -> TopologyFragment:
    return TopologyFragment(
        components=(
            _part("R1", "resistor", "5.1k", "R_0603_1608Metric", {"1": "net.cc1", "2": "net.gnd"}),
            _part("R2", "resistor", "5.1k", "R_0603_1608Metric", {"1": "net.cc2", "2": "net.gnd"}),
        ),
        nets=(
            _net("net.cc1", "CC1"),
            _net("net.cc2", "CC2"),
        ),
    )


def _i2c() -> TopologyFragment:
    return TopologyFragment(
        components=(
            _part(
                "R4",
                "resistor",
                "4.7k",
                "R_0603_1608Metric",
                {"1": "net.p3v3", "2": "net.i2c_sda"},
            ),
            _part(
                "R5",
                "resistor",
                "4.7k",
                "R_0603_1608Metric",
                {"1": "net.p3v3", "2": "net.i2c_scl"},
            ),
        ),
        nets=(
            _net("net.i2c_sda", "I2C_SDA"),
            _net("net.i2c_scl", "I2C_SCL"),
        ),
    )


def _ldo() -> TopologyFragment:
    return TopologyFragment(
        components=(
            _part(
                "U2",
                "ic",
                "AMS1117-3.3",
                "SOT-223-3_TabPin2",
                {"1": "net.gnd", "2": "net.p3v3", "3": "net.vbus_5v"},
            ),
            _part(
                "C1",
                "capacitor",
                "10uF",
                "C_0603_1608Metric",
                {"1": "net.vbus_5v", "2": "net.gnd"},
            ),
            _part(
                "C2",
                "capacitor",
                "100nF",
                "C_0603_1608Metric",
                {"1": "net.vbus_5v", "2": "net.gnd"},
            ),
            _part(
                "C3",
                "capacitor",
                "10uF",
                "C_0603_1608Metric",
                {"1": "net.p3v3", "2": "net.gnd"},
            ),
            _part(
                "C4",
                "capacitor",
                "100nF",
                "C_0603_1608Metric",
                {"1": "net.p3v3", "2": "net.gnd"},
            ),
        ),
        nets=(
            _net("net.vbus_5v", "VBUS_5V"),
            _net("net.p3v3", "+3V3"),
            _net("net.gnd", "GND"),
        ),
    )


def _strapping() -> TopologyFragment:
    return TopologyFragment(
        components=(
            _part(
                "SW2",
                "switch",
                "BOOT",
                "SW_SPST_TS-1088-xR020",
                {"1": "net.boot", "2": "net.gnd"},
            ),
        ),
        nets=(_net("net.boot", "BOOT"),),
        constraints=("ESP32-C3 strapping and boot-button assignments",),
    )


def _firmware() -> TopologyFragment:
    return TopologyFragment(
        components=(),
        nets=(),
        constraints=("firmware GPIO assignments must match declared electrical pads",),
    )


def _safety() -> TopologyFragment:
    return TopologyFragment(
        components=(),
        nets=(),
        constraints=("declared voltage, current, hazard, and certification boundary",),
    )


_TEMPLATES: dict[str, Callable[[], TopologyFragment]] = {
    "esp32c3_strapping_boot": _strapping,
    "firmware_pin_map": _firmware,
    "i2c_bus_pullup": _i2c,
    "safety_power_boundary": _safety,
    "single_ldo_power_tree": _ldo,
    "usb_c_cc_termination": _usb,
}


def synthesize_topology(
    block_ids: tuple[str, ...] | list[str],
    *,
    registry: FunctionalBlockRegistry | None = None,
) -> TopologyFragment:
    """Return the deterministic fixture fragment for declared blocks."""
    loaded = registry or load_functional_block_registry()
    known = {contract.block_id for contract in loaded.contracts}
    unknown = sorted(set(block_ids) - known)
    if unknown:
        raise TopologySynthesisError("unknown functional block: " + ", ".join(unknown))
    missing_templates = sorted(set(block_ids) - set(_TEMPLATES))
    if missing_templates:
        raise TopologySynthesisError(
            "functional block has no topology template (検証不能): " + ", ".join(missing_templates)
        )
    components: dict[str, FixtureComponentSpec] = {}
    nets: dict[str, FixtureNetSpec] = {}
    constraints: set[str] = set()
    for block_id in sorted(set(block_ids)):
        fragment = _TEMPLATES[block_id]()
        for component in fragment.components:
            previous = components.get(component.refdes)
            if previous is not None and previous != component:
                raise TopologySynthesisError(
                    f"topology templates conflict for component: {component.refdes}"
                )
            components[component.refdes] = component
        for net in fragment.nets:
            previous = nets.get(net.net_id)
            if previous is not None and previous != net:
                raise TopologySynthesisError(f"topology templates conflict for net: {net.net_id}")
            nets[net.net_id] = net
        constraints.update(fragment.constraints)
    return TopologyFragment(
        components=tuple(components[key] for key in sorted(components)),
        nets=tuple(nets[key] for key in sorted(nets)),
        constraints=tuple(sorted(constraints)),
    )


__all__ = ["TopologyFragment", "TopologySynthesisError", "synthesize_topology"]
