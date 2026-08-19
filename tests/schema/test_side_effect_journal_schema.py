"""Side-effect journal contract tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from acd.schema import (
    JournalResultStatus,
    PostOrderJournalEntry,
    PreOrderJournalEntry,
)

ROOT = Path(__file__).parents[2]
HASH = "sha256:" + "a" * 64
TIMESTAMP = datetime(2026, 8, 14, tzinfo=UTC)


def test_journal_destination_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        PreOrderJournalEntry.create(
            execution_mode="dry_run",
            idempotency_key="order-20260814",
            authorization_hash=HASH,
            target_revision="r1",
            package_hash=HASH,
            destination="https://user:password@example.invalid/order",
            occurred_at=TIMESTAMP,
            previous_entry_hash=None,
        )


def test_journal_entry_hash_rejects_tampering() -> None:
    entry = PreOrderJournalEntry.create(
        execution_mode="dry_run",
        idempotency_key="order-20260814",
        authorization_hash=HASH,
        target_revision="r1",
        package_hash=HASH,
        destination="supplier.example",
        occurred_at=TIMESTAMP,
        previous_entry_hash=None,
    )
    value = entry.model_dump(mode="python")
    value["package_hash"] = "sha256:" + "b" * 64
    with pytest.raises(ValidationError, match="entry hash"):
        PreOrderJournalEntry.model_validate(value)


def test_journal_execution_mode_is_required() -> None:
    with pytest.raises(ValidationError):
        PreOrderJournalEntry.model_validate(
            {
                "schema_version": "0.1",
                "entry_type": "pre_order",
                "idempotency_key": "order-20260814",
                "authorization_hash": HASH,
                "target_revision": "r1",
                "package_hash": HASH,
                "destination": "supplier.example",
                "occurred_at": TIMESTAMP,
                "previous_entry_hash": None,
                "entry_hash": HASH,
            }
        )


def test_post_order_status_is_closed_set() -> None:
    planned = PreOrderJournalEntry.create(
        execution_mode="dry_run",
        idempotency_key="order-20260814",
        authorization_hash=HASH,
        target_revision="r1",
        package_hash=HASH,
        destination="supplier.example",
        occurred_at=TIMESTAMP,
        previous_entry_hash=None,
    )
    with pytest.raises(ValidationError):
        PostOrderJournalEntry.create(
            planned=planned,
            execution_mode="dry_run",
            result_status=cast(JournalResultStatus, "unknown"),
            receipt_id="receipt-20260814",
            receipt_hash=HASH,
            occurred_at=TIMESTAMP,
            previous_entry_hash=planned.entry_hash,
        )


def test_invalid_credential_url_fixture_is_rejected() -> None:
    value = json.loads(
        (
            ROOT / "fixtures/contracts/invalid/side-effect-journal-credential-url.json"
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(ValidationError):
        PreOrderJournalEntry.model_validate(value)
