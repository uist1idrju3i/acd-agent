"""Tests for the order-total aggregation command."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import aggregate_order_total

from acd.core.order_total import order_total_result_from_document
from acd.schema import OrderTotalDocument

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "fixtures/contracts/valid/order-scope.json"
QUOTE = ROOT / "fixtures/contracts/valid/quote-order.json"
FAB_PROFILE = ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"


def test_aggregate_order_total_writes_validated_document(tmp_path: Path) -> None:
    output = tmp_path / "order-total.json"
    assert (
        aggregate_order_total.main(
            [
                "--quote-record",
                str(QUOTE),
                "--order-scope",
                str(SCOPE),
                "--fab-profile",
                str(FAB_PROFILE),
                "--target-revision",
                "r12",
                "--evaluated-at",
                "2025-01-11T00:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    document = OrderTotalDocument.model_validate_json(
        output.read_text(encoding="utf-8")
    )
    result = order_total_result_from_document(document)
    assert result.target_revision == "r12"
    assert document.breakdown_hash == result.breakdown_hash


def test_aggregate_order_total_rejects_revision_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "order-total.json"
    assert (
        aggregate_order_total.main(
            [
                "--quote-record",
                str(QUOTE),
                "--order-scope",
                str(SCOPE),
                "--fab-profile",
                str(FAB_PROFILE),
                "--target-revision",
                "r99",
                "--evaluated-at",
                "2025-01-11T00:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "refused" in capsys.readouterr().err
    assert not output.exists()
