"""Evidence CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

from acd_tools.evidence_check import check


def test_valid_evidence_is_accepted(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert check("r3", target)


def test_wrong_revision_and_unknown_are_rejected(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    record["target_revision"] = "r4"
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", target)
    record["target_revision"] = "r3"
    record["envelope"]["tool_version"] = "unknown"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", target)


def test_required_id_missing_and_stale_are_rejected(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", target, {"missing-id"})
    record["status"] = "stale"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", target, {record["evidence_id"]})


def test_all_required_ids_must_pass(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(record), encoding="utf-8")
    record["evidence_id"] = "evidence.second"
    second.write_text(json.dumps(record), encoding="utf-8")
    assert check("r3", tmp_path, {"ev-erc-r3-0001", "evidence.second"})
