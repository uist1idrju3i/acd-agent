"""Tests for functional-block topology synthesis."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.functional_block_entry import register_functional_block_contract
from acd.core.functional_blocks import load_functional_block_registry
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


def test_template_local_duplicates_are_rejected() -> None:
    duplicate_refdes = {
        "schema_version": "0.1",
        "templates": [
            {
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
                    },
                    {
                        "refdes": "R1",
                        "part_request": {
                            "kind": "resistor",
                            "value": "2k",
                            "package": "R_0603_1608Metric",
                        },
                    },
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="refdes values"):
        TopologyTemplatesDocument.model_validate(duplicate_refdes)

    duplicate_net_id = {
        "schema_version": "0.1",
        "templates": [
            {
                "template_id": "one",
                "block_id": "safety_power_boundary",
                "nets": [{"net_id": "net.one"}, {"net_id": "net.one"}],
            }
        ],
    }
    with pytest.raises(ValueError, match="net IDs"):
        TopologyTemplatesDocument.model_validate(duplicate_net_id)


@pytest.mark.parametrize(
    ("field", "message"),
    [("template_id", "template IDs"), ("block_id", "block IDs")],
)
def test_document_template_identity_duplicates_are_rejected(
    field: str,
    message: str,
) -> None:
    first = {
        "template_id": "one",
        "block_id": "safety_power_boundary",
    }
    second = {
        "template_id": "two",
        "block_id": "firmware_pin_map",
    }
    second[field] = first[field]
    with pytest.raises(ValueError, match=message):
        TopologyTemplatesDocument.model_validate(
            {"schema_version": "0.1", "templates": [first, second]}
        )


def test_shared_net_collision_is_rejected() -> None:
    with pytest.raises(ValueError, match="shared net IDs"):
        TopologyTemplatesDocument.model_validate(
            {
                "schema_version": "0.1",
                "shared_nets": [{"net_id": "net.gnd"}, {"net_id": "net.gnd"}],
                "templates": [
                    {
                        "template_id": "one",
                        "block_id": "safety_power_boundary",
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="collide with shared nets"):
        TopologyTemplatesDocument.model_validate(
            {
                "schema_version": "0.1",
                "shared_nets": [{"net_id": "net.gnd"}],
                "templates": [
                    {
                        "template_id": "one",
                        "block_id": "safety_power_boundary",
                        "nets": [{"net_id": "net.gnd"}],
                    }
                ],
            }
        )


def test_alternative_templates_may_repeat_refdes_and_net_ids() -> None:
    document = TopologyTemplatesDocument.model_validate(
        {
            "schema_version": "0.1",
            "shared_nets": [{"net_id": "net.gnd"}],
            "templates": [
                {
                    "template_id": "one",
                    "block_id": "safety_power_boundary",
                    "components": [
                        {
                            "refdes": "U2",
                            "part_request": {
                                "kind": "ic",
                                "value": "one",
                                "package": "one",
                            },
                            "pads": {"1": "net.gnd"},
                        }
                    ],
                    "nets": [{"net_id": "net.local"}],
                },
                {
                    "template_id": "two",
                    "block_id": "firmware_pin_map",
                    "components": [
                        {
                            "refdes": "U2",
                            "part_request": {
                                "kind": "ic",
                                "value": "two",
                                "package": "two",
                            },
                            "pads": {"1": "net.gnd"},
                        }
                    ],
                    "nets": [{"net_id": "net.local"}],
                },
            ],
        }
    )
    assert len(document.templates) == 2


def test_selected_alternative_conflicts_fail_closed(tmp_path: Path) -> None:
    templates = {
        "schema_version": "0.1",
        "shared_nets": [{"net_id": "net.gnd"}],
        "templates": [
            {
                "template_id": "one",
                "block_id": "safety_power_boundary",
                "components": [
                    {
                        "refdes": "U2",
                        "part_request": {
                            "kind": "ic",
                            "value": "one",
                            "package": "one",
                        },
                        "pads": {"1": "net.gnd"},
                    }
                ],
            },
            {
                "template_id": "two",
                "block_id": "firmware_pin_map",
                "components": [
                    {
                        "refdes": "U2",
                        "part_request": {
                            "kind": "ic",
                            "value": "two",
                            "package": "two",
                        },
                        "pads": {"1": "net.gnd"},
                    }
                ],
            },
        ],
    }
    path = tmp_path / "topology-templates.json"
    path.write_text(json.dumps(templates), encoding="utf-8")
    with pytest.raises(TopologySynthesisError, match="conflict"):
        synthesize_topology(
            ["safety_power_boundary", "firmware_pin_map"],
            templates_path=path,
        )


def test_synthesis_emits_only_selected_template_and_shared_nets(
    tmp_path: Path,
) -> None:
    templates = {
        "schema_version": "0.1",
        "shared_nets": [{"net_id": "net.gnd"}],
        "templates": [
            {
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
                        "pads": {"1": "net.gnd"},
                    }
                ],
            },
            {
                "template_id": "two",
                "block_id": "firmware_pin_map",
                "nets": [{"net_id": "net.other"}],
            },
        ],
    }
    path = tmp_path / "topology-templates.json"
    path.write_text(json.dumps(templates), encoding="utf-8")
    fragment = synthesize_topology(
        ["safety_power_boundary"],
        templates_path=path,
    )
    assert [net.net_id for net in fragment.nets] == ["net.gnd"]


def test_registered_block_reaches_synthesis_without_python_changes(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "functional-block-registry.json"
    registry_path.write_text(
        (
            Path(__file__).parents[2] / "contracts" / "functional-block-registry.json"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    register_functional_block_contract(
        {
            "block_id": "data_only_block",
            "title": "Data-only block",
            "description": "A test block registered without synthesis code changes.",
            "required_predicates": ["power_boundary"],
            "allowed_change_dimensions": [],
        },
        registry_path,
    )
    topology_path = tmp_path / "topology-templates.json"
    topology_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "templates": [
                    {
                        "template_id": "data-only-template",
                        "block_id": "data_only_block",
                        "components": [
                            {
                                "refdes": "R1",
                                "part_request": {
                                    "kind": "resistor",
                                    "value": "1k",
                                    "package": "R_0603_1608Metric",
                                },
                                "pads": {"1": "net.local"},
                            }
                        ],
                        "nets": [{"net_id": "net.local"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fragment = synthesize_topology(
        ["data_only_block"],
        registry=load_functional_block_registry(registry_path),
        templates_path=topology_path,
    )
    assert [component.refdes for component in fragment.components] == ["R1"]
    assert [net.net_id for net in fragment.nets] == ["net.local"]


def test_pad_cannot_reference_another_template_net() -> None:
    with pytest.raises(ValueError, match="undeclared nets"):
        TopologyTemplatesDocument.model_validate(
            {
                "schema_version": "0.1",
                "templates": [
                    {
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
                                "pads": {"1": "net.other"},
                            }
                        ],
                        "nets": [{"net_id": "net.one"}],
                    },
                    {
                        "template_id": "two",
                        "block_id": "firmware_pin_map",
                        "nets": [{"net_id": "net.other"}],
                    },
                ],
            }
        )
