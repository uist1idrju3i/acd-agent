"""End-to-end tests for deterministic receipt ingestion."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from acd.schema import PhysicalEvidence


def test_ingest_receipt_is_byte_stable(tmp_path: Path) -> None:
    manifest = Path("fixtures/contracts/valid/fab-package-receipt.json")
    receipt = Path("fixtures/contracts/valid/receipt.json")
    evidence_one = tmp_path / "evidence-one.json"
    report_one = tmp_path / "report-one.json"
    evidence_two = tmp_path / "evidence-two.json"
    report_two = tmp_path / "report-two.json"

    for evidence, report in (
        (evidence_one, report_one),
        (evidence_two, report_two),
    ):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ingest_receipt.py",
                "--manifest",
                str(manifest),
                "--receipt",
                str(receipt),
                "--evidence",
                str(evidence),
                "--report",
                str(report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0

    assert evidence_one.read_bytes() == evidence_two.read_bytes()
    assert report_one.read_bytes() == report_two.read_bytes()
    first_evidence = PhysicalEvidence.model_validate(json.loads(evidence_one.read_text()))
    second_evidence = PhysicalEvidence.model_validate(json.loads(evidence_two.read_text()))
    assert first_evidence.canonical_hash() == second_evidence.canonical_hash()


def test_ingest_receipt_blocks_manifest_unknowns(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_receipt.py",
            "--manifest",
            "fixtures/contracts/invalid/fab-package-unknowns.json",
            "--receipt",
            "fixtures/contracts/valid/receipt.json",
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "unknown"
