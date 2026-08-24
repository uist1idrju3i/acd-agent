"""Tests for the design-loop command-line contract."""

from __future__ import annotations

import pytest
from scripts import run_design_loop


def test_jobs_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        run_design_loop.main(["--order-total", "order.json", "--jobs", "0"])
