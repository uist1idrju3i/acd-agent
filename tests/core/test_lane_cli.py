"""Tests for the unified lane command-line surface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from acd.core.lane_cli import add_lane_io_arguments

REPO_ROOT = Path(__file__).resolve().parents[2]
LANE_ENTRYPOINTS = (
    ("scripts/resolve_gd1_silkscreen.py",),
    ("scripts/run_gd1_pipeline.py",),
    ("scripts/run_gd1_enclosure_pipeline.py",),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(exit_on_error=False)
    add_lane_io_arguments(parser, out_default=Path("out/lane"))
    return parser


def test_canonical_arguments_are_fixture_and_out() -> None:
    args = _parser().parse_args(["--fixture", "fixtures/x", "--out", "out/y"])
    assert args.fixture == Path("fixtures/x")
    assert args.out == Path("out/y")


@pytest.mark.parametrize(
    ("flag", "replacement"),
    [
        ("--graph", "--fixture"),
        ("--graph-dir", "--fixture"),
        ("--fixture-dir", "--fixture"),
        ("--out-dir", "--out"),
        ("--output", "--out"),
    ],
)
def test_legacy_flags_report_the_canonical_replacement(
    flag: str, replacement: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([flag, "value"])
    message = capsys.readouterr().err
    assert flag in message
    assert f"use {replacement} instead" in message


@pytest.mark.parametrize("entrypoint", LANE_ENTRYPOINTS)
def test_lane_entrypoints_accept_fixture_and_out(entrypoint: tuple[str]) -> None:
    result = subprocess.run(
        [sys.executable, *entrypoint, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--fixture" in result.stdout
    assert "--out " in result.stdout or "--out\n" in result.stdout


@pytest.mark.parametrize("entrypoint", LANE_ENTRYPOINTS)
def test_lane_entrypoints_reject_graph_with_guidance(entrypoint: tuple[str]) -> None:
    result = subprocess.run(
        [sys.executable, *entrypoint, "--graph", "fixtures/golden-design-1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "use --fixture instead" in result.stderr
