"""Deterministic parsing and evaluation of firmware functional-run records."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from statistics import fmean

from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.evidence import MeasuredQuantity, PhysicalEvidence
from acd.schema.functional_run import (
    FunctionalCheckReport,
    FunctionalRunRecord,
    FunctionalRunReport,
    LedExpectation,
    SerialExpectation,
)
from acd.schema.tool_envelope import ToolEnvelope


class FunctionalRunError(ValueError):
    """Raised when a functional run cannot produce a fail-closed result."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FunctionalRunError(f"could not parse run JSON: {path}") from exc


def _digest(path: Path) -> Sha256:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise FunctionalRunError(f"could not read functional-run file: {path}") from exc


def _resolve_file(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise FunctionalRunError("functional-run path escapes logs directory") from exc
    return candidate


def _unknown_check(reason: str) -> FunctionalCheckReport:
    return FunctionalCheckReport(status="unknown", reason=reason)


def _failed_check(reason: str) -> FunctionalCheckReport:
    return FunctionalCheckReport(status="fail", reason=reason)


def _unknown_run_report(run: FunctionalRunRecord, reason: str) -> FunctionalRunReport:
    unknown = _unknown_check(reason)
    return FunctionalRunReport(
        status="unknown",
        run_id=run.run_id,
        target_revision=run.target_revision,
        input_hash="unknown",
        build=unknown,
        flash=unknown,
        led=unknown,
        serial=unknown,
        error=reason,
    )


def _parse_build(
    run: FunctionalRunRecord,
    path: Path,
    artifact_sizes: Mapping[str, int],
) -> FunctionalCheckReport:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return _unknown_check(f"build log could not be read: {exc}")
    version_matches = [
        match.group(1)
        for line in lines
        if (match := re.fullmatch(r"ESP-IDF (\S+)", line)) is not None
    ]
    if not version_matches:
        return _unknown_check("build log ESP-IDF version line is missing")
    if version_matches[0] != run.esp_idf_version:
        return _failed_check(
            "build log ESP-IDF version does not match the run declaration"
        )
    if "Project build complete." not in lines:
        return _failed_check("build log does not declare successful completion")
    bin_artifact = next(
        item for item in run.build_artifacts if item.artifact_type == "bin"
    )
    size_pattern = re.compile(
        r"(?P<name>\S+) binary size 0x(?P<size>[0-9a-fA-F]+) bytes"
    )
    size_matches = [
        (match.group("name"), int(match.group("size"), 16))
        for line in lines
        if (match := size_pattern.fullmatch(line)) is not None
    ]
    if not size_matches:
        return _unknown_check("build log binary size line is missing")
    basename_matches = [
        size for name, size in size_matches if name == Path(bin_artifact.path).name
    ]
    if not basename_matches:
        return _failed_check(
            "build log binary size line does not identify the declared bin artifact"
        )
    if len(basename_matches) != 1:
        return _unknown_check("build log contains duplicate binary size lines")
    if basename_matches[0] != artifact_sizes[bin_artifact.path]:
        return _failed_check(
            "build log binary size does not match the declared bin artifact"
        )
    return FunctionalCheckReport(status="pass", measured_values={"artifact_count": 2.0})


def _parse_flash(
    run: FunctionalRunRecord,
    path: Path,
    bin_size: int,
) -> FunctionalCheckReport:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return _unknown_check(f"flash log could not be read: {exc}")
    if any("A fatal error occurred" in line for line in lines):
        return _failed_check("flash log reports a fatal error")
    chip_matches = [
        match.group(1)
        for line in lines
        if (match := re.match(r"^Chip is (\S+)", line)) is not None
    ]
    if not chip_matches:
        return _unknown_check("flash log chip line is missing")
    if chip_matches[0] != "ESP32-C3":
        return _failed_check("flash target chip is not ESP32-C3")
    write_pattern = re.compile(
        r"Wrote (?P<size>[0-9]+) bytes \([0-9]+ compressed\) "
        r"at (?P<offset>0x[0-9a-fA-F]+) in \S+ seconds"
    )
    writes = [
        (int(match.group("size")), int(match.group("offset"), 16))
        for line in lines
        if (match := write_pattern.search(line)) is not None
    ]
    if not writes:
        return _unknown_check("flash log write line is missing")
    verifications = [line for line in lines if line.strip() == "Hash of data verified."]
    if len(verifications) != len(writes):
        return _failed_check(
            "flash verification count does not match write count"
        )
    app_writes = [
        offset
        for size, offset in writes
        if size == bin_size and offset == run.app_flash_offset
    ]
    if not app_writes:
        return _failed_check(
            f"flash app image does not match offset 0x{run.app_flash_offset:x} "
            f"and size {bin_size}"
        )
    if "Hard resetting" not in "\n".join(lines):
        return _unknown_check("flash log completion marker is missing")
    return FunctionalCheckReport(
        status="pass",
        measured_values={"verified_writes": float(len(writes))},
    )


def _parse_led(path: Path, expectation: LedExpectation) -> FunctionalCheckReport:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        return _unknown_check(f"LED capture could not be read: {exc}")
    if not rows or rows[0] != ["timestamp_s", "level"]:
        return _unknown_check("LED capture header is invalid")
    samples: list[tuple[float, int]] = []
    try:
        for row in rows[1:]:
            if len(row) != 2:
                return _failed_check("LED capture contains a malformed row")
            timestamp = float(row[0])
            level = int(row[1])
            if not math.isfinite(timestamp) or level not in {0, 1}:
                return _unknown_check("LED capture contains an invalid sample")
            samples.append((timestamp, level))
    except ValueError:
        return _unknown_check("LED capture contains a non-numeric sample")
    if len(samples) < expectation.minimum_cycles * 2:
        return _failed_check("LED capture has too few samples")
    if any(current[0] <= previous[0] for previous, current in pairwise(samples)):
        return _unknown_check("LED capture timestamps are not strictly increasing")
    rising = [
        timestamp
        for (_previous_timestamp, previous_level), (timestamp, level) in pairwise(samples)
        if previous_level == 0 and level == 1
    ]
    if len(rising) < expectation.minimum_cycles:
        return _failed_check("LED capture has too few complete cycles")
    period = fmean(
        current - previous for previous, current in pairwise(rising)
    )
    frequency = 1 / period
    duration = samples[-1][0] - samples[0][0]
    high_duration = sum(
        current[0] - previous[0]
        for previous, current in pairwise(samples)
        if previous[1] == 1
    )
    duty = high_duration / duration if duration > 0 else math.nan
    if (
        abs(frequency - expectation.frequency_hz) > expectation.tolerance_hz
        or not expectation.duty_min <= duty <= expectation.duty_max
    ):
        return _failed_check(
            "LED frequency or duty is outside expectation: "
            f"frequency={frequency:.6f}, duty={duty:.6f}"
        )
    return FunctionalCheckReport(
        status="pass",
        measured_values={"frequency_hz": frequency, "duty_ratio": duty},
    )


def _parse_serial(
    path: Path,
    expectation: SerialExpectation,
    tag: str,
) -> FunctionalCheckReport:
    pattern = re.compile(
        rf"I \((\d+)\) {re.escape(tag)}: "
        r"temp=(-?\d+(?:\.\d+)?)C rh=(-?\d+(?:\.\d+)?)%"
    )
    sensor_prefix = re.compile(rf"^I \(\d+\) {re.escape(tag)}:")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return _unknown_check(f"serial log could not be read: {exc}")
    samples: list[tuple[float, float, float]] = []
    for line in lines:
        if not sensor_prefix.match(line):
            continue
        match = pattern.fullmatch(line)
        if match is None:
            return _unknown_check("serial log contains a malformed sensor line")
        timestamp_ms, temperature, humidity = (
            float(value) for value in match.groups()
        )
        samples.append((timestamp_ms / 1000, temperature, humidity))
    if len(samples) < expectation.minimum_samples:
        return _failed_check("serial log has too few samples")
    if any(current[0] <= previous[0] for previous, current in pairwise(samples)):
        return _unknown_check("serial log timestamps are not strictly increasing")
    temperatures = [sample[1] for sample in samples]
    humidities = [sample[2] for sample in samples]
    intervals = [
        current[0] - previous[0] for previous, current in pairwise(samples)
    ]
    period = fmean(intervals)
    if (
        min(temperatures) < expectation.temperature_min_deg_c
        or max(temperatures) > expectation.temperature_max_deg_c
        or min(humidities) < expectation.humidity_min_rh
        or max(humidities) > expectation.humidity_max_rh
        or any(
            abs(interval - expectation.period_s) > expectation.period_tolerance_s
            for interval in intervals
        )
    ):
        return _failed_check(
            f"serial values or period are outside expectation: period={period:.6f}"
        )
    return FunctionalCheckReport(
        status="pass",
        measured_values={
            "temperature_deg_c": fmean(temperatures),
            "humidity_rh": fmean(humidities),
            "period_s": period,
        },
    )


def _evidence(
    run: FunctionalRunRecord,
    check_name: str,
    check: FunctionalCheckReport,
    input_hash: Sha256,
    output_hash: Sha256,
) -> PhysicalEvidence:
    if check.status != "pass":
        raise FunctionalRunError(f"cannot create Evidence for non-passing check: {check_name}")
    quantities: list[MeasuredQuantity]
    if check_name == "build":
        quantities = [
            MeasuredQuantity(
                name="build_success",
                unit="boolean",
                value=1,
                expected_min=1,
                expected_max=1,
                tolerance=0,
            )
        ]
    elif check_name == "flash":
        quantities = [
            MeasuredQuantity(
                name="flash_verification",
                unit="boolean",
                value=1,
                expected_min=1,
                expected_max=1,
                tolerance=0,
            )
        ]
    elif check_name == "led":
        quantities = [
            MeasuredQuantity(
                name="led_frequency",
                unit="Hz",
                value=check.measured_values["frequency_hz"],
                expected_min=run.expectations.led.frequency_hz,
                expected_max=run.expectations.led.frequency_hz,
                tolerance=run.expectations.led.tolerance_hz,
            ),
            MeasuredQuantity(
                name="led_duty_ratio",
                unit="ratio",
                value=check.measured_values["duty_ratio"],
                expected_min=run.expectations.led.duty_min,
                expected_max=run.expectations.led.duty_max,
                tolerance=0,
            ),
        ]
    else:
        quantities = [
            MeasuredQuantity(
                name="temperature",
                unit="degC",
                value=check.measured_values["temperature_deg_c"],
                expected_min=run.expectations.serial.temperature_min_deg_c,
                expected_max=run.expectations.serial.temperature_max_deg_c,
                tolerance=0,
            ),
            MeasuredQuantity(
                name="humidity",
                unit="%RH",
                value=check.measured_values["humidity_rh"],
                expected_min=run.expectations.serial.humidity_min_rh,
                expected_max=run.expectations.serial.humidity_max_rh,
                tolerance=0,
            ),
            MeasuredQuantity(
                name="serial_period",
                unit="s",
                value=check.measured_values["period_s"],
                expected_min=run.expectations.serial.period_s,
                expected_max=run.expectations.serial.period_s,
                tolerance=run.expectations.serial.period_tolerance_s,
            ),
        ]
    acquired_at = {
        "build": run.build_at,
        "flash": run.flash_at,
        "led": run.acquired_at,
        "serial": run.acquired_at,
    }[check_name]
    envelope = ToolEnvelope(
        tool_name=f"acd-functional-{check_name}",
        tool_version="0.1",
        format_version="0.1",
        config_hash=canonical_json_sha256(run.expectations.model_dump(mode="json")),
        input_hash=input_hash,
        output_hash=output_hash,
        execution_env="python-3.12; deterministic firmware functional measurement",
        execution_context="host",
        measurement_conditions=(
            f"capture_route={run.serial_capture_route}; "
            f"serial_tag={run.serial_log_tag}; "
            f"esp_idf={run.esp_idf_version}; "
            f"toolchain={run.toolchain_version}; "
            f"project_git_commit={run.project_git_commit}"
        ),
        convergence_state="not_applicable",
        target_revision=run.target_revision,
        started_at=run.build_at,
        finished_at=run.recorded_at,
    )
    return PhysicalEvidence(
        evidence_id=f"evidence.functional.{run.run_id}.{check_name}",
        target_revision=run.target_revision,
        status="valid",
        envelope=envelope,
        claims=[],
        created_at=run.recorded_at,
        measurement_class="measured",
        instrument=run.instrument,
        acquired_at=acquired_at,
        measurements=quantities,
    )


def evaluate_functional_run(
    run: FunctionalRunRecord,
    logs_dir: Path,
) -> tuple[FunctionalRunReport, dict[str, PhysicalEvidence]]:
    """Evaluate all declared firmware checks from hashed files."""
    if run.measurement_class != "measured":
        return _unknown_run_report(
            run,
            "virtual functional measurements are not accepted by this CLI",
        ), {}
    references = list(run.build_artifacts) + list(run.logs)
    actual_hashes: dict[str, Sha256] = {}
    paths: dict[str, Path] = {}
    for reference in references:
        path = _resolve_file(logs_dir, reference.path)
        paths[reference.path] = path
        if not path.is_file():
            return _unknown_run_report(
                run,
                f"functional-run file is missing: {reference.path}",
            ), {}
        actual_hash = _digest(path)
        actual_hashes[reference.path] = actual_hash
        if actual_hash != reference.content_hash:
            reason = f"declared file hash mismatch: {reference.path}"
            return _unknown_run_report(run, reason), {}
    input_hash = canonical_json_sha256(
        {
            "run": run.model_dump(mode="json"),
            "files": actual_hashes,
        }
    )
    artifact_sizes = {item.path: paths[item.path].stat().st_size for item in run.build_artifacts}
    logs = {item.log_type: paths[item.path] for item in run.logs}
    checks = {
        "build": _parse_build(run, logs["build"], artifact_sizes),
        "flash": _parse_flash(
            run,
            logs["flash"],
            artifact_sizes[
                next(item.path for item in run.build_artifacts if item.artifact_type == "bin")
            ],
        ),
        "led": _parse_led(logs["led"], run.expectations.led),
        "serial": _parse_serial(
            logs["serial"],
            run.expectations.serial,
            run.serial_log_tag,
        ),
    }
    statuses = {check.status for check in checks.values()}
    overall_status = (
        "unknown"
        if "unknown" in statuses
        else "fail"
        if "fail" in statuses
        else "pass"
    )
    report = FunctionalRunReport(
        status=overall_status,
        run_id=run.run_id,
        target_revision=run.target_revision,
        input_hash=input_hash,
        build=checks["build"],
        flash=checks["flash"],
        led=checks["led"],
        serial=checks["serial"],
    )
    evidences: dict[str, PhysicalEvidence] = {}
    for name, check in checks.items():
        if check.status == "pass":
            evidences[name] = _evidence(
                run,
                name,
                check,
                input_hash,
                canonical_json_sha256(check.model_dump(mode="json")),
            )
    return report, evidences


def load_and_evaluate_functional_run(
    run_path: Path,
    logs_dir: Path,
) -> tuple[FunctionalRunRecord, FunctionalRunReport, dict[str, PhysicalEvidence]]:
    """Load a run contract and evaluate its referenced functional files."""
    value = _load_json(run_path)
    try:
        run = FunctionalRunRecord.model_validate(value)
    except Exception as exc:
        raise FunctionalRunError("functional run record is invalid") from exc
    report, evidences = evaluate_functional_run(run, logs_dir)
    return run, report, evidences
