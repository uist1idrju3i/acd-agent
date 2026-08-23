"""Run the independent Golden Design #1 lanes after silkscreen resolution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from acd.core import command_runner

CommandSpec = command_runner.CommandSpec
run_stage = command_runner.run_stage
subprocess = command_runner.subprocess

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
    return run_stage(LANE_COMMANDS, jobs=args.jobs)


if __name__ == "__main__":
    sys.exit(main())
