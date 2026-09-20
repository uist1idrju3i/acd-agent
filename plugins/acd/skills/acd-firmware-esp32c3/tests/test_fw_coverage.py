from __future__ import annotations

import pytest

from acd.schema import CoverageFloor
from fw_coverage import evaluate_coverage, parse_gcovr_json


def _gcovr() -> str:
    return (
        '{"files": ['
        '{"file":"z.c","line_total":4,"line_covered":4,'
        '"branch_total":2,"branch_covered":1},'
        '{"file":"a.c","line_total":2,"line_covered":1,'
        '"branch_total":0,"branch_covered":0}'
        "]}"
    )


def test_gcovr_parser_sorts_files_and_evaluates_floor() -> None:
    report = parse_gcovr_json(_gcovr())
    assert [item.path for item in report.files] == ["a.c", "z.c"]
    result = evaluate_coverage(
        report,
        CoverageFloor(line_pct_min=90, branch_pct_min=80),
    )
    assert result.status == "fail"
    assert result.authority == "observation"


def test_gcovr_malformed_and_missing_are_fail_closed() -> None:
    with pytest.raises(ValueError):
        parse_gcovr_json("{")
    result = evaluate_coverage(None, CoverageFloor(line_pct_min=80))
    assert result.status == "unknown"
