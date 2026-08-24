"""Tests for functional-block topology synthesis."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.topology_synthesis import TopologySynthesisError, synthesize_topology
from acd.schema.common import canonical_json_sha256
from acd.schema.topology_template import TopologyTemplatesDocument


def test_gd1_blocks_synthesize_expected_subset() -> None:
    fragment = synthesize_topology(
        [
            "usb_c_cc_termination",
            "i2c_bus_pullup",
            "single_ldo_power_tree",
            "esp32c3_strapping_boot",
            "firmware_pin_map",
            "safety_power_boundary",
        ]
    )
    assert {"R1", "R2", "R4", "R5", "U2", "SW2"} <= {item.refdes for item in fragment.components}
    assert {"net.cc1", "net.cc2", "net.i2c_sda", "net.i2c_scl", "net.p3v3"} <= {
        item.net_id for item in fragment.nets
    }
    assert fragment.constraints
    assert canonical_json_sha256(
        {
            "components": [item.model_dump(mode="json") for item in fragment.components],
            "nets": [item.model_dump(mode="json") for item in fragment.nets],
            "constraints": list(fragment.constraints),
        }
    ) == "sha256:7254c7ba937187105aba5f8bdc200f8e51335b6d2ee93ddddd02bc2ad3f193ea"


def test_unknown_and_template_less_blocks_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(TopologySynthesisError, match="unknown"):
        synthesize_topology(["unknown_block"])

    templates = {
        "schema_version": "0.1",
        "templates": [
            {
                "template_id": "safety-power-boundary",
                "block_id": "safety_power_boundary",
            }
        ],
    }
    template_path = tmp_path / "topology-templates.json"
    template_path.write_text(json.dumps(templates), encoding="utf-8")
    with pytest.raises(TopologySynthesisError, match="検証不能"):
        synthesize_topology(["firmware_pin_map"], templates_path=template_path)


def test_invalid_topology_declarations_fail_closed(tmp_path: Path) -> None:
    base = {
        "schema_version": "0.1",
        "templates": [
            {
                "template_id": "safety-power-boundary",
                "block_id": "safety_power_boundary",
                "components": [
                    {
                        "refdes": "R1",
                        "part_request": {
                            "kind": "resistor",
                            "value": "1k",
                            "package": "R_0603_1608Metric",
                        },
                        "pads": {"1": "net.missing"},
                    }
                ],
            }
        ],
    }
    path = tmp_path / "invalid-topology-templates.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(TopologySynthesisError, match="undeclared nets"):
        synthesize_topology(["safety_power_boundary"], templates_path=path)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("template_id", "template IDs"),
        ("block_id", "block IDs"),
        ("refdes", "refdes values"),
        ("net_id", "net IDs"),
    ],
)
def test_topology_declaration_duplicates_are_rejected(field: str, message: str) -> None:
    first = {
        "template_id": "one",
        "block_id": "safety_power_boundary",
        "components": [
            {
                "refdes": "R1",
                "part_request": {
                    "kind": "resistor",
                    "value": "1k",
                    "package": "R_0603_1608Metric",
                },
            }
        ],
        "nets": [{"net_id": "net.one"}],
    }
    second = {
        "template_id": "two",
        "block_id": "firmware_pin_map",
        "components": [
            {
                "refdes": "R2" if field != "refdes" else "R1",
                "part_request": {
                    "kind": "resistor",
                    "value": "2k",
                    "package": "R_0603_1608Metric",
                },
            }
        ],
        "nets": [{"net_id": "net.two" if field != "net_id" else "net.one"}],
    }
    if field == "template_id":
        second["template_id"] = "one"
    if field == "block_id":
        second["block_id"] = "safety_power_boundary"
    with pytest.raises(ValueError, match=message):
        TopologyTemplatesDocument.model_validate(
            {"schema_version": "0.1", "templates": [first, second]}
        )
