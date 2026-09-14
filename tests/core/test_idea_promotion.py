"""Tests for idea-to-requirement promotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.idea_dialogue import load_idea_record
from acd.core.idea_promotion import (
    IdeaPromotionError,
    load_promotion_rationale,
    promote_idea,
)
from acd.schema.common import canonical_sha256
from acd.schema.idea import IdeaRecord
from acd.schema.idea_promotion import (
    IdeaPromotionProvenance,
    IdeaPromotionRationale,
)
from acd.schema.requirement import RequirementDocument

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPOSITORY / "fixtures" / "idea" / "sample-usb-thermometer"


def _promote() -> tuple[
    IdeaRecord,
    IdeaPromotionRationale,
    tuple[RequirementDocument, IdeaPromotionProvenance],
]:
    record = load_idea_record(FIXTURE_DIR / "idea-confirmed.json")
    rationale = load_promotion_rationale(
        FIXTURE_DIR / "promotion-rationale.json"
    )
    return record, rationale, promote_idea(
        record,
        rationale,
        graph_id="golden-design-1",
        revision="r1",
        script_hash="sha256:" + "0" * 64,
    )


def test_happy_path_ids_statements_and_provenance() -> None:
    record, rationale, (document, provenance) = _promote()
    ids = [entry.requirement_id for entry in document.records]
    assert ids == [
        "idea.sample-usb-thermometer-req-001",
        "idea.sample-usb-thermometer-req-002",
        "idea.sample-usb-thermometer-req-003",
    ]
    assert document.records[0].statement == "連続1時間の温度記録が欠落なく行える"
    assert document.records[0].graph_anchored is False
    assert provenance.idea_id == record.idea_id
    assert provenance.idea_hash == canonical_sha256(record)
    assert provenance.rationale_hash == canonical_sha256(rationale)
    assert provenance.requirement_ids == ids
    assert provenance.pass_evidence is False
    assert provenance.record_class == "L3"


def test_open_items_block_promotion() -> None:
    record = load_idea_record(FIXTURE_DIR / "idea.json")
    rationale = load_promotion_rationale(
        FIXTURE_DIR / "promotion-rationale.json"
    )
    with pytest.raises(IdeaPromotionError, match="open items"):
        promote_idea(
            record,
            rationale,
            graph_id="g",
            revision="r1",
            script_hash="sha256:" + "0" * 64,
        )


def test_missing_rationale_record_fails() -> None:
    record, rationale, _ = _promote()
    trimmed = rationale.model_copy(
        update={"records": rationale.records[:-1]}
    )
    with pytest.raises(IdeaPromotionError, match="exactly one"):
        promote_idea(
            record,
            trimmed,
            graph_id="g",
            revision="r1",
            script_hash="sha256:" + "0" * 64,
        )


def test_extra_rationale_record_fails() -> None:
    record, rationale, _ = _promote()
    extra = rationale.model_copy(
        update={
            "records": [
                *rationale.records,
                rationale.records[0].model_copy(
                    update={"requirement_id": "idea.x-req-999"}
                ),
            ]
        }
    )
    with pytest.raises(IdeaPromotionError, match="unknown requirement"):
        promote_idea(
            record,
            extra,
            graph_id="g",
            revision="r1",
            script_hash="sha256:" + "0" * 64,
        )


def test_idea_id_and_revision_mismatch_fail() -> None:
    record, rationale, _ = _promote()
    with pytest.raises(IdeaPromotionError, match="idea_id"):
        promote_idea(
            record,
            rationale.model_copy(update={"idea_id": "idea.other"}),
            graph_id="g",
            revision="r1",
            script_hash="sha256:" + "0" * 64,
        )
    with pytest.raises(IdeaPromotionError, match="revision"):
        promote_idea(
            record,
            rationale.model_copy(update={"revision": "r2"}),
            graph_id="g",
            revision="r1",
            script_hash="sha256:" + "0" * 64,
        )
