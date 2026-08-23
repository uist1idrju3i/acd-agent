from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.core.quote import QuoteReadError, quote_provider_from_config


def test_unknown_quote_provider_fails_closed() -> None:
    with pytest.raises(QuoteReadError, match="unknown"):
        quote_provider_from_config({"provider": "network"})


def test_fixture_quote_provider_reads_valid_fixture() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures/contracts/valid/quote.json"
    provider = quote_provider_from_config({"provider": "fixture", "path": str(fixture)})

    record = provider.fetch(
        configuration={"provider": "fixture", "path": str(fixture)},
        evaluated_at=datetime(2025, 1, 15, tzinfo=UTC),
        target_revision="r12",
    )

    assert record.quote_id == "quote-gd1-001"


def test_fixture_quote_provider_rejects_expired_quote(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures/contracts/valid/quote.json"
    quote = json.loads(fixture.read_text(encoding="utf-8"))
    quote["valid_until"] = "2026-01-01T00:00:00Z"
    path = tmp_path / "quote.json"
    path.write_text(json.dumps(quote), encoding="utf-8")
    provider = quote_provider_from_config({"provider": "fixture", "path": str(path)})

    with pytest.raises(QuoteReadError, match="expired"):
        provider.fetch(
            configuration={"provider": "fixture", "path": str(path)},
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
            target_revision="r12",
        )
