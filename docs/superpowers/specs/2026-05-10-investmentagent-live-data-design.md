# InvestmentAgent Live Data Design

Date: 2026-05-10

## Goal

Add the first live-data capability to InvestmentAgent without disturbing the existing fixture-backed MVP. The feature should let users choose between deterministic fixture data and a live provider that attempts to build a Sweden/Finland listed-company universe from free public sources.

This branch should make live provider infrastructure real. It should not yet attempt full valuation, news, AI synthesis, or complete market-data enrichment.

## Scope

Included:

- Provider selection in the CLI: `fixture` or `live`.
- A `LiveNasdaqNordicProvider` skeleton that fetches and parses a public Nasdaq Nordic listing/reference-data source where available.
- Source diagnostics for both fixture and live providers.
- Graceful live-source failure handling with clear source-check output.
- Mocked tests for live fetch success and failure.
- Fixture provider remains the default so tests and demos stay deterministic.

Excluded:

- Paid APIs.
- Autonomous trading.
- AI-generated investment theses from live web searches.
- Full quote, market-cap, ratio, news, or filings enrichment.
- Silent fallback from live data to fixture data.

## Architecture

Add provider selection through a small factory:

```text
CLI --provider fixture|live -> provider factory -> ResearchProvider
```

The existing `FixtureResearchProvider` remains unchanged as the default. The new live provider should share the same `ResearchProvider` protocol, so watchlist and deep-dive builders do not need to know which provider they are using.

Live provider responsibilities:

- Fetch public Nasdaq Nordic listing/reference data.
- Parse enough fields to create `Company` objects.
- Support country filtering for Sweden and Finland.
- Include First North listings when requested.
- Return `SourceCheck` records that explain whether fetching/parsing succeeded.
- Return thin `CompanyResearch` records for listed companies when detailed financial data is not available yet.

If live fetching fails, `source_checks()` should expose the failure. `watchlist --provider live` may return an empty watchlist when no live companies can be loaded, but it must not pretend fixture data is live.

## CLI

Add a provider option to relevant commands:

```bash
investmentagent watchlist --provider fixture
investmentagent watchlist --provider live
investmentagent deep-dive FREEM --provider fixture
investmentagent sources test --provider live
```

Rules:

- Default provider is `fixture`.
- Valid values are `fixture` and `live`.
- Invalid provider values should fail with a clear CLI error.
- `sources test --provider live` should be the first place users check live connectivity.

## Data Quality

The first live provider should mark research quality as `thin` unless it has reliable financial data. The watchlist score should continue to penalize thin data.

For live companies without detailed research:

- Catalysts can be empty.
- Risks should include at least a sparse-data risk.
- Evidence should include the public listing/reference source URL.
- Valuation fields can be `None`.

## Testing

Tests should not depend on the public internet. Add mocked live-provider tests that cover:

- Successful parsing of a small sample live-source payload.
- Country filtering.
- First North inclusion/exclusion.
- Fetch failure surfaces through `source_checks()`.
- CLI provider selection for `fixture` and `live`.
- Invalid provider input.

Existing fixture tests should keep passing without network access.

## Success Criteria

This feature is done when:

- `investmentagent watchlist --provider fixture` behaves as it does today.
- `investmentagent sources test --provider live` reports live provider status clearly.
- Live provider parsing is covered by deterministic mocked tests.
- Live provider failures are visible and do not silently fall back to fixture data.
- The full test suite passes without network access.
