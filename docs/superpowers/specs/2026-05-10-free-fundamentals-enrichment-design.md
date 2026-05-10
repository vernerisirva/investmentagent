# Free Fundamentals Enrichment Design

## Goal

Improve InvestmentAgent's long-term and balanced watchlists by enriching live Nasdaq Nordic listings with free fundamental data when available. The agent should use real valuation and financial signals instead of relying mostly on intraday price action.

## Scope

In scope:

- Add a fundamentals enrichment layer separate from the existing listing and live-price provider.
- Start with a free Yahoo-style fundamentals adapter because it can work without user setup.
- Keep Finnhub as a later optional adapter that requires `FINNHUB_API_KEY`.
- Enrich existing model fields: `Company.market_cap_eur_m` plus `FinancialSnapshot` P/E, price/book, revenue growth, operating margin, debt/equity, net cash/debt, and average traded value when available.
- Add evidence for every successful fundamentals source.
- Mark enriched data quality as `partial` when at least one meaningful fundamentals field is found.
- Keep live Nasdaq Nordic data as the source of listing universe, exchange, segment, live price, turnover, and intraday momentum.
- Make `long-term` and `balanced` benefit from fundamentals; keep `trading` mostly driven by live momentum and liquidity.

Out of scope:

- Paid data sources.
- Broker recommendations or target prices.
- Automated buy/sell decisions.
- Full PDF annual report parsing.
- Building a local financial statement database.
- Replacing Nasdaq Nordic as the listing source.

## Architecture

Add a focused `FundamentalsProvider` interface with a method that accepts a `Company` and returns optional fundamentals data plus evidence. This keeps listing discovery, live market data, and fundamentals enrichment as separate responsibilities.

The live watchlist flow should become:

1. Load public SE/FI listings from Nasdaq Nordic.
2. Build company-specific live research with price, turnover, catalysts, and risks.
3. Attempt fundamentals enrichment for each company.
4. Merge enriched fields into `FinancialSnapshot`.
5. Re-score using the existing scoring engine and strategy adjustments.

Deep dives should use the same enriched research path where possible, so valuation sections can show actual P/E, P/B, profitability, and balance-sheet information when available.

## Source Strategy

The first adapter should be a free Yahoo-style provider. It should be treated as best-effort because the source is unofficial and may miss Nordic small caps or First North tickers.

Ticker mapping should be conservative:

- Swedish listings try suffixes such as `.ST`.
- Finnish listings try suffixes such as `.HE`.
- First North tickers with spaces or share classes should be normalized carefully, but failed lookups should not break the watchlist.
- If multiple candidate symbols return data, prefer the one whose currency, exchange, or name best matches the Nasdaq listing.

Finnhub should not be required for v1 of this enrichment. The architecture should make it easy to add later as an optional provider when `FINNHUB_API_KEY` is present.

## Data Quality

Fundamentals enrichment must never invent missing values. Each field should remain `None` unless the source provides a parseable value.

Research quality rules:

- Keep `thin` when only Nasdaq live data is available.
- Upgrade to `partial` when at least one valuation, profitability, balance-sheet, or market-cap field is found.
- Keep `good` reserved for future richer audited statement coverage.

Evidence should identify the fundamentals source and the symbol used for lookup. If a lookup fails, do not add noisy per-company evidence; source checks can summarize availability.

## Ranking Behavior

`long-term` should benefit most from enriched fundamentals:

- Low P/E, low P/B, net cash, positive operating margin, and reasonable debt should help.
- Negative operating margin, very high valuation, high debt, and weak liquidity should hurt.
- Intraday momentum should remain secondary.

`balanced` should use fundamentals as a quality filter and boost, while still considering live liquidity and recent price action.

`trading` should remain mostly unchanged. It may display fundamentals if available, but it should not become a valuation strategy.

## CLI Behavior

Keep the current CLI simple. The default live command should attempt free fundamentals enrichment automatically when `--provider live` is used:

```text
investmentagent watchlist --provider live --strategy long-term
```

Add an explicit escape hatch:

```text
--fundamentals off|free
```

Default should be `free` for live provider and `off` for fixture provider. `--fundamentals off` should preserve today's live behavior for troubleshooting or faster runs.

## Error Handling

Fundamentals lookups are best-effort:

- Network or parsing failures should not fail the whole watchlist.
- Per-company failures should leave existing live research unchanged.
- Source checks should report whether fundamentals enrichment was available, partially available, or failed.
- Tests should use fixture responses and not require the public internet.

## Testing

Tests should cover:

- Ticker suffix generation for Swedish and Finnish companies.
- Successful fundamentals parsing into existing `FinancialSnapshot` fields.
- Evidence added for successful enrichment.
- Data quality upgrades from `thin` to `partial` when fundamentals are found.
- Missing or malformed fundamentals leave research unchanged.
- `long-term` ranks an enriched value candidate above a pure intraday mover.
- `trading` remains mostly driven by live momentum and liquidity.
- CLI metadata records fundamentals mode when report saving is used.
- Full test suite remains deterministic without live internet.
