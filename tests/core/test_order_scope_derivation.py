"""Order scope derivation from fixture inputs is deterministic and fail-closed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from acd.core.manufacturing.order_scope_derivation import (
    OrderScopeDerivationError,
    build_quote_request,
    derive_order_scope,
)

ROOT = Path(__file__).resolve().parents[2]
GD1 = ROOT / "fixtures" / "golden-design-1"
GOLDEN_SCOPE = (
    ROOT / "fixtures" / "contracts" / "valid" / "order-scope-golden-design-1.json"
)


def _fixture_copy(tmp_path: Path) -> Path:
    target = tmp_path / "fixture"
    shutil.copytree(GD1, target)
    return target


def _write_terms(fixture_dir: Path, **overrides: object) -> None:
    terms = json.loads(
        (fixture_dir / "order-terms.json").read_text(encoding="utf-8")
    )
    terms.update(overrides)
    (fixture_dir / "order-terms.json").write_text(
        json.dumps(terms, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_enclosure_nodes(fixture_dir: Path) -> None:
    graph_path = fixture_dir / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"] = [
        node for node in graph["nodes"] if node["kind"] != "mechanical.enclosure"
    ]
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_gd1_derivation_matches_contract_fixture() -> None:
    scope = derive_order_scope(GD1)
    expected = json.loads(GOLDEN_SCOPE.read_text(encoding="utf-8"))

    assert scope.model_dump(mode="json") == expected


def test_derivation_is_deterministic() -> None:
    assert derive_order_scope(GD1) == derive_order_scope(GD1)


def test_enclosure_absent_requires_exclusion_reason(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    _remove_enclosure_nodes(fixture_dir)

    with pytest.raises(OrderScopeDerivationError):
        derive_order_scope(fixture_dir)


def test_enclosure_absent_with_reason_yields_excluded_scope(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    _remove_enclosure_nodes(fixture_dir)
    _write_terms(
        fixture_dir, mechanical_exclusion_reason="fixture has no enclosure"
    )

    scope = derive_order_scope(fixture_dir)

    assert scope.mechanical_treatment == "excluded"
    assert scope.mechanical_item_ids is None
    assert "mechanical" not in scope.required_categories


def test_itemized_shipping_adds_required_category(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    _write_terms(fixture_dir, shipping_treatment="itemized")

    scope = derive_order_scope(fixture_dir)

    assert "shipping" in scope.required_categories


def test_missing_order_terms_fails_closed(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    (fixture_dir / "order-terms.json").unlink()

    with pytest.raises(OrderScopeDerivationError):
        derive_order_scope(fixture_dir)


def test_unknown_fab_profile_fails_closed(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    graph_path = fixture_dir / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    for node in graph["nodes"]:
        if node["kind"] == "fab.order_intent":
            node["attrs"]["fab_profile"] = "nonexistent-profile"
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OrderScopeDerivationError):
        derive_order_scope(fixture_dir)


def test_registry_default_supplier_when_not_declared(tmp_path: Path) -> None:
    fixture_dir = _fixture_copy(tmp_path)
    _write_terms(fixture_dir, allowed_suppliers=None)

    scope = derive_order_scope(fixture_dir)

    assert scope.allowed_suppliers == ["JLCPCB"]


def test_quote_request_never_synthesizes_quote_record() -> None:
    scope = derive_order_scope(GD1)
    request = build_quote_request(scope, fixture_dir=Path("out"))

    assert request["quote_record"] is None
    assert request["pass_evidence"] is False
    assert "fetch_quote.py" in str(request["next_step"])
    for key in request:
        assert "amount" not in key
