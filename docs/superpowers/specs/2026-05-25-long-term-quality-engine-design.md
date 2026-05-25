# Long-Term Quality Engine Design

## Goal

Improve InvestmentAgent's long-term watchlist so the top ideas are better small-cap research candidates, not just small or active listings. First North and other underfollowed small-cap markets remain the primary hunting ground, but long-term ranking should require more durable evidence before a company reaches the top of the report.

The system should help answer: "Which small-cap companies deserve manual long-term research next?"

## Current Context

InvestmentAgent already publishes daily long-term and trading reports from live Nasdaq Nordic listings enriched with Finimpulse fundamentals. It also tracks public performance in `docs/data/performance/ledger.json` and renders a scorecard under `docs/performance/`.

The current long-term strategy rewards First North, small market cap, positive operating margin, revenue growth, conservative debt/equity, and business descriptions. It also discounts intraday signals. This is a good base, but the reports still need a stronger distinction between investable small-cap quality and speculative small-cap discovery.

## Scope

In scope:

- Add a long-term quality layer for the `long-term` strategy.
- Keep First North and small-cap discovery as positive signals.
- Reward durable evidence: profitability, growth, conservative balance sheet, valuation support, business description, and practical liquidity.
- Penalize missing or weak long-term proof: missing valuation, no profitability signal, no growth signal, negative operating margin, high debt, thin liquidity, and names supported only by live/intraday signals.
- Improve long-term conviction buckets and thesis text in reports.
- Add tests proving high-quality First North names outrank weaker speculative names.
- Use the existing performance ledger for reviewed learning suggestions, not automatic score changes.

Out of scope:

- New paid data sources.
- Automated buy/sell recommendations.
- Automatic scoring-weight changes.
- Portfolio sizing.
- Reworking the trading strategy.
- Replacing the existing daily publishing workflow.

## Design Principles

First North should be treated as an opportunity set, not a quality signal by itself. A First North company can rank highly, but only when supported by enough long-term evidence.

Missing data should be visible and should matter. A company with no valuation, no profitability signal, and no growth signal can still appear as a speculative monitor, but it should not outrank companies with stronger fundamental support unless other evidence is compelling.

The first version should be conservative and explainable. The reports should make clear why an idea ranks well and what proof is still missing.

## Scoring Architecture

Keep the existing base score from `score_research()`. Add a strategy-specific long-term quality layer inside the long-term scoring path.

The long-term score should combine:

- Existing value score.
- Discounted discovery score.
- Durable quality adjustment.
- Long-term proof penalties.
- Existing risk and data-quality penalties.

This keeps the scoring model compatible with current reports while making long-term behavior more thesis-driven.

## Quality Evidence Signals

The long-term quality layer should reward:

- Positive operating margin.
- Revenue growth.
- Conservative debt/equity.
- Net cash when available.
- Attractive valuation when P/E or P/B is available.
- Business description/profile availability.
- Adequate average daily value when available.
- First North listing as a discovery boost, but lower than true quality evidence.

The weights should make a profitable, growing, conservatively financed First North company outrank a weaker First North company that is mostly small, active, or newly surfaced.

## Proof Penalties

The long-term layer should penalize:

- Missing valuation data.
- No profitability signal.
- No growth signal.
- Negative operating margin.
- High debt/equity.
- Thin liquidity.
- Only live-market or intraday support.
- Partial or thin data quality.

These should mostly be ranking penalties rather than hard exclusions. The report should still allow speculative small-cap monitors, but weaker proof should push them down and make the uncertainty explicit.

## Conviction Buckets

Long-term reports should classify each idea into one of these buckets:

- `Quality small-cap candidate`: small-cap or First North company with multiple durable quality signals and manageable risks.
- `Fundamental watchlist candidate`: enough evidence for manual research, but at least one major proof gap remains.
- `Speculative small-cap monitor`: interesting small-cap discovery, but quality evidence is weak or incomplete.
- `Insufficient evidence`: appears in the screen but lacks enough support for a strong long-term thesis.

The bucket should be computed from the same quality signals and penalties used by ranking, so the report text matches the score.

## Report Behavior

The long-term report should keep the existing company presentation, component table, reasons, risks, and evidence links. It should improve the thesis wording so the reader can immediately see:

- what makes the company interesting,
- what long-term evidence supports it,
- what evidence is missing,
- whether it is a quality candidate or a speculative monitor.

The report should avoid presenting a company as a strong long-term idea when the available data only supports "monitor this small-cap."

## Performance-Led Learning

Use the existing performance ledger as an input to human-reviewed learning.

The agent should summarize long-term outcomes by quality-related signals, such as:

- First North versus main market.
- Positive operating margin versus missing or negative margin.
- Conservative balance sheet versus high debt.
- Valuation available versus valuation missing.
- Adequate liquidity versus thin liquidity.
- Quality bucket.

The agent may suggest scoring changes after enough observations, but it must not change weights automatically. Suggested changes should be reviewed and implemented through normal commits.

## Error Handling

Missing fundamentals should not crash report generation. Instead, missing fields should produce explicit proof gaps and ranking penalties.

Provider failures should keep the current behavior: source checks report failures clearly, and live watchlist generation should fail rather than silently falling back to fixture data.

If performance history is too sparse for a signal, the review should say there are not enough observations instead of implying confidence.

## Testing

Tests should cover:

- First North remains a positive discovery signal.
- A profitable, growing, conservatively financed First North company outranks a weaker speculative First North company.
- Missing valuation, profitability, and growth evidence reduce long-term rank.
- Negative operating margin and weak liquidity create stronger long-term penalties.
- Conviction buckets match the quality state.
- Report thesis text distinguishes quality candidates from speculative monitors.
- Performance review groups long-term outcomes by quality signals.
- Existing daily workflow tests still pass.

## Rollout

Implement the quality layer behind the existing `--strategy long-term` behavior. No new CLI flag is needed for the first version.

After implementation, compare the latest long-term report before and after the scoring change. The desired outcome is a top 10 that still includes First North companies, but with clearer fundamental support and fewer names ranked highly on discovery alone.
