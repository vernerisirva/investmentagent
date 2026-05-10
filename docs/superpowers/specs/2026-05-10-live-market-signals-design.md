# Live Market Signals Design

## Goal

Improve `investmentagent watchlist --provider live` ranking by using market data already returned by Nasdaq's free Nordic screener API while keeping live research clearly marked as thin triage data.

## Scope

In scope:

- Parse live `lastSalePrice`, `percentageChange`, `turnover`, and `volume` fields from Nasdaq screener rows.
- Store those parsed fields in the existing `FinancialSnapshot` shape where a matching field exists.
- Add lightweight catalysts and risks derived from live market signals.
- Keep live provider `data_quality` as `thin`.
- Preserve fixture provider behavior and existing scoring semantics for fixture-backed reports.

Out of scope:

- Full valuation from P/E, P/B, EV/EBIT, margins, debt, or market cap.
- Paid data sources.
- AI-written investment theses.
- Currency conversion. Turnover remains in listing currency and is used as a relative liquidity signal only.

## Data Mapping

Nasdaq screener row fields map as follows:

- `lastSalePrice` -> `FinancialSnapshot.price`
- `currency` -> `FinancialSnapshot.currency`
- `percentageChange` -> `FinancialSnapshot.one_year_return_pct` is not used, because the API field is an intraday change, not a one-year return.
- `turnover` -> a live-market liquidity signal for risk/catalyst text.
- `volume` -> a live-market liquidity signal for risk text.

Because the current model has no dedicated intraday change or raw turnover fields, live signal text should be stored in `CompanyResearch.catalysts` and `CompanyResearch.risks`. This avoids misusing long-term financial fields.

## Signal Rules

For each live company:

- Add `Live price available from Nasdaq Nordic` when a valid price is parsed.
- Add `Positive intraday momentum` when percentage change is at least `+5%`.
- Add `Sharp intraday selloff` as a risk when percentage change is at most `-5%`.
- Add `Low live turnover` as a risk when turnover is present and below `100000`.
- Add `Missing live turnover` as a risk when both turnover and volume are absent.
- Preserve `Sparse live-source data` as a baseline risk.

## Error Handling

Malformed numeric fields should not fail the provider. They should be ignored for price/signal purposes, and the company should still appear if name, symbol, country, and segment can be inferred.

## Testing

Tests should cover:

- Parsing Nasdaq numeric fields with thousands separators and percent signs.
- Live research includes price/currency and signal-derived catalysts/risks.
- Malformed numeric fields do not break parsing.
- The full suite remains deterministic and does not require public internet.
