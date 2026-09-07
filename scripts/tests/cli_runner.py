"""In-process runner for script CLIs under test.

Spawning `sys.executable` per assertion costs seconds for scripts that import the
OpenHands SDK. Tests keep one subprocess smoke test per CLI and route the other
cases through `run_main`, which applies `cwd`/`env` for the call only. An uncaught
exception propagates as a test error, which is stricter than asserting the absence
of "Traceback" on stderr.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest


@dataclass(frozen=True)
class CliResult:
    """Captured outcome of a CLI `main` invoked in the test process."""

    returncode: int
    stdout: str
    stderr: str

    def json(self) -> dict[str, object]:
        value = json.loads(self.stdout)
        assert isinstance(value, dict)
        return cast(dict[str, object], value)


CliRunner = Callable[..., CliResult]


def run_main(
    capsys: pytest.CaptureFixture[str],
    main: Callable[[list[str]], int],
    *args: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CliResult:
    with pytest.MonkeyPatch.context() as scoped:
        if cwd is not None:
            scoped.chdir(cwd)
        for key, value in (env or {}).items():
            scoped.setenv(key, value)
        capsys.readouterr()
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return CliResult(returncode=code, stdout=captured.out, stderr=captured.err)
