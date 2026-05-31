# Long-Term Conviction Gate Design

## Goal

Improve the long-term report so it behaves like a selective research queue instead
of a forced daily top 10. The agent should be allowed to say that there are no
high-conviction long-term ideas today when the evidence is too thin.

The system should help answer: "Which First North or Nordic small-cap companies
are worth serious long-term manual research now?"

## Current Context

InvestmentAgent now has a long-term quality layer with buckets such as `Quality
small-cap candidate`, `Fundamental watchlist candidate`, `Speculative small-cap
monitor`, and `Insufficient evidence`.

The latest published data through 2026-05-29 shows that the new model is more
honest about uncertainty, but it still fills the report mostly with speculative
monitors. The long-term scorecard is positive in absolute terms, but the history
is still short and weak versus the equal-weight market benchmark. The improved
model only has a small number of completed short-horizon observations, so the
next change should improve selection quality rather than overfit to recent
returns.

The latest long-term report also shows a repeated proof gap: valuation data is
usually missing. Finimpulse still provides enough business, profitability,
growth, and balance-sheet data to be useful, but the agent should make better
use of available price, market cap, sales, book value, cash, debt, and earnings
fields before declaring valuation support missing.

## Scope

In scope:

- Add a stricter long-term conviction gate after scoring and before final report
  selection.
- Allow long-term reports to contain fewer than 10 high-conviction ideas.
- Keep lower-conviction companies visible as a separate monitor section when
  useful, without presenting them as top long-term picks.
- Add valuation proxy support from existing fields where possible.
- Make the report clearly distinguish high-conviction candidates, fundamental
  watchlist candidates, speculative monitors, and rejected/insufficient-evidence
  names.
- Add tests for gate behavior, valuation proxy calculation, report rendering,
  and workflow safety.

Out of scope:

- New paid data sources.
- New EODHD or alternate fundamentals provider support.
- Automated buy/sell recommendations.
- Portfolio sizing or allocation rules.
- Automatic score-weight optimization from performance history.
- A persistent multi-day candidate memory model. This should be designed after
  the conviction gate is working.

## Design Principles

The report should prefer being empty over being noisy. A forced top 10 creates
false confidence when most candidates lack valuation, profitability, growth, or
liquidity support.

First North remains the preferred hunting ground, but First North membership is
not enough. The gate should require durable evidence before a name is promoted
as a long-term candidate.

Missing data should reduce conviction, but calculated proxies should be used
before treating evidence as missing. If the agent can infer market-cap-to-sales
or price-to-book from existing fields, it should use that information instead of
only saying "missing valuation data."

The model should remain explainable. Every promoted company should show why it
passed, and every demoted company should show which proof gaps blocked it.

## Conviction Gate

The long-term scoring path should still produce a ranked list of candidates.
After ranking, a conviction gate should classify each candidate into a report
tier.

High-conviction candidates must meet all of these requirements:

- Bucket is `Quality small-cap candidate`, or bucket is `Fundamental watchlist
  candidate` with at least three durable quality anchors.
- At least two durable quality anchors are present, such as positive operating
  margin, revenue growth, conservative balance sheet, net cash, attractive
  valuation support, or adequate liquidity.
- No severe proof gaps are present. Severe gaps include no profitability signal,
  negative operating margin, high debt/equity, thin data quality, missing
  business description, or missing liquidity data.
- Valuation support is available either from direct valuation metrics or a
  calculated proxy.

Fundamental watchlist candidates may have one meaningful proof gap, but they
must still have enough durable evidence for manual research.

Speculative monitors may appear below the main candidate section when they are
interesting First North discoveries, but they should not be counted as
high-conviction picks.

Insufficient-evidence names should be excluded from the main report body unless
the report includes a short rejected-candidates audit section.

## Valuation Proxies

The agent should derive valuation evidence from existing fields where available.
The first implementation should support conservative, easy-to-explain proxies:

- Market-cap-to-sales when market cap and revenue are available.
- Price-to-book when market cap and equity or book value are available.
- Net-cash-to-market-cap when net cash and market cap are available.
- Earnings yield or P/E when net income and market cap are available.

Proxy thresholds should be broad and conservative. Their first job is to avoid
mistaking "no direct P/E field" for "no valuation evidence." They should not
make a weak business look attractive just because one proxy is cheap.

Valuation output should distinguish:

- `Attractive valuation support`: at least one direct metric or proxy is inside
  the conservative threshold selected for that metric.
- `Valuation data available`: metrics exist but are not clearly attractive.
- `Missing valuation data`: no direct metric or proxy can be computed.

## Report Behavior

The long-term report should show:

- A high-conviction section if any companies pass the gate.
- A fundamental watchlist section for companies that are research-worthy but not
  high conviction.
- A speculative monitor section for interesting First North names with clear
  proof gaps.
- A short "No high-conviction ideas today" message when no companies pass.

The daily report should not force 10 high-conviction rows. If only three names
pass, the high-conviction section should contain three names. The remaining
monitor names may still be useful, but the report must make their lower
conviction explicit.

The JSON payload should preserve tier and gate-reason fields so the performance
ledger can review future outcomes by gate decision.

## Performance Review

The performance scorecard should track returns by conviction tier and gate
outcome. This allows future review of whether high-conviction candidates
outperform speculative monitors and insufficient-evidence names.

The first version should not automatically change weights. It should expose
evidence for human review after enough observations exist.

Useful future signals include:

- Gate tier.
- Number of durable anchors.
- Severe proof-gap count.
- Valuation proxy type.
- First North versus main market.
- Country and sector.

## Error Handling

Missing fundamentals should not crash report generation. Missing fields should
produce proof gaps, and unavailable proxy calculations should be skipped.

If no high-conviction ideas pass, the workflow should still succeed and publish
a valid report.

If Finimpulse lookup coverage is partial, the source-check warning should remain
visible. The gate should naturally demote companies with thin data.

## Testing

Tests should cover:

- A high-quality First North company with profitability, growth, balance-sheet
  strength, liquidity, and valuation support passes the high-conviction gate.
- A company with good growth but negative operating margin does not pass the
  high-conviction gate.
- A company with missing valuation direct metrics can pass when a conservative
  valuation proxy is available.
- A company with thin data quality or missing liquidity is demoted.
- Reports can render a valid "no high-conviction ideas today" result.
- JSON output includes gate tier and gate-reason fields.
- Performance review groups outcomes by conviction tier.
- Existing daily workflow tests still pass.

## Rollout

Implement this behind the existing `--strategy long-term` behavior. No new CLI
flag is needed.

After implementation, run the latest live or fixture long-term report and compare
the output against the 2026-05-29 report. The desired result is fewer top
long-term candidates, clearer warnings, and no speculative monitor presented as
a high-conviction pick.
