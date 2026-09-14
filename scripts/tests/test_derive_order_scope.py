"""Tests for the derive_order_scope CLI."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import derive_order_scope

ROOT = Path(__file__).resolve().parents[2]
GD1 = ROOT / "fixtures" / "golden-design-1"


def test_writes_scope_and_quote_request(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    assert (
        derive_order_scope.main(
            ["--fixture", str(GD1), "--out-dir", str(out_dir)]
        )
        == 0
    )

    scope_path = out_dir / "order-scope.json"
    request_path = out_dir / "quote-request.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    expected = json.loads(
        (
            ROOT / "fixtures/contracts/valid/order-scope-golden-design-1.json"
        ).read_text(encoding="utf-8")
    )
    assert scope == expected
    assert request["quote_record"] is None
    assert request["record_class"] == "L3"


def test_derivation_failure_writes_nothing(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    fixture_dir = tmp_path / "broken-fixture"
    fixture_dir.mkdir()

    assert (
        derive_order_scope.main(
            ["--fixture", str(fixture_dir), "--out-dir", str(out_dir)]
        )
        == 1
    )
    assert not (out_dir / "order-scope.json").exists()
    assert not (out_dir / "quote-request.json").exists()
