"""Contracts for append-only side-effect journal entries."""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    IdempotencyKey,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Sha256,
    Timestamp,
    canonical_sha256,
    contains_unknown,
)

JournalEntryType = Literal["pre_order", "post_order"]
JournalResultStatus = Literal["success", "failure", "rejected"]


def _validate_destination(value: str) -> str:
    if contains_unknown(value):
        raise ValueError("journal destination must not be unknown")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("journal destination is invalid") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("journal destination must not contain credentials")
    if "@" in parsed.netloc:
        raise ValueError("journal destination must not contain credentials")
    return value


class JournalEntryBody[EntryTypeT: str](AcdModel):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    entry_type: EntryTypeT
    idempotency_key: IdempotencyKey
    authorization_hash: Sha256
    target_revision: Revision
    package_hash: Sha256
    destination: NonEmptyStr
    occurred_at: Timestamp
    previous_entry_hash: Sha256 | None = None

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        return _validate_destination(value)

    @model_validator(mode="after")
    def validate_body(self) -> Self:
        if contains_unknown(self.model_dump(mode="json")):
            raise ValueError("journal entry must not contain unknown")
        return self


class PreOrderJournalEntryBody(JournalEntryBody[Literal["pre_order"]]):
    entry_type: Literal["pre_order"] = "pre_order"


class PreOrderJournalEntry(PreOrderJournalEntryBody):
    entry_hash: Sha256

    @model_validator(mode="after")
    def validate_entry_hash(self) -> Self:
        body = PreOrderJournalEntryBody.model_validate(
            self.model_dump(exclude={"entry_hash"})
        )
        if self.entry_hash != canonical_sha256(body):
            raise ValueError("pre-order journal entry hash does not match contents")
        return self

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: IdempotencyKey,
        authorization_hash: Sha256,
        target_revision: Revision,
        package_hash: Sha256,
        destination: NonEmptyStr,
        occurred_at: Timestamp,
        previous_entry_hash: Sha256 | None,
    ) -> PreOrderJournalEntry:
        body = PreOrderJournalEntryBody(
            idempotency_key=idempotency_key,
            authorization_hash=authorization_hash,
            target_revision=target_revision,
            package_hash=package_hash,
            destination=destination,
            occurred_at=occurred_at,
            previous_entry_hash=previous_entry_hash,
        )
        return cls.model_validate(
            {
                **body.model_dump(mode="python"),
                "entry_hash": canonical_sha256(body),
            }
        )


class PostOrderJournalEntryBody(JournalEntryBody[Literal["post_order"]]):
    entry_type: Literal["post_order"] = "post_order"
    result_status: JournalResultStatus
    receipt_id: NonEmptyStr
    receipt_hash: Sha256
    planned_entry_hash: Sha256
    planned_authorization_hash: Sha256
    planned_package_hash: Sha256
    planned_target_revision: Revision


class PostOrderJournalEntry(PostOrderJournalEntryBody):
    entry_hash: Sha256

    @model_validator(mode="after")
    def validate_entry_hash(self) -> Self:
        body = PostOrderJournalEntryBody.model_validate(
            self.model_dump(exclude={"entry_hash"})
        )
        if self.entry_hash != canonical_sha256(body):
            raise ValueError("post-order journal entry hash does not match contents")
        return self

    @classmethod
    def create(
        cls,
        *,
        planned: PreOrderJournalEntry,
        result_status: JournalResultStatus,
        receipt_id: NonEmptyStr,
        receipt_hash: Sha256,
        occurred_at: Timestamp,
        previous_entry_hash: Sha256 | None,
    ) -> PostOrderJournalEntry:
        body = PostOrderJournalEntryBody(
            idempotency_key=planned.idempotency_key,
            authorization_hash=planned.authorization_hash,
            target_revision=planned.target_revision,
            package_hash=planned.package_hash,
            destination=planned.destination,
            occurred_at=occurred_at,
            previous_entry_hash=previous_entry_hash,
            result_status=result_status,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            planned_entry_hash=planned.entry_hash,
            planned_authorization_hash=planned.authorization_hash,
            planned_package_hash=planned.package_hash,
            planned_target_revision=planned.target_revision,
        )
        return cls.model_validate(
            {
                **body.model_dump(mode="python"),
                "entry_hash": canonical_sha256(body),
            }
        )
