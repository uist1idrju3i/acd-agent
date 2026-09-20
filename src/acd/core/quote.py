"""Compatibility re-export.

The implementation lives in ``acd.core.manufacturing.quote``.
"""

from acd.core.manufacturing.quote import (
    FixtureQuoteProvider,
    QuoteFeeSet,
    QuoteProvider,
    QuoteReadError,
    load_quote,
    quote_provider_from_config,
    read_quote,
)

__all__ = [
    "FixtureQuoteProvider",
    "QuoteFeeSet",
    "QuoteProvider",
    "QuoteReadError",
    "load_quote",
    "quote_provider_from_config",
    "read_quote",
]
