# Long-Term Accounting And Valuation Diagnostics Design

## Goal

Make InvestmentAgent's long-term performance reporting honest about what the
agent actually recommended. High-conviction and fundamental watchlist companies
should count as long-term research candidates. Speculative monitors should stay
visible and tracked, but should not pollute the headline long-term scorecard.

The change should also improve FinImpulse valuation diagnostics so the gate has
better inputs before it rejects otherwise interesting First North companies for
missing valuation data.

## Current Context

The stricter long-term gate is working as a guardrail. Through the latest
published report on 2026-06-05, no company passed as a high-conviction or
fundamental watchlist candidate. The report correctly says no high-conviction
ideas passed the gate and places the daily names under speculative or
insufficient-evidence sections.

The performance scorecard still aggregates every long-term report row into the
headline `Long-Term Investment Ideas` result. That makes the headline return
hard to interpret because it mixes real research candidates with names the gate
already marked as speculative or insufficient.

The latest reports also show persistent `Missing valuation data` proof gaps.
The code already supports valuation proxies, but FinImpulse parsing is not
feeding enough direct or proxy valuation fields into the model.

## Scope

In scope:

- Split long-term performance reporting by gate tier.
- Treat `High-conviction candidate` and `Fundamental watchlist` as the headline
  long-term research candidate universe.
- Keep `Speculative monitor` outcomes tracked in a separate monitor scorecard.
- Keep `Insufficient evidence` outcomes tracked as an audit bucket.
- Preserve all picks in the ledger so historical review remains possible.
- Improve FinImpulse parsing for available valuation-related fields.
- Add source-check or report diagnostics that show how many enriched names had
  valuation support.
- Add tests for performance accounting, FinImpulse field parsing, and report
  diagnostics.

Out of scope:

- Candidate memory across days.
- New paid data providers.
- EODHD support.
- Automatic weight optimization.
- Buy/sell recommendations.
- Portfolio sizing.
- Changing the daily workflow schedule.

## Design Principles

The public headline should not treat every surfaced row as an investment idea.
If the gate says a name is speculative, the scorecard should say so too.

Speculative monitors still matter. They can teach us whether discovery signals
are useful, and they can become future research candidates if better evidence
appears. They should be tracked, just not presented as the primary long-term
model result.

Missing valuation data should be specific. The agent should distinguish between
"FinImpulse had no useful valuation fields" and "the provider returned fields
that we failed to parse."

## Performance Accounting

The performance ledger should continue to store every long-term report row.
Each pick should retain its `long_term_gate` payload, including tier, blockers,
durable anchor count, severe proof gap count, and valuation details.

The rendered performance page should split long-term outcomes into:

- `Long-Term Research Candidates`: high-conviction and fundamental watchlist
  names only.
- `Speculative Monitors`: speculative monitor names.
- `Insufficient Evidence Audit`: insufficient-evidence names.

The existing `Trading Ideas` section remains unchanged.

The headline long-term scorecard should use only the research-candidate subset.
If there are no completed research-candidate observations yet, it should say
that clearly instead of showing monitor results as long-term candidate results.

The monitor and audit sections should use the same horizon table format where
possible, but their headings and labels must make clear that they are not
investment-candidate performance.

## Report Behavior

The daily long-term report can keep showing speculative monitors and
insufficient-evidence rows, because they are useful for transparency. However,
when no research candidates pass the gate, the report should emphasize:

- No research candidates passed today.
- The rows below are monitors or audit rows.
- Missing valuation support is a blocker when relevant.

This keeps the report useful without implying that speculative rows are
recommended long-term ideas.

## FinImpulse Valuation Diagnostics

FinImpulse search and profile payload parsing should capture any useful
valuation fields already present in the API response.

Direct metrics to parse when available:

- P/E or trailing P/E into `pe_ratio`.
- Price/book into `price_to_book`.
- EV/EBIT or EV/EBITDA into `ev_to_ebit` when the field is truly EBIT-like, or
  into a clearly named diagnostic if it is EBITDA-only.

Proxy inputs to parse when available:

- Revenue into `revenue_eur_m`.
- Book value or shareholders' equity into `book_value_eur_m`.
- Net income into `net_income_eur_m`.
- Existing market cap into `Company.market_cap_eur_m`.

The parser should accept several likely field names because vendor payloads
often vary by endpoint. It should avoid unsafe assumptions: if the unit or
currency cannot be determined, leave the field missing and record diagnostics
instead of inventing a conversion.

## Valuation Coverage Diagnostics

Report metadata or source checks should expose valuation coverage for enriched
companies. Useful diagnostics:

- Enriched companies with any valuation support.
- Enriched companies with direct valuation metrics.
- Enriched companies with proxy valuation inputs.
- Enriched companies still missing valuation support.

The detail can be compact, for example:

`9/10 FinImpulse lookups parsed; valuation support 2/9; proxy inputs 1/9`

This gives us a way to judge whether FinImpulse is the limiting factor or our
parser is.

## Error Handling

Provider failures should keep the current behavior: report source checks should
show partial or failed enrichment, and the workflow should fail only when the
configured provider is unavailable in a way that prevents report generation.

Unknown valuation fields should be ignored safely. Missing fields should not
crash parsing or scoring.

Performance rendering should handle older ledger rows that do not have
`long_term_gate` data. Those rows can remain under the existing historical
long-term section or be labeled as legacy long-term rows.

## Testing

Tests should cover:

- Long-term headline scorecard includes only high-conviction and fundamental
  watchlist picks.
- Speculative monitor outcomes appear in a separate monitor section.
- Insufficient evidence outcomes appear in a separate audit section.
- Older ledger rows without gate payloads still render.
- FinImpulse parser extracts direct valuation metrics when fields are present.
- FinImpulse parser extracts proxy inputs when fields are present.
- FinImpulse source checks include valuation coverage diagnostics.
- Daily workflow tests still pass.

## Rollout

Implement behind existing `performance update` and long-term report behavior.
No new CLI flag is needed.

After implementation, regenerate the scorecard from the current ledger and
verify that the headline long-term candidate section no longer reports
speculative monitor outcomes as candidate returns.
