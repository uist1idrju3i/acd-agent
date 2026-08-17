"""Evidence CLI tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from acd.openhands.evidence_check import check


def test_valid_evidence_is_accepted(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert check("r3", [target])


def test_wrong_revision_and_unknown_are_rejected(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    record["target_revision"] = "r4"
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", [target])
    record["target_revision"] = "r3"
    record["envelope"]["tool_version"] = "unknown"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", [target])


def test_required_id_missing_and_stale_are_rejected(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    target = tmp_path / "evidence.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", [target], {"missing-id"})
    record["status"] = "stale"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert not check("r3", [target], {record["evidence_id"]})


def test_all_required_ids_must_pass(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    record = json.loads(source.read_text(encoding="utf-8"))
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(record), encoding="utf-8")
    record["evidence_id"] = "evidence.second"
    second.write_text(json.dumps(record), encoding="utf-8")
    assert check("r3", [first, second], {"ev-erc-r3-0001", "evidence.second"})


def test_cli_accepts_multiple_evidence_paths(tmp_path: Path) -> None:
    source = Path("fixtures/contracts/valid/evidence.json")
    first_record = json.loads(source.read_text(encoding="utf-8"))
    second_record = {**first_record, "evidence_id": "evidence.second"}
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(first_record), encoding="utf-8")
    second.write_text(json.dumps(second_record), encoding="utf-8")
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "acd-evidence-check",
            "--revision",
            "r3",
            "--evidence",
            str(first),
            "--evidence",
            str(second),
            "--require-id",
            first_record["evidence_id"],
            "--require-id",
            "evidence.second",
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0


def test_cli_rejects_valid_only_with_revision_or_required_id(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "acd-evidence-check",
            "--valid-only",
            "--revision",
            "r3",
            "--require-id",
            "evidence.any",
            "--evidence",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 2
