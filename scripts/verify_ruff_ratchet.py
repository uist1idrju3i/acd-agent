"""Ratchet Ruff complexity rules against a committed per-file baseline.

The complexity family (``C901``, ``PLR0911``/``PLR0912``/``PLR0913``/``PLR0915``,
``PLR2004``) has hundreds of pre-existing findings, so enabling it in
``pyproject.toml`` would either fail immediately or require blanket ignores.
Instead this script runs Ruff with exactly those rules, counts findings per
``(path, rule)`` and compares them with ``contracts/ruff-ratchet-baseline.json``.
``--check`` fails closed when any pair exceeds its recorded count or a new pair
appears, and also when a count dropped without the baseline being lowered, so
the baseline always equals the current state and complexity can only go down;
``--write`` records the current counts after a refactor changed them.  The
report is an L3 observation and grants no pass authority.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from acd.schema.common import AcdModel, NonEmptyStr

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "contracts" / "ruff-ratchet-baseline.json"
RATCHET_RULES: tuple[str, ...] = (
    "C901",
    "PLR0911",
    "PLR0912",
    "PLR0913",
    "PLR0915",
    "PLR2004",
)
SCAN_PATHS: tuple[str, ...] = ("src", "scripts", "plugins")
EXCLUDE_GLOB = "**/tests"


class RatchetEntry(AcdModel):
    path: NonEmptyStr
    rule: NonEmptyStr
    count: int = Field(ge=1)


class RatchetBaseline(AcdModel):
    schema_version: Literal["1.0"] = "1.0"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    rules: list[str]
    scan_paths: list[str]
    entries: list[RatchetEntry]


class RatchetReport(AcdModel):
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    status: Literal["pass", "fail"]
    baseline: NonEmptyStr
    baseline_total: int
    current_total: int
    regressions: list[str]
    improvements: list[str]


class RatchetError(RuntimeError):
    """Raised when Ruff output cannot be trusted."""


class _RuffFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filename: str
    code: str


_RuffFindings = TypeAdapter(list[_RuffFinding])


def run_ruff(
    root: Path, rules: tuple[str, ...], paths: tuple[str, ...]
) -> dict[tuple[str, str], int]:
    """Return finding counts keyed by ``(relative path, rule)``."""
    command = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        ",".join(rules),
        "--output-format",
        "json",
        "--exit-zero",
        "--exclude",
        EXCLUDE_GLOB,
        *paths,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise RatchetError(f"ruff could not be executed: {exc}") from exc
    if completed.returncode != 0:
        raise RatchetError(f"ruff exited with {completed.returncode}: {completed.stderr.strip()}")
    try:
        findings = _RuffFindings.validate_json(completed.stdout)
    except ValueError as exc:
        raise RatchetError(f"ruff produced unexpected JSON: {exc}") from exc
    counts: dict[tuple[str, str], int] = {}
    for finding in findings:
        relative = Path(finding.filename).resolve().relative_to(root).as_posix()
        key = (relative, finding.code)
        counts[key] = counts.get(key, 0) + 1
    return counts


def load_baseline(path: Path) -> RatchetBaseline:
    return RatchetBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def build_baseline(root: Path) -> RatchetBaseline:
    counts = run_ruff(root, RATCHET_RULES, SCAN_PATHS)
    entries = [
        RatchetEntry(path=path, rule=rule, count=count)
        for (path, rule), count in sorted(counts.items())
    ]
    return RatchetBaseline(rules=list(RATCHET_RULES), scan_paths=list(SCAN_PATHS), entries=entries)


def build_report(root: Path, baseline_path: Path) -> RatchetReport:
    baseline = load_baseline(baseline_path)
    if tuple(baseline.rules) != RATCHET_RULES or tuple(baseline.scan_paths) != SCAN_PATHS:
        raise RatchetError("baseline rules or scan paths differ from this script; rerun --write")
    recorded = {(entry.path, entry.rule): entry.count for entry in baseline.entries}
    if len(recorded) != len(baseline.entries):
        raise RatchetError("baseline contains duplicate (path, rule) entries")
    current = run_ruff(root, RATCHET_RULES, SCAN_PATHS)
    regressions = sorted(
        f"{path}: {rule} {recorded.get((path, rule), 0)} -> {count}"
        for (path, rule), count in current.items()
        if count > recorded.get((path, rule), 0)
    )
    improvements = sorted(
        f"{path}: {rule} {count} -> {current.get((path, rule), 0)}"
        for (path, rule), count in recorded.items()
        if current.get((path, rule), 0) < count
    )
    return RatchetReport(
        status="fail" if regressions or improvements else "pass",
        baseline=baseline_path.relative_to(root).as_posix()
        if baseline_path.is_relative_to(root)
        else str(baseline_path),
        baseline_total=sum(recorded.values()),
        current_total=sum(current.values()),
        regressions=regressions,
        improvements=improvements,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a count grew")
    parser.add_argument("--write", action="store_true", help="record the current counts")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    baseline_path = args.baseline.resolve()
    try:
        if args.write:
            baseline = build_baseline(root)
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(
                json.dumps(baseline.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
            )
            print(f"wrote {baseline_path} ({len(baseline.entries)} entries)")
            return 0
        report = build_report(root, baseline_path)
    except (OSError, ValueError, RatchetError) as exc:
        print(f"ERROR: ruff ratchet is unavailable: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    if args.check and report.status != "pass":
        if report.regressions:
            print("ERROR: ruff complexity findings increased", file=sys.stderr)
        else:
            print(
                "ERROR: ruff complexity findings decreased; run --write to lower the baseline",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
