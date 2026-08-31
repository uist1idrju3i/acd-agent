"""Regression tests for GD1 revision-aligned order totals."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from acd.core.order_total import OrderTotalError, aggregate_order_total
from acd.schema import FabProfileDocument, OrderScope, QuoteRecord

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
SCOPE_PATH = ROOT / "fixtures/contracts/valid/order-scope-golden-design-1.json"
QUOTE_PATH = ROOT / "fixtures/contracts/valid/quote-order-golden-design-1.json"
PROFILE_PATH = ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"
EVALUATED_AT = datetime(2025, 1, 11, 0, 0, tzinfo=UTC)


def load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def test_gd1_order_total_uses_graph_revision_and_rejects_mismatch() -> None:
    graph_revision = load_json(GRAPH_PATH)["revision"]
    assert isinstance(graph_revision, str)
    scope_value = load_json(SCOPE_PATH)
    quote_value = load_json(QUOTE_PATH)
    assert scope_value["target_revision"] == graph_revision
    assert quote_value["target_revision"] == graph_revision

    scope = OrderScope.model_validate(scope_value)
    quote = QuoteRecord.model_validate(quote_value)
    profile = FabProfileDocument.model_validate(load_json(PROFILE_PATH))
    result = aggregate_order_total(
        [quote],
        scope,
        fab_profile=profile,
        evaluated_at=EVALUATED_AT,
        target_revision=graph_revision,
    )
    assert result.target_revision == graph_revision
    assert result.total.amount_minor == 9300

    with pytest.raises(OrderTotalError, match="scope target revision"):
        aggregate_order_total(
            [quote],
            scope,
            fab_profile=profile,
            evaluated_at=EVALUATED_AT,
            target_revision="r2",
        )
