"""SES import and router availability tests (fail-closed negative cases)."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.adapters.freerouting.router import (
    FreeroutingRunner,
    RouterUnavailableError,
    _convergence_from_log,  # pyright: ignore[reportPrivateUsage]
    router_pass_progression,
)
from acd.adapters.freerouting.ses import SesImportError, parse_ses
from acd.core.process import sha256_bytes

_SES = """
(session "gd1.ses"
  (routes
    (resolution um 10)
    (network_out
      (net GND
        (wire (path F.Cu 1500 10000 -20000 30000 -20000))
        (via "Via[0-1]_600:300_um" 15000 -25000)
      )
    )
  )
)
"""


def _fake_router(tmp_path: Path) -> tuple[FreeroutingRunner, Path, Path]:
    executable = tmp_path / "freerouting"
    executable.write_text(
        """#!/bin/sh
if [ -n "$FREEROUTING_ARGS_FILE" ]; then
  printf '%s\\n' "$@" > "$FREEROUTING_ARGS_FILE"
fi
if [ "$1" = "--version" ]; then
  printf 'Freerouting v2.3.0\\n'
  exit 0
fi
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-do" ]; then
    shift
    printf '(session "x" (routes (resolution um 10) (network_out)))\\n' > "$1"
    printf '(0 unrouted and 0 violations)\\n'
    exit 0
  fi
  shift
done
exit 2
"""
    )
    executable.chmod(0o755)
    dsn_path = tmp_path / "input.dsn"
    dsn_path.write_text("(pcb x)")
    ses_path = tmp_path / "output.ses"
    return FreeroutingRunner(executable=str(executable)), dsn_path, ses_path


def test_parse_ses_converts_um_to_mm_y_flip() -> None:
    routed = parse_ses(_SES)
    assert len(routed.wires) == 1
    wire = routed.wires[0]
    assert wire.net == "GND"
    assert wire.layer == "F.Cu"
    assert wire.width_mm == pytest.approx(0.15)
    assert wire.points == ((1.0, 2.0), (3.0, 2.0))
    assert routed.vias[0].x_mm == pytest.approx(1.5)
    assert routed.vias[0].y_mm == pytest.approx(2.5)


def test_parse_ses_normalizes_narrow_neck_downs() -> None:
    routed = parse_ses(_SES.replace("1500", "1124"), minimum_width_mm=0.15)
    assert routed.wires[0].width_mm == pytest.approx(0.15)


def test_parse_ses_rejects_non_session() -> None:
    with pytest.raises(SesImportError):
        parse_ses("(pcb foo)")


def test_parse_ses_rejects_missing_resolution() -> None:
    with pytest.raises(SesImportError, match="resolution"):
        parse_ses('(session "x" (routes (network_out (net A (wire (path F.Cu 1 0 0 1 1))))))')


def test_parse_ses_rejects_unsupported_unit() -> None:
    with pytest.raises(SesImportError, match="resolution unit"):
        parse_ses(
            '(session "x" (routes (resolution mil 10)'
            " (network_out (net A (wire (path F.Cu 1 0 0 1 1))))))"
        )


def test_parse_ses_rejects_empty_routes() -> None:
    with pytest.raises(SesImportError, match="no routed wires"):
        parse_ses('(session "x" (routes (resolution um 10) (network_out)))')


def test_parse_ses_rejects_odd_coordinates() -> None:
    with pytest.raises(SesImportError, match="malformed wire path"):
        parse_ses(
            '(session "x" (routes (resolution um 10)'
            " (network_out (net A (wire (path F.Cu 1 0 0 1))))))"
        )


def test_router_absent_fails_closed(tmp_path: object) -> None:
    runner = FreeroutingRunner(executable="definitely-not-a-router")
    with pytest.raises(RouterUnavailableError):
        runner.version()


def test_router_declares_thread_count_in_command_and_conditions(tmp_path: Path) -> None:
    runner, dsn_path, ses_path = _fake_router(tmp_path)

    with pytest.raises(ValueError, match="must be positive"):
        runner.route(dsn_path, ses_path, "r1", freerouting_threads=-1)

    run = runner.route(
        dsn_path,
        ses_path,
        "r1",
        max_passes=10,
        freerouting_threads=2,
    )

    command = [
        str(tmp_path / "freerouting"),
        "-de",
        str(dsn_path),
        "-do",
        str(ses_path),
        "-mp",
        "10",
        "-mt",
        "2",
    ]
    assert run.envelope.config_hash == sha256_bytes("\x00".join(command).encode())
    assert (
        run.envelope.measurement_conditions
        == "headless; max 10 passes; max 2 router threads; max heap 2g"
    )


def test_router_inherits_default_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, dsn_path, ses_path = _fake_router(tmp_path)
    args_path = tmp_path / "router-args"
    monkeypatch.setenv("FREEROUTING_ARGS_FILE", str(args_path))

    run = runner.route(dsn_path, ses_path, "r1", max_passes=10)

    assert "-mt" not in args_path.read_text().splitlines()
    assert (
        "implicit router threads (cpu_count-1)"
        in run.envelope.measurement_conditions
    )


def test_convergence_parsing() -> None:
    assert _convergence_from_log("... (0 unrouted and 4 violations)") == "converged"
    assert _convergence_from_log("... (3 unrouted and 0 violations)") == "not_converged"
    assert _convergence_from_log("no completion banner") == "unknown"
    assert (
        _convergence_from_log("(2 unrouted and 0 violations)\n(0 unrouted and 0 violations)")
        == "converged"
    )
    assert router_pass_progression(
        "(8 unrouted and 0 violations)\n(2 unrouted and 0 violations)\n"
        "(0 unrouted and 0 violations)"
    ) == (8, 2, 0)
