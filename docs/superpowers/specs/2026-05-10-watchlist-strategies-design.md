# Watchlist Strategies Design

## Goal

Improve live watchlists so InvestmentAgent does not treat every First North intraday spike as a high-quality opportunity. The agent should separate long-term investment candidates from short-term trading ideas while keeping the raw momentum scanner available.

## Scope

In scope:

- Add a `--strategy` option to `investmentagent watchlist`.
- Make `balanced` the default strategy for ordinary watchlists.
- Add separate `long-term` and `trading` strategy modes.
- Keep a raw `momentum` strategy for users who explicitly want strongest daily movers.
- Improve live risks for extreme spikes, weak liquidity, and speculative low-price shares.
- Deduplicate live listing rows by ticker and country before ranking.
- Preserve fixture provider behavior unless a test needs a strategy-specific fixture case.

Out of scope:

- Paid data sources.
- Multi-year financial statement ingestion.
- Analyst estimates.
- Portfolio sizing or buy/sell recommendations.
- Automated trading.

## Strategy Modes

`balanced` is the default. It should produce a cleaner daily watchlist by excluding or heavily penalizing extreme intraday spikes, missing turnover, and low-turnover names. It should still allow First North companies when liquidity and signals are credible enough.

`long-term` should favor investable discovery and value signals over daily price action. With the current free source set, this means avoiding extreme spikes and weak liquidity, giving less weight to intraday momentum, and surfacing names that deserve manual financial-statement review. As richer financial data is added later, this strategy becomes the home for valuation, profitability, balance sheet, and catalyst thesis scoring.

`trading` should identify short-term setups. It can reward positive intraday momentum and turnover more than `long-term`, but it should still flag extreme spikes and very low-price shares as higher-risk ideas rather than clean opportunities.

`momentum` should remain closest to the current behavior. It is useful when the user wants raw strongest movers, including speculative First North movers, but the output must still show risks clearly.

`discovery` should remain small/mid-cap oriented. It should accept higher risk than `balanced`, prefer less-covered names, and avoid obvious data-quality traps such as missing turnover or extreme one-day spikes.

## Live Risk Rules

The live Nasdaq Nordic provider should continue to mark all live rows as `thin` data quality. It should also add transparent risks from numeric live fields:

- `Extreme intraday spike` when percentage change is at least `40%`.
- `Sharp intraday selloff` when percentage change is at most `-5%`.
- `Low live turnover` when turnover is present and below `100000`.
- `Missing live turnover` when both turnover and volume are unavailable.
- `Speculative low-price share` when the live price is below `1` in the listing currency.

These are not automatic rejections for every strategy. They are input signals the strategy layer can interpret.

## Ranking Behavior

The base scoring engine should continue to create value, discovery, catalyst, risk, and data-quality components. Strategy handling should apply a focused adjustment after base scoring rather than rewriting the whole score model.

For `balanced`, exclude or strongly penalize:

- Extreme intraday spikes.
- Missing turnover.
- Low live turnover.
- Speculative low-price shares unless stronger evidence is available later.

For `long-term`, discount intraday momentum catalysts and prefer lower-risk, more investable candidates. Until richer valuation data exists, this mode should be conservative and explicit about data gaps.

For `trading`, reward strong momentum and live turnover, but keep risk warnings visible. Extreme spikes should rank lower than strong but more orderly moves.

For `momentum`, preserve the current raw-mover feel with clearer risk labeling.

For `discovery`, favor First North and small/mid-cap names but avoid rows with missing turnover or extreme spikes.

## CLI And Reports

`investmentagent watchlist` should accept:

```text
--strategy balanced|long-term|trading|momentum|discovery
```

Saved report metadata should include the selected strategy so nightly reports are auditable. Text and JSON output can keep the same item shape; the strategy is part of command metadata for saved reports.

The existing daily automation should continue to work because `balanced` is the default. After implementation, the automation prompt can be updated to mention the balanced daily watchlist explicitly.

## Testing

Tests should cover:

- The CLI accepts supported strategies and rejects unsupported ones before provider work.
- `balanced` filters or penalizes extreme spike and weak-liquidity rows.
- `momentum` can still surface a raw high-momentum row.
- `long-term` ranks a steadier candidate above an extreme spike when both are available.
- `trading` favors momentum plus turnover without treating extreme spikes as clean winners.
- Live provider emits the new risks from Nasdaq numeric fields.
- Live provider deduplicates listing rows by ticker and country.
- Saved watchlist reports include selected strategy metadata.
