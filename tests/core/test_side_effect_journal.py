"""Append-only side-effect journal tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from acd.core.side_effect_journal import (
    SideEffectJournalError,
    append_post_order,
    append_pre_order,
    read_journal,
    reconstruct_order,
)
from acd.schema import (
    EvidenceReference,
    PostOrderJournalEntry,
    PostOrderJournalEntryBody,
    PreOrderGateRecord,
    PreOrderJournalEntry,
    QuoteAmount,
)
from acd.schema.common import canonical_sha256

ROOT = Path(__file__).parents[2]
HASH = "sha256:" + "a" * 64
PACKAGE_HASH = "sha256:" + "b" * 64
RECEIPT_HASH = "sha256:" + "c" * 64
TIMESTAMP = datetime(2026, 8, 14, tzinfo=UTC)


def _authorization() -> PreOrderGateRecord:
    amount = QuoteAmount(amount_minor=100, currency="USD", minor_unit_digits=2)
    return PreOrderGateRecord.create(
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


def _append_complete(path: Path) -> tuple[PreOrderJournalEntry, PostOrderJournalEntry]:
    planned = append_pre_order(
        path,
        authorization=_authorization(),
        execution_mode="dry_run",
        package_hash=PACKAGE_HASH,
        destination="supplier.example",
        idempotency_key="order-20260814",
        occurred_at=TIMESTAMP,
    )
    result = append_post_order(
        path,
        planned=planned,
        execution_mode="dry_run",
        result_status="success",
        receipt_id="receipt-20260814",
        receipt_hash=RECEIPT_HASH,
        occurred_at=TIMESTAMP + timedelta(seconds=1),
    )
    return planned, result


def test_journal_round_trip_and_reconstruction_are_deterministic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    planned, result = _append_complete(path)

    first = reconstruct_order(path, idempotency_key=planned.idempotency_key)
    second = reconstruct_order(path, idempotency_key=planned.idempotency_key)

    assert first == second
    assert first.planned == planned
    assert first.result == result
    assert len(read_journal(path, require_complete=True)) == 2


def test_journal_rejects_duplicate_resend_and_missing_post_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    planned = append_pre_order(
        path,
        authorization=_authorization(),
        execution_mode="dry_run",
        package_hash=PACKAGE_HASH,
        destination="supplier.example",
        idempotency_key="order-20260814",
        occurred_at=TIMESTAMP,
    )
    with pytest.raises(SideEffectJournalError, match="already has a pre-order"):
        append_pre_order(
            path,
            authorization=_authorization(),
            execution_mode="dry_run",
            package_hash=PACKAGE_HASH,
            destination="supplier.example",
            idempotency_key=planned.idempotency_key,
            occurred_at=TIMESTAMP,
        )
    with pytest.raises(SideEffectJournalError, match="without post-order"):
        read_journal(path, require_complete=True)


def test_journal_rejects_post_execution_mode_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    planned = append_pre_order(
        path,
        authorization=_authorization(),
        execution_mode="dry_run",
        package_hash=PACKAGE_HASH,
        destination="supplier.example",
        idempotency_key="order-20260814",
        occurred_at=TIMESTAMP,
    )
    with pytest.raises(SideEffectJournalError, match="execution mode"):
        append_post_order(
            path,
            planned=planned,
            execution_mode="real",
            result_status="success",
            receipt_id="receipt-20260814",
            receipt_hash=RECEIPT_HASH,
            occurred_at=TIMESTAMP,
        )
    with pytest.raises(
        SideEffectJournalError,
        match=r"without post-order|no post-order",
    ):
        reconstruct_order(path, idempotency_key=planned.idempotency_key)


def test_journal_rejects_post_result_without_planned_entry(tmp_path: Path) -> None:
    with pytest.raises(SideEffectJournalError, match="requires an existing"):
        append_post_order(
            tmp_path / "journal.jsonl",
            planned=PreOrderJournalEntry.create(
                execution_mode="dry_run",
                idempotency_key="order-20260814",
                authorization_hash=HASH,
                target_revision="r1",
                package_hash=PACKAGE_HASH,
                destination="supplier.example",
                occurred_at=TIMESTAMP,
                previous_entry_hash=None,
            ),
            execution_mode="dry_run",
            result_status="failure",
            receipt_id="receipt-20260814",
            receipt_hash=RECEIPT_HASH,
            occurred_at=TIMESTAMP,
        )


@pytest.mark.parametrize("mutation", ["tamper", "delete", "reorder"])
def test_journal_detects_append_only_corruption(
    tmp_path: Path,
    mutation: str,
) -> None:
    path = tmp_path / "journal.jsonl"
    _append_complete(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if mutation == "tamper":
        value = json.loads(lines[0])
        assert isinstance(value, dict)
        value["package_hash"] = "sha256:" + "d" * 64
        lines[0] = json.dumps(value)
    elif mutation == "delete":
        lines = lines[:1]
    else:
        lines.reverse()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SideEffectJournalError):
        read_journal(path, require_complete=True)


def test_append_refuses_corrupted_existing_journal(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    _append_complete(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace(PACKAGE_HASH, "sha256:" + "d" * 64)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SideEffectJournalError, match=r"hash|contract"):
        append_pre_order(
            path,
            authorization=_authorization(),
            execution_mode="dry_run",
            package_hash=PACKAGE_HASH,
            destination="supplier.example",
            idempotency_key="order-20260815",
            occurred_at=TIMESTAMP + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("package_hash", "sha256:" + "d" * 64, "does not match"),
        ("authorization_hash", "sha256:" + "d" * 64, "does not match"),
        ("target_revision", "r2", "does not match"),
        ("occurred_at", datetime(2026, 8, 13, tzinfo=UTC), "timestamp"),
    ],
)
def test_journal_rejects_post_mismatch(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    path = tmp_path / "journal.jsonl"
    _, result = _append_complete(path)
    body = result.model_dump(mode="python")
    body[field] = value
    body.pop("entry_hash")
    body["entry_hash"] = canonical_sha256(PostOrderJournalEntryBody.model_validate(body))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(body, default=str)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SideEffectJournalError, match=message):
        read_journal(path)


def test_reconstruct_order_rejects_missing_journal(tmp_path: Path) -> None:
    with pytest.raises(SideEffectJournalError, match="does not exist"):
        reconstruct_order(
            tmp_path / "missing.jsonl",
            idempotency_key="order-20260814",
        )


def test_journal_write_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "journal.jsonl"

    def fail_open(*args: object, **kwargs: object) -> object:
        raise OSError("read-only")

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(SideEffectJournalError, match="could not append"):
        append_pre_order(
            path,
            authorization=_authorization(),
            execution_mode="dry_run",
            package_hash=PACKAGE_HASH,
            destination="supplier.example",
            idempotency_key="order-20260814",
            occurred_at=TIMESTAMP,
        )


def test_valid_journal_fixture_reconstructs() -> None:
    reconstruction = reconstruct_order(
        ROOT / "fixtures/contracts/valid/side-effect-journal.jsonl",
        idempotency_key="order-20260814",
    )
    assert reconstruction.result.result_status == "success"
