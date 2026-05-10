# Finnhub Fundamentals Design

## Goal

Improve InvestmentAgent's live Sweden/Finland watchlists with keyed Finnhub fundamentals when `FINNHUB_API_KEY` is available. The agent should keep Nasdaq Nordic as the listing and live-market source, then use Finnhub to add better valuation and financial context for the highest-ranked candidates.

## Scope

In scope:

- Add a `FinnhubFundamentalsProvider` alongside the existing Yahoo-style free provider.
- Read the API key only from the `FINNHUB_API_KEY` environment variable.
- Add explicit CLI support for `--fundamentals finnhub`.
- Make `--fundamentals auto` prefer Finnhub when `FINNHUB_API_KEY` exists, otherwise keep the current free fallback.
- Preserve `--fundamentals free` as the no-key Yahoo-style fallback.
- Use Finnhub company profile and basic financials endpoints for market cap, valuation ratios, profitability, growth, and leverage when available.
- Keep the existing enrichment budget so live watchlists only call Finnhub for preliminary top candidates.
- Ensure tokens are never written to evidence URLs, reports, source checks, tests, or logs.
- Add deterministic tests with fixture payloads.

Out of scope:

- Storing secrets in files or committing local configuration.
- Replacing Nasdaq Nordic listing discovery.
- Paid-only Finnhub datasets beyond profile and basic financials.
- Full annual-report parsing.
- Automated buy/sell recommendations.
- A local fundamentals database or cache.

## Architecture

The current enrichment architecture already has the right boundary: `EnrichedResearchProvider` wraps a base research provider and calls a fundamentals provider for selected companies. Finnhub should use that same interface so the scoring and report rendering layers do not need source-specific branches.

The live watchlist flow should be:

1. Load SE/FI listings and live market signals from Nasdaq Nordic.
2. Score preliminary live research without fundamentals.
3. Select the highest preliminary candidates within the enrichment budget.
4. Fetch Finnhub fundamentals for those candidates when enabled.
5. Merge only missing financial fields into the research snapshot.
6. Re-score and render the final watchlist.

This preserves the recent budget fix: Finnhub calls are spent on candidates that already look interesting, not on arbitrary listing order.

## Finnhub Source Behavior

The provider should use official Finnhub REST endpoints:

- Company Profile 2 for company metadata and market capitalization.
- Basic Financials with `metric=all` for ratios and financial metrics.
- Stock symbol lookup may be used later if simple suffix candidates are insufficient.

Ticker candidates should be conservative:

- Sweden: try Nasdaq ticker normalized with `.ST`.
- Finland: try Nasdaq ticker normalized with `.HE`.
- Tickers with spaces, share classes, or suffix-like parts should try both normalized and compact forms.
- If all candidates fail or return no meaningful data, leave the company unchanged.

The provider should avoid false precision. It should only map fields that are present and parseable. Market cap should only be converted to EUR when the source currency is supported by the existing FX table, or left empty when conversion is unsafe.

## CLI Behavior

Extend fundamentals modes to:

```text
auto|off|free|finnhub
```

For `--provider live`:

- `auto`: use Finnhub if `FINNHUB_API_KEY` is present, otherwise use `free`.
- `finnhub`: require `FINNHUB_API_KEY`; fail early with a clear CLI error if missing.
- `free`: use the existing Yahoo-style provider.
- `off`: do not enrich fundamentals.

For non-live providers, fundamentals remain effectively `off` so fixture runs stay deterministic.

Saved report metadata should record the effective mode: `finnhub`, `free`, or `off`.

## Security

The API key must stay out of all project artifacts. The provider should:

- Read the key from `FINNHUB_API_KEY` at runtime.
- Build request URLs internally with the token.
- Store evidence URLs without the token, such as endpoint documentation or a redacted API URL.
- Never include raw request URLs containing `token=` in exceptions, source checks, snapshots, or tests.
- Avoid `.env` generation in this change.

Users should set the key in their shell or automation environment:

```bash
export FINNHUB_API_KEY='...'
```

## Data Mapping

Map Finnhub fields into the existing model where available:

- `Company.market_cap_eur_m`
- `FinancialSnapshot.pe_ratio`
- `FinancialSnapshot.price_to_book`
- `FinancialSnapshot.revenue_growth_pct`
- `FinancialSnapshot.operating_margin_pct`
- `FinancialSnapshot.debt_to_equity`

Keep Nasdaq values for live price, currency, turnover, intraday momentum, and listing segment. Preserve existing curated or live values when they already exist, following the current merge rules.

If Finnhub returns at least one meaningful valuation, profitability, leverage, or market-cap field, upgrade `thin` research to `partial`. Keep `good` reserved for future richer audited statement coverage.

## Error Handling

Finnhub enrichment is optional and should not break a watchlist unless the user explicitly asked for `--fundamentals finnhub` without a key.

Runtime failures should behave like the current free fundamentals provider:

- Per-company lookup failures leave research unchanged.
- Source checks summarize attempts and successes.
- Network, rate-limit, parse, and empty-response failures become warnings, not watchlist crashes.
- The source check detail should be useful but token-safe.

## Testing

Tests should cover:

- CLI accepts `--fundamentals finnhub`.
- `auto` chooses Finnhub when `FINNHUB_API_KEY` is present.
- `auto` falls back to `free` when the key is absent.
- Explicit `finnhub` fails early when the key is missing.
- Finnhub payload parsing maps supported fields correctly.
- Missing or malformed payloads return no snapshot.
- Token-bearing request URLs are not exposed in evidence or source checks.
- The enrichment budget still limits Finnhub calls to preliminary top candidates.
- Saved report metadata records `finnhub` when that is the effective mode.
- Full test suite remains deterministic without live internet.

## References

- Finnhub Company Profile 2: https://finnhub.io/docs/api/company-profile2
- Finnhub Basic Financials: https://finnhub.io/docs/api/company-basic-financials
- Finnhub Stock Symbols: https://finnhub.io/docs/api/stock-symbols
