"""Run ordered commands with optional barrier-separated concurrency."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acd.core.runtime_records import TimingRecorder

Command = tuple[str, ...]


@dataclass(frozen=True)
class CommandSpec:
    """Describe a command and its ordering constraint."""

    command: Command
    barrier: bool = False


@dataclass(frozen=True)
class CommandResult:
    """Capture one command's result for deterministic stage output."""

    returncode: int
    stdout: str
    stderr: str


def _normalize_commands(
    commands: Sequence[CommandSpec | Command],
) -> tuple[CommandSpec, ...]:
    """Accept command tuples while retaining stage metadata."""
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
                encoding="utf-8",
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


def run_stage(
    commands: Sequence[CommandSpec | Command],
    jobs: int = 1,
    *,
    timing: TimingRecorder | None = None,
    results: list[tuple[CommandSpec, CommandResult]] | None = None,
) -> int:
    """Run commands sequentially or concurrently with deterministic output."""
    if jobs < 1:
        raise ValueError("jobs must be a positive integer")
    specs = _normalize_commands(commands)
    total = len(specs)
    if jobs == 1:
        for index, spec in enumerate(specs, start=1):
            _emit_start(index, total, spec, buffered=False)
            stage_name = f"command-{index}:{shlex.join(spec.command)}"
            if timing is not None:
                timing.start(stage_name)
            result = _run_command(spec, capture_output=False)
            if timing is not None:
                timing.finish(stage_name)
            if results is not None:
                results.append((spec, result))
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
                batch_name = f"batch-{next_index + 1}:barrier"
                if timing is not None:
                    timing.start(batch_name)
                result = _run_command(spec, capture_output=True)
                if timing is not None:
                    timing.finish(batch_name)
                if results is not None:
                    results.append((spec, result))
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
                if timing is not None:
                    timing.start(f"command-{offset + 1}:{shlex.join(spec.command)}")
            batch_name = f"batch-{batch_start + 1}-{next_index}"
            if timing is not None:
                timing.start(batch_name)
            futures = [
                executor.submit(_run_command, spec, capture_output=True)
                for spec in specs[batch_start:next_index]
            ]
            batch_results = [future.result() for future in futures]
            if timing is not None:
                timing.finish(batch_name)
            first_failure: int | None = None
            for offset, (spec, result) in enumerate(
                zip(specs[batch_start:next_index], batch_results, strict=True),
                start=batch_start,
            ):
                if timing is not None:
                    timing.finish(f"command-{offset + 1}:{shlex.join(spec.command)}")
                if results is not None:
                    results.append((spec, result))
                _emit_result(offset + 1, total, spec, result)
                if result.returncode != 0 and first_failure is None:
                    first_failure = result.returncode or 1
            if first_failure is not None:
                return first_failure

    return 0
