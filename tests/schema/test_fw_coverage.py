from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import CoverageFile, CoverageFloor, CoverageReport


def test_coverage_report_rejects_inconsistent_totals() -> None:
    with pytest.raises(ValidationError):
        CoverageReport(
            files=[
                CoverageFile(
                    path="b.c",
                    lines_total=2,
                    lines_covered=1,
                    branches_total=0,
                    branches_covered=0,
                )
            ],
            line_pct=100,
            branch_pct=100,
        )


def test_coverage_floor_is_strict() -> None:
    with pytest.raises(ValidationError):
        CoverageFloor.model_validate(
            {"line_pct_min": 50, "unexpected": True}
        )
