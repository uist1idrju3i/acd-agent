"""Tests for L3 router non-convergence diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from acd.core.router_diagnostics import (
    OPEN_NET_LIMIT,
    read_router_diagnostics,
    router_diagnostics_hint,
)


def _write_progress(
    board_output: Path, unrouted: object, convergence_state: object
) -> None:
    path = board_output / "l3" / "router-pass-progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "unrouted": unrouted,
                "convergence_state": convergence_state,
            }
        ),
        encoding="utf-8",
    )


def _write_connectivity(board_output: Path, nets: object, status: str = "fail") -> None:
    path = board_output / "gate-evidence" / "routing-connectivity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status, "observation": {"status": status, "nets": nets}}),
        encoding="utf-8",
    )


def test_missing_directory_reports_unknown(tmp_path: Path) -> None:
    diag = read_router_diagnostics(tmp_path / "missing")
    assert diag.convergence_state == "unknown"
    assert diag.unrouted_progression == ()
    assert diag.final_unrouted is None
    assert diag.plateau_passes == 0
    assert diag.open_net_count is None
    assert diag.open_nets == ()
    assert any("missing" in error for error in diag.read_errors)
    assert router_diagnostics_hint(diag) is None
    assert diag.to_dict()["authority"] == "L3 observation; not gate authority"


def test_malformed_json_is_a_read_error(tmp_path: Path) -> None:
    path = tmp_path / "l3" / "router-pass-progress.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    diag = read_router_diagnostics(tmp_path)
    assert diag.convergence_state == "unknown"
    assert any("router-pass-progress.json" in error for error in diag.read_errors)


def test_converged_progression(tmp_path: Path) -> None:
    _write_progress(tmp_path, [5, 0], "converged")
    _write_connectivity(tmp_path, [{"net": "net.gnd", "status": "pass"}], "pass")
    diag = read_router_diagnostics(tmp_path)
    assert diag.convergence_state == "converged"
    assert diag.unrouted_progression == (5, 0)
    assert diag.final_unrouted == 0
    assert diag.plateau_passes == 1
    assert diag.open_net_count == 0
    assert diag.open_nets == ()
    assert router_diagnostics_hint(diag) is None


def test_not_converged_plateau_hint(tmp_path: Path) -> None:
    _write_progress(tmp_path, [22, 21, 21, 21, 21], "not_converged")
    diag = read_router_diagnostics(tmp_path)
    assert diag.plateau_passes == 4
    assert diag.final_unrouted == 21
    hint = router_diagnostics_hint(diag)
    assert hint is not None
    assert "plateaued at 21 for 4 passes" in hint
    assert "do not relax DRC or routing rules" in hint


def test_not_converged_still_decreasing_hint(tmp_path: Path) -> None:
    _write_progress(tmp_path, [9, 7, 5], "not_converged")
    diag = read_router_diagnostics(tmp_path)
    assert diag.plateau_passes == 1
    hint = router_diagnostics_hint(diag)
    assert hint is not None
    assert "still converging" in hint
    assert "--max-passes" in hint


def test_timed_out_hint(tmp_path: Path) -> None:
    _write_progress(tmp_path, [12, 12], "timed_out")
    diag = read_router_diagnostics(tmp_path)
    hint = router_diagnostics_hint(diag)
    assert hint is not None
    assert "timed out" in hint
    assert "--router-timeout-s" in hint


def test_open_nets_capped_and_counted(tmp_path: Path) -> None:
    nets = [
        {"net": f"net.{index:02d}", "status": "fail"}
        for index in range(OPEN_NET_LIMIT + 3)
    ]
    nets.append({"net": "net.ok", "status": "pass"})
    _write_progress(tmp_path, [30, 30, 30], "not_converged")
    _write_connectivity(tmp_path, nets)
    diag = read_router_diagnostics(tmp_path)
    assert diag.open_net_count == OPEN_NET_LIMIT + 3
    assert diag.open_nets == tuple(f"net.{index:02d}" for index in range(OPEN_NET_LIMIT))
    assert list(diag.open_nets) == sorted(diag.open_nets)


def test_wrong_typed_fields_become_read_errors(tmp_path: Path) -> None:
    _write_progress(tmp_path, [4, "x", -1], "not_converged")
    _write_connectivity(tmp_path, [{"net": 7, "status": "fail"}])
    diag = read_router_diagnostics(tmp_path)
    assert diag.unrouted_progression == ()
    assert diag.final_unrouted is None
    assert diag.open_net_count is None
    assert len(diag.read_errors) >= 2
    assert any("unrouted" in error for error in diag.read_errors)
    assert any("routing-connectivity.json" in error for error in diag.read_errors)


def test_unknown_convergence_state_is_a_read_error(tmp_path: Path) -> None:
    _write_progress(tmp_path, [3], "sideways")
    diag = read_router_diagnostics(tmp_path)
    assert diag.convergence_state == "unknown"
    assert any("convergence_state" in error for error in diag.read_errors)
    assert router_diagnostics_hint(diag) is None
