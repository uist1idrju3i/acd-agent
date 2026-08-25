"""GD1 electrical Evidence construction tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest

from acd.adapters.kicad.gates import GateError
from acd.core.design_predicates import PredicateResult
from acd.core.functional_blocks import load_functional_block_registry
from acd.pipeline.gd1_board import build_electrical_evidence
from acd.schema.evidence import Evidence
from acd.schema.tool_envelope import ToolEnvelope


def _envelope(
    context: Literal["container", "host", "unknown"] = "host",
    digest: str | None = None,
) -> ToolEnvelope:
    return ToolEnvelope(
        tool_name="kicad-cli",
        tool_version="10.0.5",
        format_version="json",
        config_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        output_hash="sha256:" + "c" * 64,
        execution_env=f"linux-x86_64; container={digest or 'none'}",
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions="test",
        convergence_state="converged",
        target_revision="r3",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        exit_code=0,
    )


def _build(envelope: ToolEnvelope) -> Evidence:
    return build_electrical_evidence(
        revision="r3",
        subject_node="board.gd1",
        envelope=envelope,
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        order_readiness_status="ready",
        design_predicates=_passing_predicates(),
        functional_block_contract=_contract_claim(),
        declared_blocks=_declared_blocks(),
    )


def _contract_claim() -> str:
    registry = load_functional_block_registry()
    return f"{registry.registry_id}:{registry.registry_hash}"


def _declared_blocks() -> tuple[str, ...]:
    return (
        "esp32c3_strapping_boot",
        "firmware_pin_map",
        "i2c_bus_pullup",
        "safety_power_boundary",
        "single_ldo_power_tree",
        "usb_c_cc_termination",
    )


def _passing_predicates() -> tuple[PredicateResult, ...]:
    return tuple(
        PredicateResult(name=name, status="pass", detail="ok")
        for name in (
            "usb_cc",
            "i2c_pullup",
            "strapping_pin",
            "pin_firmware_alignment",
            "power_decoupling",
            "power_boundary",
            "led_series_element",
        )
    )


def test_electrical_evidence_is_provisional_on_host() -> None:
    evidence = _build(_envelope())
    assert evidence.is_provisional()
    assert not evidence.supports_authoritative_pass("r3")


def test_missing_gate_value_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown"):
        build_electrical_evidence(
            revision="r3",
        subject_node="board.gd1",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status=None,
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=_passing_predicates(),
            functional_block_contract=_contract_claim(),
            declared_blocks=_declared_blocks(),
        )


def test_missing_design_predicates_fails_closed() -> None:
    with pytest.raises(ValueError, match="design predicate set is incomplete"):
        build_electrical_evidence(
            revision="r3",
        subject_node="board.gd1",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status="measured_pass",
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=(),
            functional_block_contract=_contract_claim(),
            declared_blocks=_declared_blocks(),
        )


@pytest.mark.parametrize(
    "predicates",
    [
        _passing_predicates()[:5],
        (*_passing_predicates(), PredicateResult(name="extra", status="pass", detail="ok")),
    ],
)
def test_incomplete_design_predicates_fail_closed(
    predicates: tuple[PredicateResult, ...],
) -> None:
    with pytest.raises(ValueError, match="design predicate set is incomplete"):
        build_electrical_evidence(
            revision="r3",
        subject_node="board.gd1",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status="measured_pass",
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=predicates,
            functional_block_contract=_contract_claim(),
            declared_blocks=_declared_blocks(),
        )


def test_design_predicate_claims_are_recorded_in_fixed_order() -> None:
    predicates = tuple(
        PredicateResult(name=name, status="pass", detail="ok")
        for name in (
            "usb_cc",
            "i2c_pullup",
            "strapping_pin",
            "pin_firmware_alignment",
            "power_decoupling",
            "power_boundary",
            "led_series_element",
        )
    )
    evidence = build_electrical_evidence(
        revision="r3",
        subject_node="board.gd1",
        envelope=_envelope(),
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        order_readiness_status="ready",
        design_predicates=predicates,
        functional_block_contract=_contract_claim(),
        declared_blocks=_declared_blocks(),
    )
    count = len(predicates)
    assert [claim.property for claim in evidence.claims[-count:]] == [
        predicate.name for predicate in predicates
    ]
    assert all(
        claim.value == "pass" and claim.verified for claim in evidence.claims[-count:]
    )


@pytest.mark.parametrize("status", ["unknown", "fail"])
def test_nonpassing_design_predicate_status_fails_closed(
    status: Literal["unknown", "fail"],
) -> None:
    predicates = tuple(
        PredicateResult(
            name=name,
            status=status if name == "i2c_pullup" else "pass",
            detail="not verified" if name == "i2c_pullup" else "ok",
        )
        for name in (
            "usb_cc",
            "i2c_pullup",
            "strapping_pin",
            "pin_firmware_alignment",
            "power_decoupling",
            "power_boundary",
            "led_series_element",
        )
    )
    with pytest.raises(GateError, match="i2c_pullup"):
        build_electrical_evidence(
            revision="r3",
            subject_node="board.gd1",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status="measured_pass",
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=predicates,
            functional_block_contract=_contract_claim(),
            declared_blocks=_declared_blocks(),
        )


def test_not_applicable_predicates_are_omitted_from_verified_claims() -> None:
    predicates = tuple(
        PredicateResult(
            name=name,
            status="not_applicable" if name in {"usb_cc", "i2c_pullup"} else "pass",
            detail="not required" if name in {"usb_cc", "i2c_pullup"} else "ok",
        )
        for name in (
            "usb_cc",
            "i2c_pullup",
            "strapping_pin",
            "pin_firmware_alignment",
            "power_decoupling",
            "power_boundary",
            "led_series_element",
        )
    )
    evidence = build_electrical_evidence(
        revision="r3",
        subject_node="board.gd1",
        envelope=_envelope(),
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        order_readiness_status="ready",
        design_predicates=predicates,
        functional_block_contract=_contract_claim(),
        declared_blocks=_declared_blocks(),
    )
    properties = {claim.property for claim in evidence.claims}
    assert "usb_cc" not in properties
    assert "i2c_pullup" not in properties
    assert "functional_block_contract" in properties
    assert "declared_functional_blocks" in properties


@pytest.mark.parametrize(
    ("contract", "blocks"),
    [
        (None, _declared_blocks()),
        (_contract_claim(), ()),
        (_contract_claim(), ("",)),
    ],
)
def test_missing_functional_block_evidence_metadata_fails_closed(
    contract: object,
    blocks: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="functional block evidence"):
        build_electrical_evidence(
            revision="r3",
            subject_node="board.gd1",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status="measured_pass",
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=_passing_predicates(),
            functional_block_contract=contract,
            declared_blocks=blocks,
        )


def test_missing_subject_node_fails_closed() -> None:
    with pytest.raises(ValueError, match="subject node is unknown"):
        build_electrical_evidence(
            revision="r3",
            subject_node="",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status="measured_pass",
            dfm_status="pass",
            order_readiness_status="ready",
            design_predicates=_passing_predicates(),
            functional_block_contract=_contract_claim(),
            declared_blocks=_declared_blocks(),
        )


def test_claims_use_the_graph_derived_subject_node() -> None:
    evidence = build_electrical_evidence(
        revision="r3",
        subject_node="board.custom",
        envelope=_envelope(),
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        order_readiness_status="ready",
        design_predicates=_passing_predicates(),
        functional_block_contract=_contract_claim(),
        declared_blocks=_declared_blocks(),
    )
    assert {claim.subject_node for claim in evidence.claims} == {"board.custom"}
