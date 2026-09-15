from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from acd.schema import (
    HilMeasurementChannel,
    HilMeasurementPlan,
    HilRunRecord,
    HilSample,
    build_physical_evidence_from_hil,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/golden-design-1"


def _inputs() -> tuple[HilMeasurementPlan, HilRunRecord, str]:
    plan = HilMeasurementPlan.model_validate_json(
        (FIXTURE / "hil-plan.json").read_text(encoding="utf-8")
    )
    run = HilRunRecord.model_validate_json(
        (FIXTURE / "hil-run.json").read_text(encoding="utf-8")
    )
    log = (FIXTURE / "hil-virtual-log.txt").read_text(encoding="utf-8")
    return plan, run, log


def test_hil_builder_is_deterministic_and_measured_only() -> None:
    plan, run, log = _inputs()
    first = build_physical_evidence_from_hil(plan, run, virtual_log=log)
    second = build_physical_evidence_from_hil(plan, run, virtual_log=log)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.measurement_class == "measured"
    assert not first.supports_authoritative_pass(plan.revision)
    assert first.supports_measured_claim(plan.revision)


def test_hil_builder_records_uart_mismatch_as_unsupported() -> None:
    plan, run, log = _inputs()
    samples = [sample.model_dump(mode="json") for sample in run.samples]
    samples[0]["text"] = "different\n"
    changed = run.model_copy(
        update={"samples": TypeAdapter(list[HilSample]).validate_python(samples)}
    )
    evidence = build_physical_evidence_from_hil(plan, changed, virtual_log=log)
    uart = next(item for item in evidence.measurements if item.name == "uart_log_match")
    assert uart.value == 0
    assert not evidence.supports_measured_claim(plan.revision)


def test_hil_builder_rejects_undeclared_and_missing_channels() -> None:
    plan, run, log = _inputs()
    samples = [sample.model_dump(mode="json") for sample in run.samples]
    samples[0]["channel_id"] = "undeclared"
    with pytest.raises(ValueError, match="undeclared"):
        build_physical_evidence_from_hil(
            plan,
            run.model_copy(
                update={"samples": TypeAdapter(list[HilSample]).validate_python(samples)}
            ),
            virtual_log=log,
        )

    samples = [sample.model_dump(mode="json") for sample in run.samples[:-1]]
    with pytest.raises(ValueError, match="no sample"):
        build_physical_evidence_from_hil(
            plan,
            run.model_copy(
                update={"samples": TypeAdapter(list[HilSample]).validate_python(samples)}
            ),
            virtual_log=log,
        )


def test_hil_builder_rejects_unit_and_revision_mismatch() -> None:
    plan, run, log = _inputs()
    samples = [sample.model_dump(mode="json") for sample in run.samples]
    samples[1]["unit"] = "mA"
    changed = run.model_copy(
        update={"samples": TypeAdapter(list[HilSample]).validate_python(samples)}
    )
    with pytest.raises(ValueError, match="unit mismatch"):
        build_physical_evidence_from_hil(plan, changed, virtual_log=log)

    envelope = run.envelope.model_copy(update={"target_revision": "r2"})
    changed_run = run.model_copy(update={"envelope": envelope})
    with pytest.raises(ValueError, match="revision"):
        build_physical_evidence_from_hil(plan, changed_run, virtual_log=log)


def test_hil_builder_fails_closed_for_range_instrument_and_envelope() -> None:
    plan, run, log = _inputs()
    samples = [sample.model_dump(mode="json") for sample in run.samples]
    samples[1]["value"] = 9.0
    out_of_range = run.model_copy(
        update={"samples": TypeAdapter(list[HilSample]).validate_python(samples)}
    )
    evidence = build_physical_evidence_from_hil(plan, out_of_range, virtual_log=log)
    assert not evidence.supports_measured_claim(plan.revision)

    channels = [
        channel.model_copy(
            update={
                "instrument": channel.instrument.model_copy(update={"operator": "unknown"})
            }
        )
        for channel in plan.channels
    ]
    unknown_instrument = plan.model_copy(
        update={
            "channels": TypeAdapter(list[HilMeasurementChannel]).validate_python(channels)
        }
    )
    with pytest.raises(ValueError, match="unknown instrument"):
        build_physical_evidence_from_hil(unknown_instrument, run, virtual_log=log)

    envelope = run.envelope.model_copy(update={"input_hash": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="input_hash"):
        build_physical_evidence_from_hil(
            plan,
            run.model_copy(update={"envelope": envelope}),
            virtual_log=log,
        )
