# Model Quality Tuning Design

## Goal

Improve InvestmentAgent pick quality using the observed performance record through
June 18, 2026. The change should make the daily reports less willing to present
weak proof as investable conviction, reduce underperforming short-term signal
weights, and improve valuation coverage where FinImpulse lacks direct multiples.

The agent should remain a research triage system, not a buy/sell recommender.

## Current Evidence

The published performance scorecard shows:

- Trading ideas have positive raw average returns, but weak benchmark-adjusted
  returns.
- Generic trading and high-turnover signals have not added enough value.
- First North, small-cap, and live-price-backed signals have been more useful.
- True long-term research candidates have too little sample size to judge.
- Speculative monitors and insufficient-evidence rows are negative so far.
- Missing valuation data is a repeated proof gap and performance drag.
- Global AI reports receive quality, growth, and margin data from FinImpulse,
  but no direct valuation support.

## Scope

In scope:

- Tighten long-term candidate selection and presentation.
- Keep speculative monitors visible, but stop letting them read like primary
  investment ideas.
- Tune down underperforming generic trading signals.
- Preserve useful small-cap and First North discovery signals.
- Add explicit Yahoo-style valuation fallback for symbols where FinImpulse
  lacks valuation support.
- Improve report source checks so valuation fallback coverage is visible.
- Add tests around scoring, gating, fallback valuation, and report wording.

Out of scope:

- Automatic portfolio sizing.
- Removing speculative monitor/audit sections completely.
- Adding global AI performance tracking.
- Changing the daily publishing schedule.
- Adding a paid data source beyond the current provider set.
- Replacing FinImpulse as the primary enrichment provider.

## Design

### Long-Term Selection

The long-term report should clearly separate true research candidates from
speculative monitors and audit rows.

The main long-term candidate section should require enough durable evidence to
justify research attention. A company should need either valuation support or a
stronger combination of profitability, growth, balance sheet, liquidity, and
business profile. Missing valuation should remain a visible blocker unless the
rest of the quality profile is unusually strong.

If the gate finds only a small number of real research candidates, the report
should say that plainly instead of filling the main section with speculative
names. Speculative monitors should remain below the primary section as a
separate watch/audit list.

### Signal Tuning

Trading scoring should become more selective:

- Reduce the boost from generic trading strategy adjustment.
- Reduce or remove standalone high-turnover benefit when it is not paired with
  price, quality, or discovery evidence.
- Preserve First North and small-market-cap discovery support, but keep them
  subordinate to proof quality.
- Keep live price availability as a confidence/data signal, not a thesis by
  itself.

The aim is to avoid over-ranking liquid but low-quality or hype-driven names
while still surfacing interesting small-cap situations.

### Valuation Fallback

FinImpulse remains the primary fundamentals provider because it works well for
many Nordic and profile-quality fields. When FinImpulse returns a company but no
valuation support, the enrichment path should try a Yahoo-style fallback for
valuation fields.

The fallback should:

- Support explicit global symbols for the Global AI report.
- Continue supporting Nordic suffix candidates for Nordic reports.
- Merge only missing valuation/proxy fields and related market-cap/liquidity
  data.
- Preserve FinImpulse business descriptions and evidence.
- Record source-check diagnostics for attempted, successful, and valuation-rich
  fallback lookups.

The report should still show valuation gaps when both providers fail.

### Global AI Report

The Global AI report should remain separate from Nordic ideas. It should benefit
from fallback valuation when available, but should not be performance-tracked in
this change.

If valuation remains unavailable, the report must continue to flag missing
valuation support in every affected row.

## Data Flow

1. Daily workflow creates live Nordic provider and FinImpulse enrichment.
2. Enrichment attempts FinImpulse first.
3. If FinImpulse returns no valuation support, enrichment attempts Yahoo-style
   valuation fallback.
4. Missing fields are merged into the existing `FinancialSnapshot`.
5. Watchlist scoring and long-term gate evaluate the enriched research.
6. Renderer groups long-term rows by gate tier and makes weak sections explicit.
7. Performance update continues to track trading and long-term Nordic reports.

For Global AI:

1. Curated AI universe provides explicit provider symbols.
2. FinImpulse fetches fundamentals by symbol.
3. Yahoo-style fallback fetches valuation by explicit symbol when needed.
4. Global AI scoring uses valuation, quality, growth, relevance, and risk.

## Error Handling

- If FinImpulse fails entirely, existing provider error behavior remains.
- If valuation fallback fails for one symbol, the report continues with the
  FinImpulse fields and visible missing-valuation warning.
- Fallback source checks should report partial coverage rather than failing the
  full report.
- If both providers return no usable fundamentals, the row remains thin-data or
  monitor/audit quality instead of being promoted.

## Testing

Tests should cover:

- Yahoo-style provider can fetch explicit global symbols.
- Enrichment calls fallback only when valuation support is missing.
- Fallback valuation fields merge without overwriting FinImpulse descriptions.
- Long-term ranking no longer promotes speculative monitors as primary ideas.
- Trading score weight changes reduce generic/high-turnover dominance.
- Global AI report includes valuation when fallback provides it.
- Source checks expose fallback valuation coverage.
- Full CLI and daily workflow behavior remains intact.

## Rollout

Implement as a focused scoring/enrichment pass. After a few trading days, review:

- Whether long-term reports contain fewer speculative names.
- Whether valuation coverage improves for Global AI and Nordic reports.
- Whether 1d/5d trading excess returns improve after reducing weak signals.
- Whether First North discovery remains visible without overwhelming quality.
