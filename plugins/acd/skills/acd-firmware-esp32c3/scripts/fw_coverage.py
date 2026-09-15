# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@3ff208492908cc07a997a26b6fa469078fdaa26a",
# ]
# ///
"""Parse and evaluate gcovr coverage without promoting it to Evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, cast

from acd.schema.fw_coverage import (
    CoverageFile,
    CoverageFloor,
    CoverageReport,
    CoverageResult,
)


def _number(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if int(value) != value or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def _metric(item: Mapping[str, Any], prefix: str, key: str) -> int:
    direct = item.get(f"{prefix}_{key}")
    if direct is not None:
        return _number(direct, f"{prefix}_{key}")
    nested = item.get(prefix)
    if isinstance(nested, Mapping):
        value = cast(Mapping[str, object], nested).get(key)
        if value is not None:
            return _number(value, f"{prefix}.{key}")
    return 0


def parse_gcovr_json(text: str) -> CoverageReport:
    """Parse a gcovr JSON document into a deterministic report."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("gcovr JSON is malformed") from exc
    if not isinstance(raw, dict):
        raise ValueError("gcovr JSON must be an object")
    raw_object = cast(dict[str, object], raw)
    raw_files = raw_object.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("gcovr JSON must contain a files array")
    files: list[CoverageFile] = []
    for raw_file in cast(list[object], raw_files):
        if not isinstance(raw_file, Mapping):
            raise ValueError("gcovr file entry must be an object")
        entry = cast(Mapping[str, object], raw_file)
        path = entry.get("file", entry.get("path"))
        if not isinstance(path, str) or not path.strip():
            raise ValueError("gcovr file entry has no path")
        files.append(
            CoverageFile(
                path=path,
                lines_total=_metric(entry, "line", "total"),
                lines_covered=_metric(entry, "line", "covered"),
                branches_total=_metric(entry, "branch", "total"),
                branches_covered=_metric(entry, "branch", "covered"),
            )
        )
    files.sort(key=lambda item: item.path)
    line_total = sum(item.lines_total for item in files)
    line_covered = sum(item.lines_covered for item in files)
    branch_total = sum(item.branches_total for item in files)
    branch_covered = sum(item.branches_covered for item in files)
    return CoverageReport(
        files=files,
        line_pct=100.0 * line_covered / line_total if line_total else 100.0,
        branch_pct=100.0 * branch_covered / branch_total if branch_total else 100.0,
    )


def evaluate_coverage(
    report: CoverageReport | None,
    floor: CoverageFloor,
) -> CoverageResult:
    """Evaluate a report against its declared floor."""
    if report is None:
        return CoverageResult(
            status="unknown",
            floor=floor,
            findings=["coverage_report_missing"],
        )
    findings: list[str] = []
    if report.line_pct < floor.line_pct_min:
        findings.append(
            f"line coverage {report.line_pct:.3f}% is below "
            f"{floor.line_pct_min:.3f}%"
        )
    if floor.branch_pct_min is not None and report.branch_pct < floor.branch_pct_min:
        findings.append(
            f"branch coverage {report.branch_pct:.3f}% is below "
            f"{floor.branch_pct_min:.3f}%"
        )
    return CoverageResult(
        status="fail" if findings else "pass",
        report=report,
        floor=floor,
        findings=findings,
    )


def run_gcovr(
    build_dir: str,
    *,
    gcovr: str = "gcovr",
) -> str | None:
    """Run gcovr only when it is available on PATH."""
    executable = shutil.which(gcovr)
    if executable is None:
        return None
    completed = subprocess.run(
        [executable, "--json", "--root", build_dir, build_dir],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "gcovr failed")
    return completed.stdout


__all__ = ["evaluate_coverage", "parse_gcovr_json", "run_gcovr"]
