"""SES import and router availability tests (fail-closed negative cases)."""

from __future__ import annotations

import pytest

from acd_adapter_freerouting.router import (
    FreeroutingRunner,
    RouterUnavailableError,
    _convergence_from_log,  # pyright: ignore[reportPrivateUsage]
)
from acd_adapter_freerouting.ses import SesImportError, parse_ses

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


def test_convergence_parsing() -> None:
    assert _convergence_from_log("... (0 unrouted and 4 violations)") == "converged"
    assert _convergence_from_log("... (3 unrouted and 0 violations)") == "not_converged"
    assert _convergence_from_log("no completion banner") == "unknown"
    assert (
        _convergence_from_log("(2 unrouted and 0 violations)\n(0 unrouted and 0 violations)")
        == "converged"
    )
