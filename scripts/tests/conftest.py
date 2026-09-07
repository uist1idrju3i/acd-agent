"""Configure imports for script tests."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.tests.cli_runner import CliResult, CliRunner, run_main

REPO_ROOT = Path(__file__).parents[2]


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Invoke a script's `main(argv)` in-process; see `scripts/tests/cli_runner.py`."""

    def run(main: Callable[[list[str]], int], *args: str, **kwargs: Any) -> CliResult:
        return run_main(capsys, main, *args, **kwargs)

    return run


def load_fixture(kind: str, name: str) -> dict[str, Any]:
    """Load a contract fixture for tests collected with script tests."""
    value = cast(
        dict[str, Any],
        json.loads((REPO_ROOT / "fixtures/contracts" / kind / name).read_text()),
    )
    assert isinstance(value, dict)
    return value


def fixture_obj(value: Any) -> dict[str, Any]:
    """Assert and return a fixture object."""
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)
