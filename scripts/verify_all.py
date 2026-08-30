"""Run the repository's canonical verification stages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from acd.core.command_runner import CommandSpec, run_stage

SYNC_COMMAND = CommandSpec(("uv", "sync"), barrier=True)
FAST_COMMANDS: tuple[CommandSpec, ...] = (
    SYNC_COMMAND,
    CommandSpec(("uv", "run", "ruff", "check")),
    CommandSpec(("uv", "run", "pyright")),
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
STANDARD_COMMANDS = (*FAST_COMMANDS, CommandSpec(("uv", "run", "pytest")))

STAGES: dict[str, tuple[CommandSpec, ...]] = {
    "docs": (
        CommandSpec(("uv", "run", "python", "scripts/verify_docs.py")),
        CommandSpec(("uv", "run", "python", "scripts/verify_sdk_capabilities.py", "--check")),
        CommandSpec(("git", "diff", "--check")),
    ),
    "fast": FAST_COMMANDS,
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
                "scripts/run_enclosure_pipeline.py",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected verification stage."""
    args = _parser().parse_args(argv)
    if args.list:
        _list_stages()
        return 0
    return run_stage(STAGES[args.stage], jobs=args.jobs)


if __name__ == "__main__":
    sys.exit(main())
