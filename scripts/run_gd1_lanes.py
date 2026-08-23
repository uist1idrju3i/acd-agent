"""Run the independent Golden Design #1 lanes after silkscreen resolution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.command_runner import CommandResult, CommandSpec, run_stage
from acd.core.runtime_records import TimingRecorder, write_timing_record

LANE_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        ("uv", "run", "python", "scripts/resolve_gd1_silkscreen.py"),
        barrier=True,
    ),
    CommandSpec(
        ("uv", "run", "python", "scripts/run_gd1_pipeline.py", "--out", "out/gd1")
    ),
    CommandSpec(
        (
            "uv",
            "run",
            "python",
            "scripts/run_gd1_enclosure_pipeline.py",
            "--out",
            "out/gd1-enclosure",
        )
    ),
    CommandSpec(
        (
            "uv",
            "run",
            "--script",
            "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py",
            "--out",
            "out/gd1-fw",
        )
    ),
    CommandSpec(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/core/test_design_predicates.py::test_gd1_predicates_pass_on_fixture",
            "tests/core/test_design_predicates.py::test_power_decoupling_distant_capacitor_fails",
            "tests/pipeline/test_gd1_silkscreen_pinning.py::test_final_silkscreen_coordinates_are_pinned",
            "tests/pipeline/test_gd1_negative_fixtures.py",
        )
    ),
)


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("jobs must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    """Build the lane runner command-line parser."""
    parser = argparse.ArgumentParser(
        description="Run the GD1 silkscreen resolver and independent design lanes."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the lane command definitions as JSON and exit",
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
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("out"),
        help="root directory for lane outputs and L3 runtime records",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="opt-in content-addressed cache directory for deterministic artifacts",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse only valid matching artifact-cache entries; never restore verdicts",
    )
    return parser


def _list_lanes() -> None:
    """Print the lane definitions in machine-readable form."""
    print(
        json.dumps(
            [
                {
                    "command": list(spec.command),
                    "barrier": spec.barrier,
                }
                for spec in LANE_COMMANDS
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the GD1 lanes."""
    args = _parser().parse_args(argv)
    if args.list:
        _list_lanes()
        return 0
    out_root = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    cache_dir = args.cache_dir
    if args.resume and cache_dir is None:
        cache_dir = out_root / ".stage-cache"

    rewrite_outputs = out_root != Path("out")
    commands: list[CommandSpec] = []
    for index, spec in enumerate(LANE_COMMANDS):
        command = list(spec.command)
        if rewrite_outputs:
            while "--out" in command:
                out_index = command.index("--out")
                del command[out_index : out_index + 2]
            if index == 0:
                command.extend(["--out", str(out_root / "gd1-silkscreen-resolve")])
            elif index == 1:
                command.extend(["--out", str(out_root / "gd1")])
            elif index == 2:
                command.extend(["--out", str(out_root / "gd1-enclosure")])
            elif index == 3:
                command.extend(["--out", str(out_root / "gd1-fw")])
        if index == 1 and cache_dir is not None:
            command.extend(["--cache-dir", str(cache_dir)])
        commands.append(CommandSpec(tuple(command), barrier=spec.barrier))

    timing = TimingRecorder()
    command_results: list[tuple[CommandSpec, CommandResult]] = []
    returncode = 1
    runtime_error: str | None = None
    try:
        returncode = run_stage(
            commands,
            jobs=args.jobs,
            timing=timing,
            results=command_results,
        )
    except Exception as exc:
        runtime_error = f"{type(exc).__name__}: {exc}"
    finally:
        timing_path = write_timing_record(out_root, timing)
        failures = [
            {
                "command": list(spec.command),
                "returncode": result.returncode,
                "stderr": result.stderr,
            }
            for spec, result in command_results
            if result.returncode != 0
        ]
        if runtime_error is not None:
            failures.append(
                {
                    "command": [],
                    "returncode": returncode,
                    "stderr": runtime_error,
                }
            )
        summary = {
            "ok": not failures and returncode == 0,
            "resume": args.resume,
            "cache_dir": str(cache_dir) if cache_dir is not None else None,
            "timing_record": str(timing_path),
            "failures": failures,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return returncode


if __name__ == "__main__":
    sys.exit(main())
