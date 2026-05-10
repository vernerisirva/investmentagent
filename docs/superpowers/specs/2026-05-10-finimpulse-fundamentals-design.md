# Finimpulse Fundamentals Design

## Goal

Add Finimpulse fundamentals enrichment to InvestmentAgent so the existing Finimpulse API token can improve live Sweden/Finland watchlists. Finimpulse should become the preferred keyed fundamentals source because the token is available and the API probe confirmed Nordic symbols such as `KAR.ST` and `GOFORE.HE`.

## Scope

In scope:

- Add a `FinimpulseFundamentalsProvider` alongside the existing Yahoo-style and Finnhub providers.
- Read the token from `FINIMPULSE_API_KEY`.
- Add explicit CLI support for `--fundamentals finimpulse`.
- Make `--fundamentals auto` prefer Finimpulse when `FINIMPULSE_API_KEY` exists, then Finnhub when `FINNHUB_API_KEY` exists, then the no-key free fallback.
- Use the Finimpulse `/v1/search` endpoint first because it returns symbol identity, market value, margins, debt/equity, revenue growth, one-year return, liquidity, sector, and industry in one response.
- Keep Nasdaq Nordic as the listing universe and live-market source.
- Keep the existing enrichment budget so keyed calls are spent on preliminary top candidates.
- Ensure tokens are never written to evidence URLs, source checks, reports, logs, tests, or exceptions.
- Update local env guidance to use `FINIMPULSE_API_KEY`.

Out of scope:

- Removing Finnhub support.
- Building a local cache.
- Calling every Finimpulse financial statement endpoint in the first version.
- Replacing Nasdaq Nordic listing discovery.
- Automated buy/sell recommendations.
- Committing `.env` or any real token.

## Architecture

The provider should reuse the same `FundamentalsSnapshot` return model used by Yahoo and Finnhub. `EnrichedResearchProvider` should stay source-agnostic, so scoring and rendering continue to work without Finimpulse-specific branches.

The live watchlist flow remains:

1. Nasdaq Nordic loads SE/FI public listings and live market signals.
2. The report builder scores preliminary live research.
3. The enrichment wrapper chooses the preliminary top candidates within the budget.
4. Finimpulse receives one search request per selected company.
5. Returned fields are merged into missing `Company` and `FinancialSnapshot` fields.
6. The watchlist is rescored and rendered.

This keeps costs and latency bounded while improving the data quality of the most interesting names.

## Finimpulse Source Behavior

Finimpulse uses Bearer authentication:

```text
Authorization: Bearer <API_TOKEN>
```

The first version should call:

```text
POST https://api.finimpulse.com/v1/search
```

with a JSON body like:

```json
{
  "symbols": ["KAR.ST"],
  "quote_types": ["stock"],
  "limit": 1
}
```

Ticker candidates should mirror the existing Nordic suffix logic:

- Sweden: `.ST`
- Finland: `.HE`
- Tickers with spaces should try normalized and compact forms, such as `BEAMMW-B.ST` and `BEAMMWB.ST`.

If no matching item is returned, enrichment should leave the company unchanged.

## Data Mapping

Map Finimpulse fields conservatively:

- `amount` plus `currency` -> `Company.market_cap_eur_m` when the currency is supported by the existing FX table.
- `sector` -> `Company.sector` when the base company lacks sector.
- `regular_market_price` and `currency` should not override Nasdaq live price, because Nasdaq is the base live source.
- `one_year_return` -> `FinancialSnapshot.one_year_return_pct` only if the base field is missing.
- `fifty_two_week_high_change_percent` -> `FinancialSnapshot.distance_from_52w_high_pct` only if the base field is missing.
- `regular_market_price * average_daily_volume_10_day` converted to EUR -> `FinancialSnapshot.average_daily_value_eur` when possible.
- `revenue_growth` -> `FinancialSnapshot.revenue_growth_pct`, converting fraction values to percentages.
- `net_margin` or `free_cash_flow_margin` -> `FinancialSnapshot.operating_margin_pct`, converting fraction values to percentages.
- `debt_to_equity` -> `FinancialSnapshot.debt_to_equity`. The live probe showed ratio-like values, so do not divide by 100 unless a future fixture proves Finimpulse returns percentage values for this field.

Do not map P/E or P/B from `/v1/search` unless documented fields are available in fixture responses. Those can come later from `/v1/financials/valuation_measures` if needed.

## CLI Behavior

Extend fundamentals modes to:

```text
auto|off|free|finnhub|finimpulse
```

For `--provider live`:

- `auto`: use Finimpulse if `FINIMPULSE_API_KEY` is present, else Finnhub if `FINNHUB_API_KEY` is present, else `free`.
- `finimpulse`: require `FINIMPULSE_API_KEY`; fail early when missing or blank.
- `finnhub`: keep existing Finnhub behavior.
- `free`: keep the Yahoo-style no-key provider.
- `off`: skip fundamentals enrichment.

For fixture provider, effective fundamentals remain `off`.

Saved report metadata should record the effective mode, including `finimpulse`.

## Local Environment

The local `.env` file should use:

```bash
FINIMPULSE_API_KEY=...
```

The existing `.gitignore` protection for `.env` should remain. The CLI may continue requiring the user to source `.env` before running, unless implementation adds a small safe `.env` loader.

## Security

The provider must:

- Send the token only in the Authorization header.
- Redact `FINIMPULSE_API_KEY` from captured exception messages.
- Avoid storing raw request headers.
- Use documentation URLs for evidence.
- Keep source checks token-safe.
- Keep tests free of real tokens.

## Error Handling

Finimpulse enrichment is best-effort unless the user explicitly selects `--fundamentals finimpulse` without a token.

Runtime behavior:

- Missing or blank explicit token raises a clear CLI error.
- Per-company failures leave research unchanged.
- Empty search results return no snapshot.
- Source checks summarize attempts and successes.
- Network, parse, authorization, and rate-limit errors become warnings and must be token-safe.

## Testing

Tests should cover:

- Finimpulse symbol candidates.
- Parsing the `/v1/search` response fixture into `FundamentalsSnapshot`.
- Market cap conversion from SEK/EUR to EUR millions.
- Ratio-to-percent mapping for revenue growth and margins.
- Average daily value calculation.
- No token leakage in evidence or source checks.
- `auto` chooses Finimpulse before Finnhub when both keys exist.
- Explicit `finimpulse` rejects missing or blank keys.
- Saved metadata records `finimpulse`.
- Existing Finnhub and free modes still work.
- Full test suite remains deterministic without live internet.

## References

- Finimpulse authentication: https://developers.finimpulse.com/authentication/
- Finimpulse search endpoint: https://developers.finimpulse.com/v1/search/
- Finimpulse profile endpoint: https://developers.finimpulse.com/v1/profile/
- Finimpulse financials general endpoint: https://developers.finimpulse.com/v1/financials/general/
