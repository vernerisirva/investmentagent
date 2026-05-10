# Watchlist Company Presentation Design

## Goal

Add a short company presentation to each watchlist item so the output is easier to scan and understand. The presentation should explain what the company is, where it is listed, and the most useful available size/financial context without adding new API calls.

## Scope

In scope:

- Generate a concise presentation from existing structured data already available in each `WatchlistItem`.
- Include the presentation in text watchlist output.
- Include the presentation in JSON watchlist output and saved JSON reports.
- Let saved Markdown reports inherit the text output presentation.
- Keep the presentation deterministic and testable.

Out of scope:

- Dynamic web browsing or search.
- Calling Finimpulse `/v1/profile`.
- Long business descriptions.
- LLM-generated summaries.
- Changing ranking or scoring.

## Presentation Content

The presentation should be one sentence when enough data is available. It should use these fields, when present:

- Company name and country.
- Listing segment and exchange.
- Sector.
- Market cap in EUR millions.
- Revenue growth.
- Operating margin.
- One-year return.

Example:

```text
Presentation: Karnov Group AB is a Sweden-listed main market Industrials company on Nasdaq Stockholm. Market cap is about EUR 702m, revenue growth is 24.6%, operating margin is 36.8%, and one-year return is -16.5%.
```

If data is sparse, the sentence should gracefully omit missing fields:

```text
Presentation: BeammWave B is a Sweden-listed First North company on Nasdaq First North Growth Market Sweden.
```

## Architecture

Add a small pure rendering helper that accepts a `WatchlistItem` or its `Company` and `FinancialSnapshot`, then returns a string. This should live in `src/investmentagent/renderers.py` because it is presentation logic, not research or scoring logic.

The helper should not mutate models and should not introduce new model fields. JSON rendering can call the same helper and expose the result as:

```json
"company_presentation": "..."
```

Text rendering should add:

```text
Presentation: ...
```

between the listing line and score line.

## Formatting Rules

- Use `Sweden` for `SE` and `Finland` for `FI`; fall back to the country code otherwise.
- Use readable segment labels: `First North`, `main market`, `Spotlight`, or `public market`.
- Round market cap to whole EUR millions when at least EUR 100m, otherwise one decimal.
- Format percentages with one decimal place.
- Avoid saying “unknown” in the presentation; omit missing facts instead.
- Do not include links or evidence in the presentation.

## Testing

Tests should cover:

- Text watchlist output includes a `Presentation:` line.
- JSON watchlist output includes `company_presentation`.
- Saved JSON report includes `company_presentation` through existing item payloads.
- Presentations omit missing values instead of printing `None`.
- Presentations include Finimpulse-enriched market cap and financial context when available.

## Future Work

Later, a richer presentation can be added to deep dives by calling Finimpulse `/v1/profile` or a controlled web research mode. That should be optional and separate from the daily watchlist path because it adds latency, cost, and more failure modes.
