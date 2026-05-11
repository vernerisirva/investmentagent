# Public Performance Monitoring Design

## Goal

Add public monitoring for InvestmentAgent's daily trading and long-term ideas so the results can be reviewed over time. The system should show whether the watchlists are useful, separate trading results from long-term results, and create evidence-based suggestions for improving the scoring model.

## Recommendation

Build a public scorecard backed by a versioned performance ledger. The public GitHub Pages site should show readable summaries, while machine-readable data files in the repository keep the detailed pick and outcome history. The agent should not silently change its scoring weights. It should learn by producing transparent observations and suggested scoring changes that a human can review before implementation.

## Scope

V1 should track:

- Daily top 10 trading ideas.
- Daily top 10 long-term investment ideas.
- Entry price at report generation time when Nasdaq Nordic provides a live price.
- Outcome returns after 1, 5, 20, and 60 calendar days, measured at the first available weekday update on or after each horizon.
- Hit rate, average return, median return, best picks, worst picks, and open picks.
- Signal-level summaries for country, segment, sector, strategy, conviction bucket, reasons, and risks.
- A public performance page under `docs/performance/`.

V1 should not execute trades, recommend position sizes, send alerts, or auto-change the ranking model.

## Data Model

Create a performance ledger under `docs/data/performance/ledger.json`.

The ledger should use a stable schema version and contain a list of pick records. Each pick should include:

- `pick_id`: stable key, for example `2026-05-11|trading|STABL|1`.
- `report_date`.
- `strategy`: `trading` or `long-term`.
- `rank`.
- `ticker`, `name`, `country`, `exchange`, `segment`, and optional `sector`.
- `report_url`.
- `entry_price`, `entry_currency`, and `entry_timestamp` when available.
- `score_total`, reasons, risks, and data quality.
- Long-term conviction bucket and component scores when present.
- Outcome snapshots keyed by horizon, for example `1d`, `5d`, `20d`, and `60d`.

Each outcome snapshot should include:

- `as_of_date`.
- `price`.
- `currency`.
- `return_pct`.
- `status`: `priced`, `missing_price`, or `not_due`.

If a pick has no entry price, it stays in the ledger but is excluded from return calculations until a reliable entry price is available.

## Data Flow

The daily public report workflow should add a performance step after generating the trading and long-term reports.

1. Generate the public trading and long-term reports as today.
2. Save or derive structured report data for both strategies.
3. Append new picks to the ledger if they do not already exist.
4. Fetch the current Nasdaq Nordic price universe.
5. Update due outcome horizons for existing picks.
6. Render the public performance page.
7. Commit the reports, ledger, and performance page together.

The update should be idempotent. Re-running the workflow for the same day should not create duplicate picks.

## Public Pages

Add these public files:

- `docs/performance/index.md`: main scorecard.
- `docs/performance/latest.md`: alias or copy of the latest scorecard.
- `docs/data/performance/ledger.json`: machine-readable pick and outcome history.

The scorecard should show:

- Generated timestamp.
- Last successful report date.
- Trading idea performance.
- Long-term idea performance.
- Open picks waiting for outcome windows.
- Best and worst completed picks.
- Signal review: which reasons, countries, segments, and conviction buckets have helped or hurt so far.
- Learning suggestions with minimum sample-size warnings.

All public pages should keep the existing "Research triage only. Not financial advice." disclaimer.

## Learning Loop

Learning should be transparent and conservative.

The agent may calculate signal statistics such as:

- Average return by reason.
- Hit rate by reason.
- Average return by risk.
- Average return by conviction bucket.
- Trading versus long-term performance.
- First North versus main market performance.
- Sweden versus Finland performance.

The scorecard may include suggested adjustments only when there are at least 10 completed observations for a signal. Suggestions should be phrased as evidence to review, for example:

"High live turnover has produced a positive 5-day average return across 14 completed trading picks. Consider keeping or increasing its trading weight."

The agent must not update scoring weights automatically. Any scoring change should be implemented through a separate reviewed code change.

## Error Handling

- Missing entry price: keep the pick, mark it unpriced, exclude it from return aggregates.
- Missing outcome price: keep the outcome as `missing_price` and retry on the next update.
- Currency mismatch: do not compute a return unless entry and outcome currency match.
- Malformed existing ledger: fail clearly and do not overwrite the file.
- Duplicate workflow runs: skip existing `pick_id` records.
- Source failure: publish the normal source-check failure if report generation fails; do not publish partial performance data as if it were complete.

## Testing

Tests should avoid public internet and use fixture data.

Add tests for:

- Creating ledger entries from watchlist items.
- Avoiding duplicate picks on rerun.
- Updating due outcome horizons.
- Leaving future horizons as `not_due`.
- Excluding missing prices from aggregate returns.
- Rendering a readable public scorecard.
- Generating learning suggestions only after the minimum sample size.
- Preserving separate trading and long-term summaries.

## Acceptance Criteria

- A public performance page is generated under `docs/performance/`.
- A versioned ledger exists under `docs/data/performance/ledger.json`.
- Daily workflow updates reports and performance data in one commit.
- Trading and long-term ideas are tracked separately.
- 1d, 5d, 20d, and 60d outcomes are recorded when due.
- The scorecard summarizes hit rate, average return, best picks, worst picks, and signal-level results.
- Learning suggestions are visible but never auto-applied to ranking weights.
- The full test suite remains deterministic and does not require public internet.
