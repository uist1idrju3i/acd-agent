"""Deterministic workaround application and retirement tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from scripts.check_workaround_retirement import main

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "fixtures/workaround-ledger/sample/ledger.json"
DEFECTS = ROOT / "fixtures/defect/sample/defects.json"
REWORK = ROOT / "fixtures/rework/sample/rework.json"
ECO = ROOT / "fixtures/eco/sample/eco.json"
ECO_CHECK = ROOT / "fixtures/workaround-ledger/sample/eco-check.json"
TO_GRAPH = ROOT / "fixtures/eco/sample/graph-r2.json"


def _args(
    out: Path,
    *,
    ledger: Path = LEDGER,
    defects: Path = DEFECTS,
    eco: Path = ECO,
    eco_check: Path = ECO_CHECK,
) -> list[str]:
    return [
        "--ledger",
        str(ledger),
        "--workaround-id",
        "WA-001",
        "--defects",
        str(defects),
        "--rework",
        str(REWORK),
        "--eco",
        str(eco),
        "--eco-id",
        "ECO-001",
        "--eco-check",
        str(eco_check),
        "--to-graph",
        str(TO_GRAPH),
        "--out-dir",
        str(out),
    ]


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_eco_check(path: Path, *, verdict: str, reasons: list[str]) -> Path:
    payload = _load(ECO_CHECK)
    payload["verdict"] = verdict
    payload["reasons"] = reasons
    return _write(path, payload)


def test_sample_workaround_is_retired(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main(_args(out)) == 0
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "retired"
    assert result["open_units"] == []


def test_serial_without_application_is_open(tmp_path: Path) -> None:
    defects = _load(DEFECTS)
    units = defects["records"][0]["affected_units"]
    units["lots"] = []
    units["serials"] = ["SER-GD1-001"]
    defects_path = _write(tmp_path / "defects.json", defects)
    out = tmp_path / "out"
    assert main(_args(out, defects=defects_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "active"
    assert result["open_units"] == [{"lot": None, "serial": "SER-GD1-001"}]
    assert result["unit_statuses"][0]["state"] == "unmodified"


def test_not_recorded_application_is_unverified(tmp_path: Path) -> None:
    ledger = _load(LEDGER)
    application = ledger["applications"][0]
    application["post_work_inspection"] = "not_recorded"
    application.pop("evidence_ref")
    ledger_path = _write(tmp_path / "ledger.json", ledger)
    out = tmp_path / "out"
    assert main(_args(out, ledger=ledger_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["unit_statuses"][0]["state"] == "applied_unverified"


def test_failed_application_is_failed(tmp_path: Path) -> None:
    ledger = _load(LEDGER)
    ledger["applications"][0]["post_work_inspection"] = "fail"
    ledger_path = _write(tmp_path / "ledger.json", ledger)
    out = tmp_path / "out"
    assert main(_args(out, ledger=ledger_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["unit_statuses"][0]["state"] == "applied_failed"


def test_scrapped_unit_is_closed(tmp_path: Path) -> None:
    ledger = _load(LEDGER)
    ledger["unit_dispositions"] = [
        {
            "unit": {"lot": "LOT-GD1-001"},
            "disposition": "scrapped",
            "reason": "Unit was scrapped.",
        }
    ]
    ledger["applications"][0]["post_work_inspection"] = "not_recorded"
    ledger["applications"][0].pop("evidence_ref")
    ledger_path = _write(tmp_path / "ledger.json", ledger)
    out = tmp_path / "out"
    assert main(_args(out, ledger=ledger_path)) == 0
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "retired"
    assert result["open_units"] == []


def test_upgraded_unit_with_wrong_revision_is_open(tmp_path: Path) -> None:
    ledger = _load(LEDGER)
    ledger["unit_dispositions"] = [
        {
            "unit": {"lot": "LOT-GD1-001"},
            "disposition": "upgraded_to_revision",
            "revision": "r3",
            "reason": "Unit was upgraded.",
        }
    ]
    ledger["applications"][0]["post_work_inspection"] = "not_recorded"
    ledger["applications"][0].pop("evidence_ref")
    ledger_path = _write(tmp_path / "ledger.json", ledger)
    out = tmp_path / "out"
    assert main(_args(out, ledger=ledger_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["open_units"]
    assert any("resolved revision" in reason for reason in result["reasons"])


def test_tampered_eco_check_hash_keeps_workaround_active(tmp_path: Path) -> None:
    eco_check = _write_eco_check(
        tmp_path / "eco-check.json",
        verdict="not_closable",
        reasons=["tampered"],
    )
    out = tmp_path / "out"
    assert main(_args(out, eco_check=eco_check)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "active"
    assert any("sha256" in reason for reason in result["reasons"])


def test_non_closable_eco_check_keeps_workaround_active(tmp_path: Path) -> None:
    eco_check = _write_eco_check(
        tmp_path / "eco-check.json",
        verdict="not_closable",
        reasons=["gate failed"],
    )
    ledger = _load(LEDGER)
    ledger["retirements"][0]["eco_check_sha256"] = (
        "sha256:" + hashlib.sha256(eco_check.read_bytes()).hexdigest()
    )
    ledger_path = _write(tmp_path / "ledger.json", ledger)
    out = tmp_path / "out"
    assert main(_args(out, ledger=ledger_path, eco_check=eco_check)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "active"
    assert any("not closable" in reason for reason in result["reasons"])


def test_eco_not_listing_workaround_keeps_it_active(tmp_path: Path) -> None:
    eco = _load(ECO)
    eco["ecos"][0]["retires_workaround_ids"] = []
    eco_path = _write(tmp_path / "eco.json", eco)
    out = tmp_path / "out"
    assert main(_args(out, eco=eco_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert any("does not list the workaround" in reason for reason in result["reasons"])


def test_eco_missing_defect_reason_keeps_it_active(tmp_path: Path) -> None:
    eco = _load(ECO)
    eco["ecos"][0]["reasons"] = [
        {
            "kind": "requirement",
            "ref": "REQ-001",
            "detail": "A requirement changed.",
        }
    ]
    eco_path = _write(tmp_path / "eco.json", eco)
    out = tmp_path / "out"
    assert main(_args(out, eco=eco_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert any("does not cover defects" in reason for reason in result["reasons"])


def test_unknown_defect_scope_returns_unknown(tmp_path: Path) -> None:
    defects = _load(DEFECTS)
    units = defects["records"][0]["affected_units"]
    units["lots"] = []
    units["scope_status"] = "unknown"
    defects_path = _write(tmp_path / "defects.json", defects)
    out = tmp_path / "out"
    assert main(_args(out, defects=defects_path)) == 1
    result = _load(out / "workaround-retirement-check.json")
    assert result["verdict"] == "unknown"
    assert "unknown" in result["reasons"][0]
