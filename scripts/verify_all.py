"""Run the repository's canonical verification stages."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Sequence

Command = tuple[str, ...]

STANDARD_COMMANDS: tuple[Command, ...] = (
    ("uv", "sync"),
    ("uv", "run", "ruff", "check"),
    ("uv", "run", "pyright"),
    ("uv", "run", "pytest"),
    ("uv", "run", "python", "scripts/verify_docs.py"),
    ("uv", "run", "python", "scripts/verify_sdk_capabilities.py", "--check"),
    ("uv", "run", "python", "scripts/verify_agent_prompts.py", "--check"),
    ("git", "diff", "--check"),
)

STAGES: dict[str, tuple[Command, ...]] = {
    "docs": (
        ("uv", "run", "python", "scripts/verify_docs.py"),
        ("uv", "run", "python", "scripts/verify_sdk_capabilities.py", "--check"),
        ("git", "diff", "--check"),
    ),
    "standard": STANDARD_COMMANDS,
    "full": (
        *STANDARD_COMMANDS,
        ("uv", "run", "pytest", "plugins", "-q"),
        ("uv", "run", "python", "scripts/resolve_gd1_silkscreen.py"),
        ("uv", "run", "python", "scripts/run_gd1_pipeline.py"),
        (
            "uv",
            "run",
            "python",
            "scripts/run_gd1_enclosure_pipeline.py",
            "--out",
            "out/gd1-enclosure",
        ),
        ("uv", "run", "python", "scripts/probe_tools.py"),
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
    return parser


def _list_stages() -> None:
    """Print the stage definitions in machine-readable form."""
    print(json.dumps(STAGES, ensure_ascii=False, indent=2))


def run_stage(commands: Sequence[Command]) -> int:
    """Run commands in order and stop at the first failure."""
    for index, command in enumerate(commands, start=1):
        print(f"[{index}/{len(commands)}] $ {shlex.join(command)}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            print(
                f"[{index}/{len(commands)}] FAIL (exit={completed.returncode})",
                flush=True,
            )
            return completed.returncode or 1
        print(f"[{index}/{len(commands)}] PASS", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected verification stage."""
    args = _parser().parse_args(argv)
    if args.list:
        _list_stages()
        return 0
    return run_stage(STAGES[args.stage])


if __name__ == "__main__":
    sys.exit(main())
