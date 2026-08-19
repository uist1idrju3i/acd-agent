"""Append-only side-effect journal storage and reconstruction."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.schema import (
    JournalResultStatus,
    PostOrderJournalEntry,
    PreOrderGateRecord,
    PreOrderJournalEntry,
)
from acd.schema.common import IdempotencyKey, NonEmptyStr, Sha256, Timestamp

JournalEntry = PreOrderJournalEntry | PostOrderJournalEntry


class SideEffectJournalError(ValueError):
    """Raised when a side-effect journal cannot be safely used."""


@dataclass(frozen=True)
class JournalOrderReconstruction:
    planned: PreOrderJournalEntry
    result: PostOrderJournalEntry


def _parse_entry(line: str, line_number: int) -> JournalEntry:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SideEffectJournalError(
            f"journal line {line_number} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SideEffectJournalError(f"journal line {line_number} must be an object")
    mapping = cast(dict[str, object], value)
    entry_type = mapping.get("entry_type")
    try:
        if entry_type == "pre_order":
            return PreOrderJournalEntry.model_validate(value)
        if entry_type == "post_order":
            return PostOrderJournalEntry.model_validate(value)
    except ValueError as exc:
        raise SideEffectJournalError(
            f"journal line {line_number} failed contract validation"
        ) from exc
    raise SideEffectJournalError(
        f"journal line {line_number} has an unsupported entry type"
    )


def _validate_entries(entries: Sequence[JournalEntry], *, require_complete: bool) -> None:
    planned_by_key: dict[str, PreOrderJournalEntry] = {}
    planned_by_hash: dict[str, tuple[int, PreOrderJournalEntry]] = {}
    result_by_key: dict[str, PostOrderJournalEntry] = {}
    previous: JournalEntry | None = None
    for index, entry in enumerate(entries, start=1):
        if previous is None:
            if entry.previous_entry_hash is not None:
                raise SideEffectJournalError(
                    "first journal entry must not reference a previous entry"
                )
        elif entry.previous_entry_hash != previous.entry_hash:
            raise SideEffectJournalError(
                f"journal hash chain is broken at line {index}"
            )
        if previous is not None and entry.occurred_at < previous.occurred_at:
            raise SideEffectJournalError(
                f"journal timestamp moved backwards at line {index}"
            )
        if isinstance(entry, PreOrderJournalEntry):
            if entry.idempotency_key in planned_by_key:
                raise SideEffectJournalError(
                    "journal idempotency key has duplicate pre-order entries"
                )
            planned_by_key[entry.idempotency_key] = entry
            planned_by_hash[entry.entry_hash] = (index, entry)
        else:
            if entry.idempotency_key in result_by_key:
                raise SideEffectJournalError(
                    "journal idempotency key has duplicate post-order entries"
                )
            planned_record = planned_by_hash.get(entry.planned_entry_hash)
            if planned_record is None:
                raise SideEffectJournalError(
                    "post-order journal entry has no preceding pre-order entry"
                )
            planned_index, planned = planned_record
            if planned_index >= index:
                raise SideEffectJournalError(
                    "post-order journal entry must follow its pre-order entry"
                )
            if entry.idempotency_key != planned.idempotency_key:
                raise SideEffectJournalError(
                    "post-order idempotency key does not match pre-order entry"
                )
            if (
                entry.authorization_hash != planned.authorization_hash
                or entry.planned_authorization_hash != planned.authorization_hash
                or entry.package_hash != planned.package_hash
                or entry.planned_package_hash != planned.package_hash
                or entry.target_revision != planned.target_revision
                or entry.planned_target_revision != planned.target_revision
                or entry.destination != planned.destination
            ):
                raise SideEffectJournalError(
                    "post-order journal entry does not match pre-order entry"
                )
            result_by_key[entry.idempotency_key] = entry
        previous = entry
    if require_complete:
        missing_results = set(planned_by_key) - set(result_by_key)
        if missing_results:
            raise SideEffectJournalError(
                "journal has pre-order entries without post-order results"
            )


def read_journal(
    path: Path,
    *,
    require_complete: bool = False,
) -> tuple[JournalEntry, ...]:
    """Read and validate every entry in a JSON Lines journal."""
    if not path.exists():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SideEffectJournalError(f"could not read journal: {path}") from exc
    if any(not line.strip() for line in lines):
        raise SideEffectJournalError("journal must not contain blank lines")
    entries = tuple(
        _parse_entry(line, line_number)
        for line_number, line in enumerate(lines, start=1)
    )
    _validate_entries(entries, require_complete=require_complete)
    return entries


def _append_entry(path: Path, entry: JournalEntry) -> None:
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(entry.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise SideEffectJournalError(f"could not append journal: {path}") from exc


def append_pre_order(
    path: Path,
    *,
    authorization: PreOrderGateRecord,
    package_hash: Sha256,
    destination: NonEmptyStr,
    idempotency_key: IdempotencyKey,
    occurred_at: Timestamp,
) -> PreOrderJournalEntry:
    """Append a pre-order entry after validating the existing journal."""
    entries = read_journal(path)
    if any(
        isinstance(entry, PreOrderJournalEntry)
        and entry.idempotency_key == idempotency_key
        for entry in entries
    ):
        raise SideEffectJournalError(
            "journal idempotency key already has a pre-order entry"
        )
    try:
        entry = PreOrderJournalEntry.create(
            idempotency_key=idempotency_key,
            authorization_hash=authorization.authorization_hash,
            target_revision=authorization.target_revision,
            package_hash=package_hash,
            destination=destination,
            occurred_at=occurred_at,
            previous_entry_hash=entries[-1].entry_hash if entries else None,
        )
    except ValueError as exc:
        raise SideEffectJournalError("invalid pre-order journal entry") from exc
    _append_entry(path, entry)
    return entry


def append_post_order(
    path: Path,
    *,
    planned: PreOrderJournalEntry,
    result_status: JournalResultStatus,
    receipt_id: NonEmptyStr,
    receipt_hash: Sha256,
    occurred_at: Timestamp,
) -> PostOrderJournalEntry:
    """Append a post-order result for an existing pre-order entry."""
    entries = read_journal(path)
    planned_entries = {
        entry.entry_hash: entry
        for entry in entries
        if isinstance(entry, PreOrderJournalEntry)
    }
    stored_planned = planned_entries.get(planned.entry_hash)
    if stored_planned is None:
        raise SideEffectJournalError(
            "post-order journal entry requires an existing pre-order entry"
        )
    if any(
        isinstance(entry, PostOrderJournalEntry)
        and entry.idempotency_key == planned.idempotency_key
        for entry in entries
    ):
        raise SideEffectJournalError(
            "journal idempotency key already has a post-order entry"
        )
    if stored_planned != planned:
        raise SideEffectJournalError("provided pre-order entry does not match journal")
    if entries and occurred_at < entries[-1].occurred_at:
        raise SideEffectJournalError("journal timestamp moved backwards")
    try:
        entry = PostOrderJournalEntry.create(
            planned=planned,
            result_status=result_status,
            receipt_id=receipt_id,
            receipt_hash=receipt_hash,
            occurred_at=occurred_at,
            previous_entry_hash=entries[-1].entry_hash if entries else None,
        )
    except ValueError as exc:
        raise SideEffectJournalError("invalid post-order journal entry") from exc
    _append_entry(path, entry)
    return entry


def reconstruct_order(
    path: Path,
    *,
    idempotency_key: IdempotencyKey,
) -> JournalOrderReconstruction:
    """Reconstruct one complete order from a validated journal."""
    entries = read_journal(path, require_complete=True)
    planned = next(
        (
            entry
            for entry in entries
            if isinstance(entry, PreOrderJournalEntry)
            and entry.idempotency_key == idempotency_key
        ),
        None,
    )
    if planned is None:
        raise SideEffectJournalError(
            "journal has no pre-order entry for idempotency key"
        )
    result = next(
        (
            entry
            for entry in entries
            if isinstance(entry, PostOrderJournalEntry)
            and entry.idempotency_key == idempotency_key
        ),
        None,
    )
    if result is None:
        raise SideEffectJournalError(
            "journal has no post-order result for idempotency key"
        )
    return JournalOrderReconstruction(planned=planned, result=result)
