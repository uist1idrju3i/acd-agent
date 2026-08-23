"""Run the repository's canonical verification stages."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

Command = tuple[str, ...]

@dataclass(frozen=True)
class CommandSpec:
    """Describe a verification command and its ordering constraint."""

    command: Command
    barrier: bool = False


@dataclass(frozen=True)
class CommandResult:
    """Capture one command's result for deterministic stage output."""

    returncode: int
    stdout: str
    stderr: str


SYNC_COMMAND = CommandSpec(("uv", "sync"), barrier=True)
STANDARD_COMMANDS: tuple[CommandSpec, ...] = (
    SYNC_COMMAND,
    CommandSpec(("uv", "run", "ruff", "check")),
    CommandSpec(("uv", "run", "pyright")),
    CommandSpec(("uv", "run", "pytest")),
    CommandSpec(("uv", "run", "python", "scripts/verify_docs.py")),
    CommandSpec(("uv", "run", "python", "scripts/verify_skill_metadata.py")),
    CommandSpec(("uv", "run", "python", "scripts/verify_skill_package_ref.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_sdk_capabilities.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_agent_prompts.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_acd_tool_registration.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_model_policy.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_agent_settings.py", "--check")),
    CommandSpec(("uv", "run", "python", "scripts/verify_context_view.py", "--check")),
    CommandSpec(("git", "diff", "--check")),
)

STAGES: dict[str, tuple[CommandSpec, ...]] = {
    "docs": (
        CommandSpec(("uv", "run", "python", "scripts/verify_docs.py")),
        CommandSpec(("uv", "run", "python", "scripts/verify_sdk_capabilities.py", "--check")),
        CommandSpec(("git", "diff", "--check")),
    ),
    "standard": STANDARD_COMMANDS,
    "full": (
        *STANDARD_COMMANDS,
        CommandSpec(("uv", "run", "pytest", "plugins", "-q"), barrier=True),
        CommandSpec(
            ("uv", "run", "python", "scripts/resolve_gd1_silkscreen.py"),
            barrier=True,
        ),
        CommandSpec(
            ("uv", "run", "python", "scripts/run_gd1_pipeline.py"),
            barrier=True,
        ),
        CommandSpec(
            (
                "uv",
                "run",
                "python",
                "scripts/run_gd1_enclosure_pipeline.py",
                "--out",
                "out/gd1-enclosure",
            ),
            barrier=True,
        ),
        CommandSpec(
            ("uv", "run", "python", "scripts/probe_tools.py"),
            barrier=True,
        ),
    ),
}


def _parser() -> argparse.ArgumentParser:
    """Build the verification command-line parser."""
    parser = argparse.ArgumentParser(
        description="Run the canonical ACD verification stages."
    )
    parser.add_argument(
        "--stage",
        choices=tuple(STAGES),
        default="standard",
        help="verification stage to run (default: standard)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the stage command definitions as JSON and exit",
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=min(os.cpu_count() or 1, 4),
        help=(
            "maximum parallel commands (default: min(cpu_count, 4)); "
            "1 stops at the first failure, while higher values run all started "
            "commands and report every failure"
        ),
    )
    return parser


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("jobs must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    return parsed


def _list_stages() -> None:
    """Print the stage definitions in machine-readable form."""
    listed = {
        stage: [
            {
                "command": list(spec.command),
                "barrier": spec.barrier,
            }
            for spec in commands
        ]
        for stage, commands in STAGES.items()
    }
    print(json.dumps(listed, ensure_ascii=False, indent=2))


def _normalize_commands(commands: Sequence[CommandSpec | Command]) -> tuple[CommandSpec, ...]:
    """Accept command tuples for callers while retaining stage metadata."""
    return tuple(
        command if isinstance(command, CommandSpec) else CommandSpec(tuple(command))
        for command in commands
    )


def _run_command(spec: CommandSpec, *, capture_output: bool) -> CommandResult:
    """Run one command with optional output buffering."""
    try:
        if capture_output:
            completed = subprocess.run(
                spec.command,
                check=False,
                capture_output=True,
                text=True,
            )
            return CommandResult(
                completed.returncode,
                completed.stdout or "",
                completed.stderr or "",
            )
        completed = subprocess.run(spec.command, check=False)
    except OSError as error:
        return CommandResult(1, "", f"{type(error).__name__}: {error}\n")
    return CommandResult(completed.returncode, "", "")


def _emit_start(index: int, total: int, spec: CommandSpec, *, buffered: bool) -> None:
    """Emit a command start line."""
    prefix = "START " if buffered else ""
    print(f"[{index}/{total}] {prefix}$ {shlex.join(spec.command)}", flush=True)


def _emit_result(index: int, total: int, spec: CommandSpec, result: CommandResult) -> None:
    """Emit a buffered command result in stage declaration order."""
    print(f"[{index}/{total}] $ {shlex.join(spec.command)}")
    output = result.stdout + result.stderr
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    status = "PASS" if result.returncode == 0 else f"FAIL (exit={result.returncode})"
    print(f"[{index}/{total}] {status}", flush=True)


def _emit_direct_result(index: int, total: int, result: CommandResult) -> None:
    """Emit a command status after direct subprocess output."""
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    status = "PASS" if result.returncode == 0 else f"FAIL (exit={result.returncode})"
    print(f"[{index}/{total}] {status}", flush=True)


def run_stage(commands: Sequence[CommandSpec | Command], jobs: int = 1) -> int:
    """Run a stage sequentially or concurrently with deterministic output."""
    if jobs < 1:
        raise ValueError("jobs must be a positive integer")
    specs = _normalize_commands(commands)
    total = len(specs)
    if jobs == 1:
        for index, spec in enumerate(specs, start=1):
            _emit_start(index, total, spec, buffered=False)
            result = _run_command(spec, capture_output=False)
            _emit_direct_result(index, total, result)
            if result.returncode != 0:
                return result.returncode or 1
        return 0

    next_index = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        while next_index < total:
            if specs[next_index].barrier:
                spec = specs[next_index]
                _emit_start(next_index + 1, total, spec, buffered=True)
                result = _run_command(spec, capture_output=True)
                _emit_result(next_index + 1, total, spec, result)
                next_index += 1
                if result.returncode != 0:
                    return result.returncode or 1
                continue

            batch_start = next_index
            while next_index < total and not specs[next_index].barrier:
                next_index += 1
            for offset, spec in enumerate(
                specs[batch_start:next_index], start=batch_start
            ):
                _emit_start(offset + 1, total, spec, buffered=True)
            futures = [
                executor.submit(_run_command, spec, capture_output=True)
                for spec in specs[batch_start:next_index]
            ]
            results = [future.result() for future in futures]
            first_failure: int | None = None
            for offset, (spec, result) in enumerate(
                zip(specs[batch_start:next_index], results, strict=True), start=batch_start
            ):
                _emit_result(offset + 1, total, spec, result)
                if result.returncode != 0 and first_failure is None:
                    first_failure = result.returncode or 1
            if first_failure is not None:
                return first_failure

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected verification stage."""
    args = _parser().parse_args(argv)
    if args.list:
        _list_stages()
        return 0
    return run_stage(STAGES[args.stage], jobs=args.jobs)


if __name__ == "__main__":
    sys.exit(main())
