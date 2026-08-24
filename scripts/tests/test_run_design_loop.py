"""Tests for the design-loop command-line contract."""

from __future__ import annotations

import pytest
from scripts import run_design_loop


def test_jobs_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        run_design_loop.main(["--order-total", "order.json", "--jobs", "0"])


def test_exploration_budget_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        run_design_loop.main(
            [
                "--order-total",
                "order.json",
                "--max-exploration-candidates",
                "0",
            ]
        )


def test_requirement_inputs_are_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_design_loop(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(run_design_loop, "run_design_loop", fake_run_design_loop)
    assert (
        run_design_loop.main(
            [
                "--order-total",
                "order.json",
                "--requirement",
                "update.json",
                "--fixture-spec",
                "fixture-spec.json",
            ]
        )
        == 0
    )
    assert captured["requirement"] == run_design_loop.Path("update.json")
    assert captured["fixture_spec"] == run_design_loop.Path("fixture-spec.json")
