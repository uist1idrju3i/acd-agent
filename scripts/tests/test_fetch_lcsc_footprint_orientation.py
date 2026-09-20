"""Tests for the pure LCSC fetch record builder."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.fetch_lcsc_footprint_orientation import build_record

from acd.core.runtime.evidence_declarations import (
    check_cpl_rotation_record,
    cpl_rotation_record_path,
)

PAYLOAD = {
    "result": {
        "dataStr": {
            "head": {
                "c_para": {
                    "Manufacturer Part": "0603WAF4701T5E",
                    "package": "R0603",
                    "Manufacturer": "UNI-ROYAL",
                    "Supplier Part": "C23162",
                }
            }
        },
        "description": "4.7kΩ",
    }
}


def _build(
    *,
    expect_mpn: str | None,
    expect_package: str | None = None,
) -> tuple[dict[str, object], int]:
    return build_record(
        refdes="R1",
        lcsc="C23162",
        url="https://example.test/C23162",
        payload=json.dumps(PAYLOAD).encode("utf-8"),
        retrieved_at="2026-09-08T00:00:00Z",
        expect_mpn=expect_mpn,
        expect_package=expect_package,
    )


def test_build_record_match_preserves_keys_and_adds_checks() -> None:
    record, exit_code = _build(
        expect_mpn="0603WAF4701T5E",
        expect_package="R0603",
    )
    assert exit_code == 0
    assert {
        "schema_version",
        "refdes",
        "lcsc",
        "url",
        "retrieved_at",
        "response_sha256",
        "response_canonical_sha256",
        "response",
        "identity",
        "mpn_check",
        "package_check",
        "lcsc_check",
    } <= record.keys()
    assert record["mpn_check"]["state"] == "match"  # type: ignore[index]
    assert record["identity"]["manufacturer_part"] == "0603WAF4701T5E"  # type: ignore[index]


def test_build_record_mismatch_returns_two() -> None:
    record, exit_code = _build(expect_mpn="KT-0603A")
    assert exit_code == 2
    assert record["mpn_check"]["state"] == "mismatch"  # type: ignore[index]


def test_build_record_without_mpn_expectation_still_records_identity() -> None:
    record, exit_code = _build(expect_mpn=None)
    assert exit_code == 0
    assert "mpn_check" not in record
    assert record["identity"]["package"] == "R0603"  # type: ignore[index]


def test_built_record_resolves_through_cpl_rotation_checker(tmp_path: Path) -> None:
    record, exit_code = _build(expect_mpn="0603WAF4701T5E")
    assert exit_code == 0
    path = cpl_rotation_record_path(tmp_path, "demo-design", "R1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    assert check_cpl_rotation_record(path, refdes="R1", lcsc="C23162") is None
