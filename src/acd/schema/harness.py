"""Declared wire-harness contract and deterministic gate result contracts."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
)
from acd.schema.dfa_review import DfaFinding

HarnessStatus = Literal["pass", "fail", "unknown"]
WireConductor = Literal["copper", "tinned_copper"]
WireShield = Literal["none", "braid", "foil", "braid_foil"]


class HarnessConnector(AcdModel):
    connector_id: NodeId
    graph_component_id: NodeId | None = None
    housing_mpn: NonEmptyStr | None = None
    terminal_mpn: NonEmptyStr | None = None
    keying: NonEmptyStr | None = None
    mating_cycles_rated: int | None = Field(default=None, gt=0)
    retention_force_n: FiniteFloat | None = Field(default=None, gt=0)
    polarity_guard: bool | None = None


class TemperatureDeratingPoint(AcdModel):
    temp_c: FiniteFloat
    factor: FiniteFloat = Field(gt=0, le=1)


class HarnessWireType(AcdModel):
    wire_type_id: NodeId
    conductor: WireConductor
    cross_section_mm2: FiniteFloat = Field(gt=0)
    awg: int | None = Field(default=None, gt=0)
    insulation_rating_v: FiniteFloat = Field(gt=0)
    insulation_temp_c: FiniteFloat = Field(gt=0)
    resistance_mohm_per_m: FiniteFloat = Field(gt=0)
    ampacity_a: FiniteFloat = Field(gt=0)
    ampacity_reference_temp_c: FiniteFloat
    shield: WireShield = "none"
    flex_rated_cycles: int | None = Field(default=None, gt=0)
    temperature_derating: list[TemperatureDeratingPoint] = Field(
        default_factory=list[TemperatureDeratingPoint]
    )

    @model_validator(mode="after")
    def validate_derating(self) -> HarnessWireType:
        temperatures = [point.temp_c for point in self.temperature_derating]
        if len(temperatures) != len(set(temperatures)):
            raise ValueError("temperature_derating temperatures must be unique")
        if temperatures != sorted(temperatures):
            raise ValueError("temperature_derating temperatures must be sorted")
        if not math.isfinite(self.insulation_temp_c) or not math.isfinite(
            self.ampacity_reference_temp_c
        ):
            raise ValueError("wire temperature values must be finite")
        return self


class BundleDerating(AcdModel):
    wires_in_bundle: int = Field(ge=1)
    factor: FiniteFloat = Field(gt=0, le=1)


class HarnessEndpoint(AcdModel):
    connector_id: NodeId
    cavity: NonEmptyStr


class HarnessWire(AcdModel):
    wire_id: NodeId
    net_id: NodeId
    wire_type_id: NodeId
    from_: HarnessEndpoint = Field(alias="from")
    to: HarnessEndpoint
    length_mm: FiniteFloat = Field(gt=0)
    slack_mm: FiniteFloat = Field(ge=0)
    bend_radius_min_mm: FiniteFloat | None = Field(default=None, gt=0)
    return_wire_id: NodeId | None = None
    twisted_pair_group: NonEmptyStr | None = None

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class HarnessRoute(AcdModel):
    route_id: NodeId
    wire_ids: list[NodeId] = Field(min_length=1)
    path_length_mm: FiniteFloat = Field(gt=0)
    min_bend_radius_mm: dict[NodeId, FiniteFloat] = Field(
        default_factory=dict[NodeId, FiniteFloat]
    )
    moving_section: bool = False
    expected_flex_cycles: int | None = Field(default=None, gt=0)
    bend_radius_dynamic_mm: FiniteFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_route(self) -> HarnessRoute:
        if len(set(self.wire_ids)) != len(self.wire_ids):
            raise ValueError("route wire_ids must be unique")
        if not set(self.min_bend_radius_mm) <= set(self.wire_ids):
            raise ValueError("route bend-radius entries must reference route wires")
        if any(value <= 0 for value in self.min_bend_radius_mm.values()):
            raise ValueError("route bend radii must be positive")
        return self


class HarnessServiceExpectation(AcdModel):
    expected_mating_cycles: int | None = Field(default=None, gt=0)
    min_retention_force_n: FiniteFloat | None = Field(default=None, gt=0)


class HarnessSegregationPolicy(AcdModel):
    min_spacing_mm: FiniteFloat = Field(gt=0)


class HarnessContract(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["harness"] = "harness"
    harness_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    ambient_temperature_c: FiniteFloat
    bundle_derating: BundleDerating | None = None
    connectors: list[HarnessConnector] = Field(min_length=1)
    wire_types: list[HarnessWireType] = Field(min_length=1)
    wires: list[HarnessWire] = Field(min_length=1)
    routes: list[HarnessRoute] = Field(default_factory=list[HarnessRoute])
    service_expectation: HarnessServiceExpectation | None = None
    segregation_policy: HarnessSegregationPolicy | None = None

    @model_validator(mode="after")
    def validate_references(self) -> HarnessContract:
        connector_ids = [item.connector_id for item in self.connectors]
        wire_type_ids = [item.wire_type_id for item in self.wire_types]
        wire_ids = [item.wire_id for item in self.wires]
        route_ids = [item.route_id for item in self.routes]
        if len(connector_ids) != len(set(connector_ids)):
            raise ValueError("connector_id entries must be unique")
        if len(wire_type_ids) != len(set(wire_type_ids)):
            raise ValueError("wire_type_id entries must be unique")
        if len(wire_ids) != len(set(wire_ids)):
            raise ValueError("wire_id entries must be unique")
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("route_id entries must be unique")
        connector_set = set(connector_ids)
        wire_type_set = set(wire_type_ids)
        wire_set = set(wire_ids)
        for wire in self.wires:
            if wire.wire_type_id not in wire_type_set:
                raise ValueError(f"wire references unknown wire_type_id: {wire.wire_type_id}")
            for endpoint in (wire.from_, wire.to):
                if endpoint.connector_id not in connector_set:
                    raise ValueError(
                        f"wire references unknown connector_id: {endpoint.connector_id}"
                    )
            if wire.return_wire_id is not None and wire.return_wire_id not in wire_set:
                raise ValueError(
                    f"wire references unknown return_wire_id: {wire.return_wire_id}"
                )
        cavity_keys = [
            (endpoint.connector_id, endpoint.cavity)
            for wire in self.wires
            for endpoint in (wire.from_, wire.to)
        ]
        if len(cavity_keys) != len(set(cavity_keys)):
            raise ValueError("connector cavities must be unique")
        all_wire_ids = set(wire_ids)
        for route in self.routes:
            if not set(route.wire_ids) <= all_wire_ids:
                raise ValueError("route references unknown wire_id")
        if not math.isfinite(self.ambient_temperature_c):
            raise ValueError("ambient_temperature_c must be finite")
        return self


class HarnessCheckResult(AcdModel):
    check_id: NonEmptyStr
    status: HarnessStatus
    reason: NonEmptyStr
    subject_ids: list[NodeId] = Field(default_factory=list[NodeId])
    details: dict[str, Any] = Field(default_factory=dict[str, Any])


class HarnessResult(AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["harness_check"] = "harness_check"
    harness_id: NonEmptyStr
    graph_id: NonEmptyStr
    revision: Revision
    status: HarnessStatus
    checks: list[HarnessCheckResult] = Field(min_length=1)
    input_hashes: dict[str, Sha256]
    dfa_findings: list[DfaFinding] = Field(default_factory=list[DfaFinding])
