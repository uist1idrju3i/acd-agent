# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@14b1b2148c2d9c2bdf982595243e0e51764c7b5a",
# ]
# ///
"""Deterministic clang-tidy analysis for a generated ESP-IDF project."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from acd.core.process import ExternalToolError, run_tool

_DIAGNOSTIC = re.compile(
    r"^(?P<file>.*?):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<severity>warning|error):\s+(?P<message>.*?)\s+\[(?P<check>[^\]]+)\]\s*$"
)


@dataclass(frozen=True)
class StaticFinding:
    file: str
    line: int
    col: int
    severity: str
    check: str
    message: str


def load_rules(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    decoded: object = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("clang-tidy rules must be an object")
    data = cast(dict[str, object], decoded)
    checks = data.get("checks")
    exclusions = data.get("exclusions")
    version_pin = data.get("version_pin")
    if not isinstance(checks, list) or not isinstance(exclusions, list):
        raise ValueError("clang-tidy rules are malformed")
    checks = cast(list[object], checks)
    exclusions = cast(list[object], exclusions)
    checks_list: list[str] = []
    exclusions_list: list[str] = []
    for item in checks:
        if not isinstance(item, str) or not item:
            raise ValueError("clang-tidy rules are malformed")
        checks_list.append(item)
    for item in exclusions:
        if not isinstance(item, str) or not item:
            raise ValueError("clang-tidy rules are malformed")
        exclusions_list.append(item)
    if not checks_list or not isinstance(version_pin, str) or not version_pin:
        raise ValueError("clang-tidy rules are malformed")
    typed_data: dict[str, object] = {
        "checks": checks_list,
        "exclusions": exclusions_list,
        "version_pin": version_pin,
    }
    return typed_data, "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_diagnostics(text: str, project_root: Path) -> list[StaticFinding]:
    findings: list[StaticFinding] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIAGNOSTIC.match(line)
        if match is None:
            if "warning:" in line or "error:" in line:
                raise ValueError(f"malformed clang-tidy diagnostic: {raw_line!r}")
            continue
        path = Path(match.group("file"))
        try:
            relative = path.resolve().relative_to(project_root.resolve())
        except ValueError:
            relative = path
        findings.append(
            StaticFinding(
                file=relative.as_posix(),
                line=int(match.group("line")),
                col=int(match.group("col")),
                severity=match.group("severity"),
                check=match.group("check"),
                message=match.group("message"),
            )
        )
    return sorted(
        findings,
        key=lambda finding: (
            finding.file,
            finding.line,
            finding.col,
            finding.severity,
            finding.check,
            finding.message,
        ),
    )


def evaluate_findings(
    findings: list[StaticFinding], exclusions: list[str]
) -> dict[str, object]:
    active = [
        finding
        for finding in findings
        if finding.check not in exclusions
    ]
    counts = {
        "warning": sum(item.severity == "warning" for item in active),
        "error": sum(item.severity == "error" for item in active),
    }
    return {
        "status": "fail" if any(counts.values()) else "pass",
        "findings": [asdict(item) for item in active],
        "counts": counts,
    }


def discover_gcc_toolchain() -> Path | None:
    """Find the ESP-IDF RISC-V GCC prefix beneath IDF_TOOLS_PATH."""
    tools_path = os.environ.get("IDF_TOOLS_PATH")
    if not tools_path:
        return None
    root = Path(tools_path)
    candidates = sorted(root.glob("tools/riscv32-esp-elf/*/riscv32-esp-elf"))
    if candidates:
        return candidates[-1]
    candidates = sorted(root.glob("tools/riscv32-esp-elf/*"))
    return candidates[-1] if candidates else None


def run_clang_tidy(
    project_dir: Path,
    checks_path: Path,
    *,
    version_pin: str | None = None,
    target_revision: str = "unknown",
) -> dict[str, object]:
    rules, checks_sha256 = load_rules(checks_path)
    compile_commands = project_dir / "build" / "compile_commands.json"
    if not compile_commands.is_file():
        return {
            "status": "unknown",
            "authority": "estimate",
            "tool_version": "unknown",
            "checks_sha256": checks_sha256,
            "findings": [],
            "counts": {"warning": 0, "error": 0},
            "findings_detail": ["compile_commands_missing"],
        }
    pin = version_pin or str(rules["version_pin"])
    gcc_toolchain = discover_gcc_toolchain()
    if gcc_toolchain is None:
        return {
            "status": "unknown",
            "authority": "estimate",
            "tool_version": "unknown",
            "checks_sha256": checks_sha256,
            "findings": [],
            "counts": {"warning": 0, "error": 0},
            "findings_detail": ["gcc_toolchain_missing"],
        }
    workdir = project_dir / "firmware-analysis"
    workdir.mkdir(parents=True, exist_ok=True)
    version_envelope = workdir / "clang-tidy-version-envelope.json"
    try:
        version_run = run_tool(
            tool_name="clang-tidy",
            tool_version=pin,
            format_version="clang-tidy-v1",
            command=["clang-tidy", "--version"],
            input_paths=[],
            output_paths=[],
            envelope_path=version_envelope,
            target_revision=target_revision,
            measurement_conditions="generated ESP-IDF compile_commands.json",
        )
        version_text = version_run.stdout + version_run.stderr
        match = re.search(r"version\s+(\d+)", version_text, re.IGNORECASE)
        if match is None:
            raise ValueError("clang-tidy version output is malformed")
        version = match.group(1)
        if version != pin:
            return {
                "status": "unknown",
                "authority": "estimate",
                "tool_version": version,
                "checks_sha256": checks_sha256,
                "findings": [],
                "counts": {"warning": 0, "error": 0},
                "findings_detail": ["tool_version_mismatch"],
            }
        checks = ",".join(
            list(cast(list[str], rules["checks"]))
            + [f"-{item}" for item in cast(list[str], rules["exclusions"])]
        )
        execution = run_tool(
            tool_name="clang-tidy",
            tool_version=version,
            format_version="clang-tidy-v1",
            command=[
                "clang-tidy",
                "-p",
                str(compile_commands.parent),
                f"-checks={checks}",
                "--extra-arg=--target=riscv32-esp-elf",
                "--extra-arg=-gcc-toolchain",
                str(gcc_toolchain),
                str(project_dir / "main" / "acd_main.c"),
            ],
            input_paths=[compile_commands],
            output_paths=[],
            envelope_path=workdir / "clang-tidy-envelope.json",
            target_revision=target_revision,
            measurement_conditions="generated ESP-IDF compile_commands.json",
            cwd=project_dir,
        )
        findings = parse_diagnostics(
            execution.stdout + execution.stderr,
            project_dir,
        )
        result = evaluate_findings(findings, cast(list[str], rules["exclusions"]))
        return {
            "authority": "estimate",
            "tool_version": version,
            "checks_sha256": checks_sha256,
            **result,
            "findings_detail": [],
        }
    except (ExternalToolError, OSError, UnicodeError, ValueError) as exc:
        return {
            "status": "unknown",
            "authority": "estimate",
            "tool_version": "unknown",
            "checks_sha256": checks_sha256,
            "findings": [],
            "counts": {"warning": 0, "error": 0},
            "findings_detail": [f"tool_unavailable_or_parse_failure: {exc}"],
        }


__all__ = [
    "StaticFinding",
    "discover_gcc_toolchain",
    "evaluate_findings",
    "load_rules",
    "parse_diagnostics",
    "run_clang_tidy",
]
