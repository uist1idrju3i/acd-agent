"""CLI tests for side-effect journal reconstruction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import side_effect_journal

from acd.core.side_effect_journal import append_post_order, append_pre_order
from acd.schema import EvidenceReference, PreOrderGateRecord, QuoteAmount

HASH = "sha256:" + "a" * 64
PACKAGE_HASH = "sha256:" + "b" * 64
TIMESTAMP = datetime(2026, 8, 14, tzinfo=UTC)


def _write_journal(path: Path) -> None:
    amount = QuoteAmount(amount_minor=100, currency="USD", minor_unit_digits=2)
    authorization = PreOrderGateRecord.create(
        target_revision="r1",
        total=amount,
        upper_limit=amount,
        breakdown_hash=HASH,
        evidence=[
            EvidenceReference(evidence_id="evidence.gd1.electrical", canonical_hash=HASH),
            EvidenceReference(evidence_id="evidence.gd1.mechanical", canonical_hash=HASH),
        ],
        policy_hash=HASH,
        evaluated_at=TIMESTAMP,
    )
    planned = append_pre_order(
        path,
        authorization=authorization,
        package_hash=PACKAGE_HASH,
        destination="supplier.example",
        idempotency_key="order-20260814",
        occurred_at=TIMESTAMP,
    )
    append_post_order(
        path,
        planned=planned,
        result_status="success",
        receipt_id="receipt-20260814",
        receipt_hash=HASH,
        occurred_at=datetime(2026, 8, 14, 0, 0, 1, tzinfo=UTC),
    )


def test_reconstruction_cli_outputs_one_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "journal.jsonl"
    _write_journal(path)

    assert (
        side_effect_journal.main(
            [
                "--journal",
                str(path),
                "--idempotency-key",
                "order-20260814",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["planned"]["entry_type"] == "pre_order"
    assert output["result"]["result_status"] == "success"


def test_reconstruction_cli_rejects_incomplete_journal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "journal.jsonl"
    _write_journal(path)
    path.write_text(
        path.read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )

    assert (
        side_effect_journal.main(
            [
                "--journal",
                str(path),
                "--idempotency-key",
                "order-20260814",
            ]
        )
        == 2
    )
    assert "failed" in capsys.readouterr().err
