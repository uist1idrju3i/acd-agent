"""Tests for the deterministic idea rough estimate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from acd.core.knowledge.idea_dialogue import load_idea_record
from acd.core.knowledge.idea_estimate import estimate_idea, load_estimate_catalog
from acd.schema.idea import IdeaField, IdeaSource
from acd.schema.idea_estimate import (
    IdeaEstimateCatalog,
)

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPOSITORY / "fixtures" / "idea" / "sample-usb-thermometer"

USER = IdeaSource(kind="user_statement", ref="conversation:evt-0009")
CONFIRMED_AT = datetime(2026, 9, 13, tzinfo=UTC)


def _catalog() -> IdeaEstimateCatalog:
    return load_estimate_catalog(FIXTURE_DIR / "estimate-catalog.json")


def test_lines_unknown_and_totals() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    estimate = estimate_idea(record, _catalog())
    assert [line.function_id for line in estimate.lines] == [
        "fn-measure-temp",
        "fn-stream-usb",
    ]
    assert estimate.unknown_functions == []
    assert estimate.totals.covers_all_functions is True
    assert estimate.totals.cost_jpy.min == 1000.0
    assert estimate.totals.cost_jpy.max == 2400.0

    no_class = record.model_copy(
        update={
            "functions": [
                record.functions[0].model_copy(update={"function_class": None})
            ]
        }
    )
    estimate = estimate_idea(no_class, _catalog())
    assert [item.function_id for item in estimate.unknown_functions] == [
        "fn-measure-temp"
    ]
    assert estimate.unknown_functions[0].reason == "function_class undeclared"
    assert estimate.totals.covers_all_functions is False

    bad_class = record.model_copy(
        update={
            "functions": [
                record.functions[0].model_copy(
                    update={"function_class": "unknown_class"}
                )
            ]
        }
    )
    estimate = estimate_idea(bad_class, _catalog())
    assert "not in catalog" in estimate.unknown_functions[0].reason


def _confirmed(value: float, unit: str) -> IdeaField:
    return IdeaField(
        status="confirmed",
        value=value,
        unit=unit,
        sources=[USER],
        confirmed_at=CONFIRMED_AT,
    )


def test_findings_stop_within_and_not_comparable() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    # Open constraints -> not_comparable
    estimate = estimate_idea(record, _catalog())
    assert {f.constraint: f.status for f in estimate.findings} == {
        "cost": "not_comparable",
        "power": "not_comparable",
        "dimensions": "not_comparable",
    }
    assert "open" in estimate.findings[0].detail

    # Confirmed within limits -> within
    within = record.model_copy(
        update={
            "constraints": record.constraints.model_copy(
                update={
                    "cost": _confirmed(5000.0, "JPY"),
                    "power": _confirmed(1000.0, "mW"),
                    "dimensions": _confirmed(3000.0, "mm2"),
                }
            )
        }
    )
    estimate = estimate_idea(within, _catalog())
    assert all(f.status == "within" for f in estimate.findings)

    # Confirmed below the upper bound -> stop
    below = record.model_copy(
        update={
            "constraints": record.constraints.model_copy(
                update={"cost": _confirmed(100.0, "JPY")}
            )
        }
    )
    estimate = estimate_idea(below, _catalog())
    cost = next(f for f in estimate.findings if f.constraint == "cost")
    assert cost.status == "stop"
    assert "exceeds" in cost.detail

    # Confirmed inside the estimated range -> risk
    risk = record.model_copy(
        update={
            "constraints": record.constraints.model_copy(
                update={"cost": _confirmed(1500.0, "JPY")}
            )
        }
    )
    estimate = estimate_idea(risk, _catalog())
    cost = next(f for f in estimate.findings if f.constraint == "cost")
    assert cost.status == "risk"
    assert "straddles" in cost.detail

    # Non-numeric and wrong-unit constraints -> not_comparable
    odd = record.model_copy(
        update={
            "constraints": record.constraints.model_copy(
                update={
                    "cost": IdeaField(
                        status="confirmed",
                        value="cheap",
                        sources=[USER],
                        confirmed_at=CONFIRMED_AT,
                    ),
                    "power": _confirmed(1.0, "W"),
                }
            )
        }
    )
    estimate = estimate_idea(odd, _catalog())
    statuses = {f.constraint: f.status for f in estimate.findings}
    assert statuses["cost"] == "not_comparable"
    assert statuses["power"] == "not_comparable"


def test_estimate_is_deterministic() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    catalog = _catalog()
    assert estimate_idea(record, catalog).model_dump_json() == estimate_idea(
        record, catalog
    ).model_dump_json()
