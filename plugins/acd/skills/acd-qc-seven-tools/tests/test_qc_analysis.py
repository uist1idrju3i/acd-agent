"""Q7 aggregation tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import pytest

from qc_analysis import pareto, stratify

FINDINGS = [
    {"category": "clearance", "stage": "drc", "refdes": "U1"},
    {"category": "clearance", "stage": "drc", "refdes": "U2"},
    {"category": "silk_overlap", "stage": "drc", "refdes": "R1"},
    {"category": "unconnected", "stage": "erc", "refdes": "J1"},
    {"category": "clearance", "stage": "dfm", "refdes": "U1"},
]


def test_pareto_ranks_by_count_then_name() -> None:
    rows = pareto(FINDINGS)
    assert [(row.category, row.count) for row in rows] == [
        ("clearance", 3),
        ("silk_overlap", 1),
        ("unconnected", 1),
    ]
    assert rows[0].ratio == pytest.approx(0.6)
    assert rows[-1].cumulative_ratio == pytest.approx(1.0)


def test_pareto_of_no_findings_is_empty() -> None:
    assert pareto([]) == []


def test_stratify_groups_and_counts_categories() -> None:
    strata = stratify(FINDINGS, by="stage")
    assert [(stratum.key, stratum.count) for stratum in strata] == [
        ("dfm", 1),
        ("drc", 3),
        ("erc", 1),
    ]
    assert strata[1].categories == {"clearance": 2, "silk_overlap": 1}


def test_missing_field_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing the field 'stage'"):
        stratify([{"category": "clearance"}], by="stage")
