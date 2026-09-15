"""Contracts and deterministic builder for physical HIL measurements."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, Revision, Sha256, Timestamp
from acd.schema.evidence import (
    MeasuredQuantity,
    MeasurementInstrument,
    PhysicalEvidence,
)
from acd.schema.tool_envelope import ToolEnvelope

HilChannelKind = Literal[
    "uart_log",
    "gpio_level",
    "analog_voltage",
    "i2c_transaction",
    "current_ma",
]


class HilExpectedRange(AcdModel):
    name: NonEmptyStr
    unit: NonEmptyStr
    expected_min: float
    expected_max: float
    tolerance: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> HilExpectedRange:
        if self.expected_min > self.expected_max:
            raise ValueError("HIL expected_min must not exceed expected_max")
        return self


class HilMeasurementChannel(AcdModel):
    channel_id: NonEmptyStr
    kind: HilChannelKind
    instrument: MeasurementInstrument
    expected: HilExpectedRange


class HilMeasurementPlan(AcdModel):
    graph_id: NonEmptyStr
    revision: Revision
    fixture_id: NonEmptyStr
    channels: list[HilMeasurementChannel] = Field(min_length=1)
    virtual_reference: Sha256

    @model_validator(mode="after")
    def validate_channels(self) -> HilMeasurementPlan:
        ids = [channel.channel_id for channel in self.channels]
        if len(ids) != len(set(ids)):
            raise ValueError("HIL channel IDs must be unique")
        return self

    @property
    def plan_id(self) -> str:
        return f"hil-plan.{self.graph_id}.{self.revision}"


class HilSample(AcdModel):
    channel_id: NonEmptyStr
    value: float | None = None
    text: NonEmptyStr | None = None
    unit: NonEmptyStr

    @model_validator(mode="after")
    def validate_value_or_text(self) -> HilSample:
        if (self.value is None) == (self.text is None):
            raise ValueError("HIL sample must contain exactly one of value or text")
        return self


class HilRunRecord(AcdModel):
    plan_id: NonEmptyStr
    acquired_at: Timestamp
    envelope: ToolEnvelope
    samples: list[HilSample] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_samples(self) -> HilRunRecord:
        ids = [sample.channel_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("HIL samples must contain one sample per channel")
        return self


def _line_set(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def build_physical_evidence_from_hil(
    plan: HilMeasurementPlan,
    run: HilRunRecord,
    *,
    virtual_log: str | None = None,
) -> PhysicalEvidence:
    """Build measured Evidence only from a complete HIL plan/run match."""
    if run.plan_id != plan.plan_id:
        raise ValueError("HIL run plan_id does not match the measurement plan")
    if run.envelope.target_revision != plan.revision:
        raise ValueError("HIL run envelope revision does not match the plan")
    if run.envelope.input_hash != plan.virtual_reference:
        raise ValueError("HIL run envelope input_hash does not match virtual reference")
    channels = {channel.channel_id: channel for channel in plan.channels}
    samples = {sample.channel_id: sample for sample in run.samples}
    undeclared = sorted(set(samples) - set(channels))
    missing = sorted(set(channels) - set(samples))
    if undeclared:
        raise ValueError(f"HIL sample channel is undeclared: {undeclared[0]}")
    if missing:
        raise ValueError(f"HIL declared channel has no sample: {missing[0]}")
    instruments = [channel.instrument for channel in plan.channels]
    if any(instrument.has_unknown() for instrument in instruments):
        raise ValueError("HIL plan contains unknown instrument fields")
    if len({instrument.model_dump_json() for instrument in instruments}) != 1:
        raise ValueError("HIL channels must use one measurement instrument")
    measurements: list[MeasuredQuantity] = []
    for channel in plan.channels:
        sample = samples[channel.channel_id]
        expected = channel.expected
        if channel.kind == "uart_log":
            if virtual_log is None or sample.text is None:
                raise ValueError("UART HIL channels require a virtual log and text sample")
            virtual_hash = hashlib.sha256(virtual_log.encode("utf-8")).hexdigest()
            if virtual_hash != plan.virtual_reference.removeprefix("sha256:"):
                raise ValueError("virtual log does not match the plan reference hash")
            match = int(_line_set(sample.text) == _line_set(virtual_log))
            measurements.append(
                MeasuredQuantity(
                    name="uart_log_match",
                    unit="bool",
                    value=match,
                    expected_min=1,
                    expected_max=1,
                    tolerance=0,
                )
            )
            continue
        if sample.value is None:
            raise ValueError(f"numeric HIL channel {channel.channel_id} has no value")
        if sample.unit != expected.unit:
            raise ValueError(f"HIL sample unit mismatch: {channel.channel_id}")
        measurements.append(
            MeasuredQuantity(
                name=expected.name,
                unit=expected.unit,
                value=sample.value,
                expected_min=expected.expected_min,
                expected_max=expected.expected_max,
                tolerance=expected.tolerance,
            )
        )
    acquired_at = run.acquired_at
    created_at = max(acquired_at, run.envelope.finished_at)
    return PhysicalEvidence(
        evidence_id=f"evidence.{plan.graph_id}.hil",
        target_revision=plan.revision,
        status="valid",
        envelope=run.envelope,
        claims=[],
        created_at=created_at,
        measurement_class="measured",
        instrument=instruments[0],
        acquired_at=acquired_at,
        measurements=measurements,
    )


__all__ = [
    "HilExpectedRange",
    "HilMeasurementChannel",
    "HilMeasurementPlan",
    "HilRunRecord",
    "HilSample",
    "build_physical_evidence_from_hil",
]
