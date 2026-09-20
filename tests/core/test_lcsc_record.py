"""Tests for pure LCSC record identity and declaration checks."""

from __future__ import annotations

from acd.core.manufacturing.lcsc_record import (
    LcscRecordIdentity,
    check_declared_lcsc,
    check_declared_mpn,
    extract_lcsc_identity,
    normalize_part_number,
)


def _response() -> dict[str, object]:
    return {
        "result": {
            "dataStr": {
                "head": {
                    "c_para": {
                        "Manufacturer Part": "0603WAF4701T5E",
                        "package": "R0603",
                        "Manufacturer": "UNI-ROYAL(厚声)",
                        "Supplier Part": "C23162",
                    }
                }
            },
            "description": "4.7KΩ (4701) ±1%",
            "title": "fallback",
        }
    }


def test_extract_identity_from_lcsc_response_shape() -> None:
    identity = extract_lcsc_identity(_response())
    assert identity.as_dict() == {
        "manufacturer_part": "0603WAF4701T5E",
        "package": "R0603",
        "manufacturer": "UNI-ROYAL(厚声)",
        "supplier_part": "C23162",
        "description": "4.7KΩ (4701) ±1%",
    }


def test_extract_identity_missing_levels_returns_none() -> None:
    identity = extract_lcsc_identity({"result": {"dataStr": {"head": {}}}})
    assert identity == LcscRecordIdentity(None, None, None, None, None)
    assert extract_lcsc_identity({"result": {"title": "fallback"}}).description == (
        "fallback"
    )
    assert extract_lcsc_identity({"result": {"description": 1}}).description is None
    assert extract_lcsc_identity({"result": []}).as_dict() == {
        "manufacturer_part": None,
        "package": None,
        "manufacturer": None,
        "supplier_part": None,
        "description": None,
    }


def test_normalize_part_number() -> None:
    assert normalize_part_number("  0603waf4701t5e \n ") == "0603WAF4701T5E"
    assert normalize_part_number("A   B\tC") == "A B C"


def test_declared_mpn_and_lcsc_match() -> None:
    identity = extract_lcsc_identity(_response())
    assert check_declared_mpn(identity, declared_mpn=" 0603waf4701t5e").state == "match"
    assert check_declared_lcsc(identity, declared_lcsc="c23162").state == "match"
    assert check_declared_mpn(identity, declared_mpn="0603WAF4701T5E").reason == ""


def test_declared_mpn_mismatch_and_unknown() -> None:
    identity = extract_lcsc_identity(_response())
    mismatch = check_declared_mpn(identity, declared_mpn="KT-0603A")
    assert mismatch.state == "mismatch"
    assert "Manufacturer Part" in mismatch.reason
    assert check_declared_mpn(identity, declared_mpn=None).state == "unknown"
    assert check_declared_mpn(
        LcscRecordIdentity(None, "R0603", None, "C1", None),
        declared_mpn="PART",
    ).state == "unknown"


def test_declared_lcsc_mismatch_and_unknown() -> None:
    identity = extract_lcsc_identity(_response())
    assert check_declared_lcsc(identity, declared_lcsc="C1").state == "mismatch"
    assert check_declared_lcsc(
        LcscRecordIdentity("PART", "R0603", None, None, None),
        declared_lcsc="C1",
    ).state == "unknown"
