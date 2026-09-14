"""Deterministic OrderScope derivation from design inputs and declared terms."""

from __future__ import annotations

from pathlib import Path

from acd.core.fab import extract_fab_intent, load_fab_profile_registry
from acd.schema import (
    DesignGraph,
    OrderScope,
    OrderTermsDeclaration,
    QuoteCategory,
    RationaleDocument,
)


class OrderScopeDerivationError(Exception):
    """Fail-closed error raised when an order scope cannot be derived."""


MECHANICAL_ENCLOSURE_ITEM_ID = "mechanical-enclosure"


def _load_graph(fixture_dir: Path) -> DesignGraph:
    path = fixture_dir / "graph.json"
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OrderScopeDerivationError(
            f"graph is invalid or unreadable: {path}: {exc}"
        ) from exc


def _load_rationale_revision(fixture_dir: Path) -> str:
    path = fixture_dir / "rationale.json"
    try:
        document = RationaleDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise OrderScopeDerivationError(
            f"rationale is invalid or unreadable: {path}: {exc}"
        ) from exc
    return document.revision


def _load_terms(fixture_dir: Path) -> OrderTermsDeclaration:
    path = fixture_dir / "order-terms.json"
    try:
        return OrderTermsDeclaration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise OrderScopeDerivationError(
            f"order terms are invalid or unreadable: {path}: {exc}"
        ) from exc


def derive_order_scope(
    fixture_dir: Path, *, registry_path: Path | None = None
) -> OrderScope:
    """Derive a validated OrderScope; fail closed on any missing input."""
    fixture_dir = Path(fixture_dir)
    graph = _load_graph(fixture_dir)
    try:
        intent, _ = extract_fab_intent(graph)
    except ValueError as exc:
        raise OrderScopeDerivationError(f"fab intent cannot be extracted: {exc}") from exc
    fab_profile_id = intent.fab_profile

    try:
        registry = load_fab_profile_registry(registry_path)
    except ValueError as exc:
        raise OrderScopeDerivationError(
            f"fab profile registry is invalid: {exc}"
        ) from exc
    entries = [
        entry
        for entry in registry.document.profiles
        if entry.profile_id == fab_profile_id
    ]
    if len(entries) != 1:
        raise OrderScopeDerivationError(f"unknown fab profile id: {fab_profile_id}")
    fab_name = entries[0].fab

    target_revision = _load_rationale_revision(fixture_dir)
    terms = _load_terms(fixture_dir)

    has_enclosure = any(node.kind == "mechanical.enclosure" for node in graph.nodes)
    categories: list[QuoteCategory] = ["board", "components", "assembly"]
    mechanical_item_ids: list[str] | None = None
    exclusion_reason: str | None = terms.mechanical_exclusion_reason
    if has_enclosure:
        mechanical_treatment = "included"
        mechanical_item_ids = [MECHANICAL_ENCLOSURE_ITEM_ID]
        categories.append("mechanical")
        exclusion_reason = None
    else:
        mechanical_treatment = "excluded"
        if exclusion_reason is None:
            raise OrderScopeDerivationError(
                "no mechanical enclosure node; order terms must declare "
                "mechanical_exclusion_reason"
            )
    if terms.shipping_treatment == "itemized":
        categories.append("shipping")
    if terms.tax_treatment == "itemized":
        categories.append("tax")

    try:
        return OrderScope.model_validate(
            {
                "scope_id": f"{graph.graph_id}-order-scope",
                "target_revision": target_revision,
                "fab_profile_id": fab_profile_id,
                "counterparty_type": "fab",
                "allowed_suppliers": terms.allowed_suppliers or [fab_name],
                "required_categories": categories,
                "shipping_treatment": terms.shipping_treatment,
                "tax_treatment": terms.tax_treatment,
                "mechanical_treatment": mechanical_treatment,
                "mechanical_item_ids": mechanical_item_ids,
                "mechanical_exclusion_reason": exclusion_reason,
                "currency": terms.currency,
                "minor_unit_digits": terms.minor_unit_digits,
            }
        )
    except ValueError as exc:
        raise OrderScopeDerivationError(
            f"derived order scope fails validation: {exc}"
        ) from exc


def build_quote_request(scope: OrderScope, *, fixture_dir: Path) -> dict[str, object]:
    """Declare that a real QuoteRecord must be fetched; never synthesize one."""
    out_dir = Path(fixture_dir) / "order-scope-out"
    return {
        "schema_version": "0.1",
        "record_class": "L3",
        "pass_evidence": False,
        "quote_record": None,
        "reason": (
            "QuoteRecord requires supplier quote values; "
            "none are derived from design inputs"
        ),
        "target_revision": scope.target_revision,
        "fab_profile_id": scope.fab_profile_id,
        "required_categories": list(scope.required_categories),
        "allowed_suppliers": list(scope.allowed_suppliers),
        "currency": scope.currency,
        "minor_unit_digits": scope.minor_unit_digits,
        "next_step": (
            "uv run python scripts/fetch_quote.py --config <quote provider config> "
            f"--target-revision {scope.target_revision} "
            "--evaluated-at <UTC timestamp> "
            f"--output {out_dir}/quote-record.json"
        ),
    }
