"""Shared lane command-line surface for the deterministic design lanes.

Every lane entry point takes the design input directory as ``--fixture`` and the
lane output directory as ``--out``. Historic spellings are still declared so
that they fail with explicit guidance instead of a bare argparse error.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

FIXTURE_HELP: Final = "design input directory containing graph.json"
OUT_HELP: Final = "lane output directory"

LEGACY_FIXTURE_FLAGS: Final[tuple[str, ...]] = (
    "--graph",
    "--graph-dir",
    "--fixture-dir",
)
LEGACY_OUT_FLAGS: Final[tuple[str, ...]] = ("--out-dir", "--output")


class _LegacyFlagAction(argparse.Action):
    """Reject a historic flag with the canonical replacement."""

    def __init__(self, option_strings: list[str], dest: str, **kwargs: object) -> None:
        replacement = kwargs.pop("replacement")
        if not isinstance(replacement, str):
            raise TypeError("replacement must be a string")
        self.replacement = replacement
        super().__init__(option_strings, dest, nargs=None, default=None)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values
        parser.error(
            f"{option_string} is not accepted; use {self.replacement} instead "
            f"(every lane entry point takes --fixture and --out)"
        )


def add_legacy_flags(
    parser: argparse.ArgumentParser,
    flags: Sequence[str],
    replacement: str,
) -> None:
    """Declare historic flags that report the canonical replacement."""
    for flag in flags:
        parser.add_argument(
            flag,
            action=_LegacyFlagAction,
            replacement=replacement,
            help=argparse.SUPPRESS,
        )


def add_lane_io_arguments(
    parser: argparse.ArgumentParser,
    *,
    fixture_default: Path | None = Path("fixtures/golden-design-1"),
    out_default: Path | None,
) -> None:
    """Add the canonical ``--fixture`` and ``--out`` lane arguments."""
    parser.add_argument(
        "--fixture",
        type=Path,
        default=fixture_default,
        required=fixture_default is None,
        help=FIXTURE_HELP,
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=out_default,
        required=out_default is None,
        help=OUT_HELP,
    )
    add_legacy_flags(parser, LEGACY_FIXTURE_FLAGS, "--fixture")
    add_legacy_flags(parser, LEGACY_OUT_FLAGS, "--out")


__all__ = [
    "FIXTURE_HELP",
    "LEGACY_FIXTURE_FLAGS",
    "LEGACY_OUT_FLAGS",
    "OUT_HELP",
    "add_lane_io_arguments",
    "add_legacy_flags",
]
