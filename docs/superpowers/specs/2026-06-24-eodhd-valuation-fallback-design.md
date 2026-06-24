# EODHD Valuation Fallback Design

## Purpose

Yahoo fundamentals is no longer a reliable unauthenticated valuation fallback: once TLS is fixed, its quote summary endpoint returns `401 Unauthorized`. The agent needs a fallback source that can actually provide direct valuation and proxy valuation fields so long-term and Global AI reports can distinguish real candidates from speculative monitors.

## Design

Keep FinImpulse as the primary fundamentals provider. Add an `EodhdFundamentalsProvider` that uses EODHD's v1.1 fundamentals endpoint when `EODHD_API_KEY` is configured. The provider will support explicit global symbols for Global AI and Nordic company lookups for daily watchlists, parse valuation fields from `Highlights` and `Valuation`, and expose source checks with parsed lookup counts and valuation coverage.

Provider order will be:

1. FinImpulse.
2. EODHD, when `EODHD_API_KEY` is present.
3. Yahoo, as a final diagnostic fallback.

When EODHD is not configured, scheduled runs remain functional and source checks make that visible. When configured, fallback enrichment should merge only missing fields into the FinImpulse snapshot so profile text and primary fields are preserved.

## Data Mapping

EODHD endpoint:

`https://eodhd.com/api/v1.1/fundamentals/{SYMBOL}?api_token={TOKEN}&fmt=json`

Fields:

- `General.Description` -> `business_description`
- `General.WebURL` -> `ir_url`
- `General.CurrencyCode` or fallback currency -> currency conversion
- `Highlights.MarketCapitalization` -> `market_cap_eur_m`
- `Highlights.PERatio` or `Valuation.TrailingPE` -> `pe_ratio`
- `Valuation.PriceBookMRQ` -> `price_to_book`
- `Highlights.RevenueTTM` -> `revenue_eur_m`
- `Highlights.BookValue` remains per-share data and is not used as book-value total.
- `Highlights.QuarterlyRevenueGrowthYOY` -> `revenue_growth_pct`
- `Highlights.OperatingMarginTTM` -> `operating_margin_pct`

## Testing

Add provider tests for:

- Explicit symbol URL construction and parsing.
- Nordic symbol candidate lookup.
- Source-check valuation coverage.
- CLI wiring for watchlist and Global AI.
- Global AI composite source checks still include FinImpulse, EODHD, Yahoo, and wrapper details.

## Acceptance Criteria

- `EodhdFundamentalsProvider` exists and parses direct valuation from fixture payloads.
- CLI uses FinImpulse plus EODHD plus Yahoo fallback when `EODHD_API_KEY` is present.
- CLI preserves FinImpulse plus Yahoo behavior when `EODHD_API_KEY` is absent.
- Global AI and watchlist reports show EODHD source checks when configured.
- Full pytest suite passes.
