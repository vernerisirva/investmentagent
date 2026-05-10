# Live Deep Dive Market Context Design

## Goal

Make `investmentagent deep-dive <ticker> --provider live` more useful by showing the live price and currency already available from Nasdaq Nordic while preserving the current thin-data warning.

## Scope

In scope:

- Add live price text to the deep-dive valuation section when `FinancialSnapshot.price` and `FinancialSnapshot.currency` are available.
- Keep P/E, price/book, and net cash/debt unavailable when those fields are absent.
- Reuse existing catalysts and risks in the deep-dive sections.
- Preserve fixture-backed deep-dive output except for harmless wording produced by shared helpers.

Out of scope:

- Adding new financial model fields.
- Inferring valuation from price alone.
- Adding paid or non-Nasdaq data.
- Changing CLI options or provider interfaces.

## Behavior

For live research with price and currency, the valuation section should begin with:

```text
Live price is 34.9 SEK from Nasdaq Nordic.
```

For research without price or currency, the valuation section should omit the live-price sentence and keep the existing unavailable metric sentences.

## Testing

Tests should cover:

- `build_deep_dive()` includes the live price sentence when financial price and currency are present.
- Existing fixture deep dives still include valuation text.
- Full test suite remains deterministic and does not require public internet.
