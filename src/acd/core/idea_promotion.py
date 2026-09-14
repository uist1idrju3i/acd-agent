"""Promote a fully-confirmed idea record to requirement records (ADR-0049)."""

from __future__ import annotations

from pathlib import Path

from acd.schema.common import canonical_sha256
from acd.schema.idea import IdeaField, IdeaRecord
from acd.schema.idea_promotion import (
    IdeaPromotionProvenance,
    IdeaPromotionRationale,
)
from acd.schema.requirement import RequirementDocument, RequirementRecord


class IdeaPromotionError(ValueError):
    """Raised when an idea record cannot be promoted to requirements."""


def load_promotion_rationale(path: Path) -> IdeaPromotionRationale:
    """Load a promotion rationale; any parse or validation failure is an error."""
    try:
        return IdeaPromotionRationale.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise IdeaPromotionError(
            f"promotion rationale {path} is not valid: {exc}"
        ) from exc


def _statement(field: IdeaField) -> str:
    value = field.value
    text = repr(value) if isinstance(value, float) else str(value)
    if field.unit is not None:
        text = f"{text} {field.unit}"
    return text


def _promoted_items(record: IdeaRecord) -> list[tuple[str, IdeaField]]:
    """Return (requirement_id, field) pairs in declaration order."""
    items: list[tuple[str, IdeaField]] = [
        (item.criterion_id, item.statement) for item in record.success_criteria
    ]
    items.extend(
        (item.function_id, item.description)
        for item in record.functions
        if item.priority == "must"
    )
    items.extend(
        (item.function_id, item.description)
        for item in record.functions
        if item.priority == "should"
    )
    return [
        (f"{record.idea_id}-req-{index:03d}", field)
        for index, (_, field) in enumerate(items, start=1)
    ]


def promote_idea(
    record: IdeaRecord,
    rationale: IdeaPromotionRationale,
    *,
    graph_id: str,
    revision: str,
    script_hash: str,
) -> tuple[RequirementDocument, IdeaPromotionProvenance]:
    """Promote a fully-confirmed idea record; fail closed on any unknown."""
    open_items = record.open_items()
    if open_items:
        raise IdeaPromotionError(
            f"idea {record.idea_id} has open items and cannot be promoted: "
            + ", ".join(open_items)
        )
    if rationale.idea_id != record.idea_id:
        raise IdeaPromotionError(
            f"rationale idea_id {rationale.idea_id!r} does not match "
            f"record idea_id {record.idea_id!r}"
        )
    if rationale.revision != record.revision:
        raise IdeaPromotionError(
            f"rationale revision {rationale.revision!r} does not match "
            f"record revision {record.revision!r}"
        )
    pairs = _promoted_items(record)
    by_id: dict[str, int] = {}
    for entry in rationale.records:
        by_id[entry.requirement_id] = by_id.get(entry.requirement_id, 0) + 1
    known_ids = {requirement_id for requirement_id, _ in pairs}
    for requirement_id in by_id:
        if requirement_id not in known_ids:
            raise IdeaPromotionError(
                f"rationale record for unknown requirement {requirement_id!r}"
            )
    for requirement_id, _ in pairs:
        if by_id.get(requirement_id, 0) != 1:
            raise IdeaPromotionError(
                f"requirement {requirement_id!r} must have exactly one "
                "rationale record"
            )
    document = RequirementDocument(
        graph_id=graph_id,
        revision=revision,
        records=[
            RequirementRecord(
                requirement_id=requirement_id,
                statement=_statement(field),
                graph_anchored=False,
            )
            for requirement_id, field in pairs
        ],
    )
    provenance = IdeaPromotionProvenance(
        idea_id=record.idea_id,
        idea_revision=record.revision,
        graph_id=graph_id,
        target_revision=revision,
        idea_hash=canonical_sha256(record),
        rationale_hash=canonical_sha256(rationale),
        script_hash=script_hash,
        requirement_ids=[requirement_id for requirement_id, _ in pairs],
    )
    return document, provenance
