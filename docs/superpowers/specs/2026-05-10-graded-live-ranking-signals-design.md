# Graded Live Ranking Signals Design

## Goal

Reduce tied scores in live watchlists by converting existing Nasdaq Nordic intraday fields into graded, transparent signals.

## Scope

In scope:

- Replace the binary `Positive intraday momentum` catalyst with graded catalyst labels.
- Add a positive liquidity catalyst when live turnover is meaningfully high.
- Keep low turnover as a risk.
- Keep all live research marked as `thin` data quality.
- Preserve fixture provider behavior.

Out of scope:

- Price history.
- Valuation metrics.
- Currency conversion.
- Paid data sources.

## Signal Rules

For each Nasdaq live row:

- If price is present, add `Live price available from Nasdaq Nordic`.
- If percentage change is at least `10%`, add `Strong intraday momentum (+X%)`.
- If percentage change is at least `5%` and below `10%`, add `Positive intraday momentum (+X%)`.
- If turnover is at least `1000000`, add `High live turnover`.
- If turnover is at least `250000` and below `1000000`, add `Moderate live turnover`.
- If turnover is present and below `100000`, add `Low live turnover` as a risk.
- If percentage change is at most `-5%`, add `Sharp intraday selloff` as a risk.

## Ranking Effect

The existing scoring engine awards 8 catalyst points per catalyst up to 24 points. These graded labels improve ranking naturally through the existing catalyst mechanism without adding a special live-only scoring path.

## Testing

Tests should cover:

- Strong momentum and high turnover produce more catalysts than moderate momentum alone.
- Low turnover remains a risk.
- Scores differ for live rows with different signal strength.
- Full test suite remains deterministic.
