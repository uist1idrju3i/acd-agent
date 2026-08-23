"""Tests for the functional-block registry declaration entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.functional_block_entry import register_functional_block_contract
from acd.core.functional_blocks import FunctionalBlockContractError, load_functional_block_registry


def _contract(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "block_id": "usb_power_monitor",
        "title": "USB power monitor",
        "description": "Combines existing USB and power-boundary predicates.",
        "mandatory": False,
        "required_predicates": ["usb_cc", "power_boundary"],
        "allowed_change_dimensions": [],
    }
    value.update(overrides)
    return value


def _registry_copy(tmp_path: Path) -> Path:
    path = tmp_path / "functional-block-registry.json"
    path.write_text(
        (Path(__file__).parents[2] / "contracts" / "functional-block-registry.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    return path


def test_registers_new_contract_and_returns_hash_provenance(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(_contract(), ensure_ascii=False),
        encoding="utf-8",
    )

    dry_run = register_functional_block_contract(
        contract_path,
        registry_path,
        dry_run=True,
    )
    assert dry_run.written is False
    assert dry_run.contract_source == str(contract_path)
    assert dry_run.prior_registry_hash != dry_run.new_registry_hash
    assert "usb_power_monitor" not in {
        item.block_id for item in load_functional_block_registry(registry_path).contracts
    }

    result = register_functional_block_contract(contract_path, registry_path)
    assert result.written is True
    assert result.prior_registry_hash == dry_run.prior_registry_hash
    assert result.new_registry_hash == dry_run.new_registry_hash
    loaded = load_functional_block_registry(registry_path)
    assert loaded.registry_hash == result.new_registry_hash
    assert loaded.contracts[-1].block_id == "usb_power_monitor"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"block_id": "i2c_bus_pullup"}, "already registered"),
        ({"required_predicates": ["predicate_that_does_not_exist"]}, "unknown predicates"),
        (
            {"allowed_change_dimensions": ["copper_layer_count"]},
            "non-explorable change dimensions",
        ),
        ({"allowed_change_dimensions": ["dimension_that_does_not_exist"]}, "unknown values"),
    ],
)
def test_invalid_contracts_fail_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    registry_path = _registry_copy(tmp_path)
    with pytest.raises((FunctionalBlockContractError, ValueError), match=message):
        register_functional_block_contract(
            json.dumps(_contract(**overrides)),
            registry_path,
        )
    assert registry_path.read_text(encoding="utf-8") == (
        Path(__file__).parents[2] / "contracts" / "functional-block-registry.json"
    ).read_text(encoding="utf-8")


def test_malformed_contract_json_fails_closed(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    with pytest.raises(FunctionalBlockContractError, match="JSON is invalid"):
        register_functional_block_contract("{", registry_path)


def test_missing_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FunctionalBlockContractError, match="registry is invalid"):
        register_functional_block_contract(
            json.dumps(_contract()),
            tmp_path / "missing-registry.json",
        )
