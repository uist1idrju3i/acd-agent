"""CLI tests for the order-execution dry-run boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import order_execution

from acd.schema import EvidenceReference, PreOrderGateRecord, QuoteAmount

HASH = "sha256:" + "a" * 64
TIMESTAMP = datetime(2026, 8, 14, tzinfo=UTC)


def _permit(path: Path) -> None:
    amount = QuoteAmount(amount_minor=100, currency="USD", minor_unit_digits=2)
    permit = PreOrderGateRecord.create(
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
    path.write_text(permit.model_dump_json(), encoding="utf-8")


def _args(permit: Path, journal: Path) -> list[str]:
    return [
        "--permit",
        str(permit),
        "--journal",
        str(journal),
        "--idempotency-key",
        "order-20260814",
        "--package-hash",
        "sha256:" + "b" * 64,
        "--destination",
        "supplier.example",
        "--target-revision",
        "r1",
        "--credential-reference",
        "ACD_API_KEY",
        "--occurred-at",
        "2026-08-14T00:00:00Z",
        "--command",
        "echo",
        "dry-run",
    ]


def test_order_execution_cli_defaults_to_dry_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    permit = tmp_path / "permit.json"
    journal = tmp_path / "journal.jsonl"
    _permit(permit)

    assert order_execution.main(_args(permit, journal)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["payload"]["execution_mode"] == "dry_run"


def test_order_execution_cli_real_flag_refuses(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    permit = tmp_path / "permit.json"
    journal = tmp_path / "journal.jsonl"
    _permit(permit)

    assert order_execution.main([*_args(permit, journal), "--real"]) == 2
    assert "not enabled" in capsys.readouterr().err
    assert not journal.exists()


def test_order_execution_cli_rejects_missing_permit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        order_execution.main(
            _args(tmp_path / "missing.json", tmp_path / "journal.jsonl")
        )
        == 2
    )
    assert "refused" in capsys.readouterr().err


def test_order_execution_cli_rejects_malformed_package_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    permit = tmp_path / "permit.json"
    journal = tmp_path / "journal.jsonl"
    _permit(permit)
    args = _args(permit, journal)
    args[args.index("--package-hash") + 1] = "not-a-hash"

    assert order_execution.main(args) == 2
    assert "refused" in capsys.readouterr().err
    assert not journal.exists()


def test_order_execution_cli_requires_dry_run_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    permit = tmp_path / "permit.json"
    journal = tmp_path / "journal.jsonl"
    _permit(permit)
    args = _args(permit, journal)
    command_index = args.index("--command")
    del args[command_index:]

    with pytest.raises(SystemExit) as error:
        order_execution.main(args)
    assert error.value.code == 2
    assert "required" in capsys.readouterr().err
    assert not journal.exists()
