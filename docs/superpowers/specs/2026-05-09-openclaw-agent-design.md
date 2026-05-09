# OpenClaw Agent Design

Date: 2026-05-09

## Goal

Build OpenClaw as a CLI-first investing research agent for publicly listed Swedish and Finnish companies, including First North companies. The first version focuses on small and mid-cap discovery with a value bias. It produces a daily ranked watchlist and deeper company reports for selected tickers.

OpenClaw is a research triage tool, not a financial adviser. Outputs must show evidence, uncertainty, and risks instead of presenting recommendations as certainties.

## Scope

Included in v1:

- Publicly listed Swedish and Finnish companies.
- First North companies.
- A daily ranked watchlist for discovery and value opportunities.
- Deep-dive reports for individual companies.
- Free and public data sources only.
- CLI output as the primary interface.

Excluded from v1:

- Funds, warrants, derivatives, and private companies.
- Paid market data APIs.
- A web dashboard.
- Automated trading or portfolio execution.
- Claims of financial advice.

## Architecture

OpenClaw uses a modular Python CLI pipeline:

```text
universe -> data collection -> scoring -> ranked watchlist -> optional deep dive
```

Core units:

- Universe provider: builds the Sweden and Finland public company universe, including First North where available.
- Market data provider: fetches free price history, basic quote data, and available valuation fields.
- Company evidence provider: gathers official and public evidence links, such as IR pages, press releases, exchange pages, announcements, filings, and accessible news references.
- Scoring engine: ranks companies for small/mid-cap discovery with a value bias.
- Report renderer: prints readable CLI output and supports structured JSON output.

Provider boundaries should be clean. Free sources may change, block requests, or have incomplete coverage, so providers must be replaceable without rewriting scoring or rendering logic.

## Daily Watchlist

The `openclaw watchlist` command produces a ranked list of candidates.

Each watchlist item should include:

- Company name, ticker, country, exchange, and listing segment when available.
- Market cap band when available.
- Recent price context, such as performance or distance from highs and lows when free data allows.
- Value signals, such as low valuation multiples, asset discount, cash position, profitability versus price, or other available indicators.
- Discovery signals, such as small/mid-cap size, less-covered listing segments, lower visibility, recent underperformance, or neglected sectors.
- Catalysts, such as recent press releases, earnings reports, guidance changes, contract wins, restructuring, M&A hints, or other public announcements.
- Risks, such as low liquidity, dilution, leverage, cyclicality, negative earnings, poor disclosure, governance concerns, or sparse data.
- Evidence links and source timestamps where available.

The ranking should be transparent:

```text
total score = value score + discovery score + catalyst score - risk penalty - data quality penalty
```

The watchlist must separate observed facts from interpretation. Missing or unreliable data should reduce confidence instead of being filled with invented values.

## Deep-Dive Reports

The `openclaw deep-dive <ticker>` command generates a fuller research note for one company.

Each report should include:

- Business summary: what the company does, geography, segment exposure, and revenue model where available.
- Why it appeared: the watchlist signals that triggered interest.
- Valuation view: available multiples, balance sheet clues, cash/debt, profitability, and rough context from free sources.
- Catalysts: recent filings, earnings, press releases, contract wins, strategy changes, ownership notes, or other accessible public signals.
- Risks and red flags: liquidity, dilution, leverage, customer concentration, cyclicality, weak profitability, poor disclosure, or questionable data.
- Thesis framing: balanced bull, base, and bear cases.
- Next manual checks: specific documents or questions a human should review before considering the idea further.
- Evidence: source links and timestamps.

If a metric cannot be fetched reliably, the report must say so. The agent should be especially careful with Nordic small caps, where source coverage can be thin and manual annual report review often matters.

## Data Sources

V1 uses free and public sources only.

Source categories:

- Exchange and listing pages for Swedish and Finnish public companies.
- Free market data sources for quotes, price history, and basic valuation fields where accessible.
- Company IR pages.
- Official press releases.
- Exchange announcement pages and public filings.
- Public news or search result links where accessible.

Each provider should return a data-quality status:

- `good`: sufficient source coverage for the field or section.
- `partial`: some useful data exists, but coverage is incomplete.
- `thin`: data is missing, stale, or insufficient for confident analysis.

Every output item should include source links for key claims. Unverified claims should be marked as uncertain.

## CLI

Initial commands:

```bash
openclaw watchlist --country se,fi --limit 20
openclaw deep-dive <ticker>
openclaw sources test
```

Useful options:

```bash
--min-market-cap
--max-market-cap
--include-first-north
--sector
--output json
--verbose
```

The CLI should produce readable terminal output first. JSON output should be available for automation and later dashboard work.

## Implementation Stack

Recommended Python stack:

- `typer` for the CLI.
- `pydantic` or dataclasses for structured company, source, score, and report models.
- `httpx` or `requests` for HTTP fetching.
- `beautifulsoup4` only where HTML parsing is necessary.
- `pytest` for tests.

Dependencies should stay modest in v1. The system should prefer structured APIs or downloadable source data when available, and use scraping only where needed.

## Testing

Tests should cover:

- Scoring engine behavior using fixed sample companies.
- Provider behavior using fixture data or mocked source responses.
- CLI renderer output for readability and JSON shape.
- Error handling for missing data, broken sources, and partial evidence.
- Data quality penalties for thin or stale source coverage.

The first implementation should make the scoring logic deterministic and easy to test.

## Success Criteria

V1 is successful when:

- `openclaw watchlist` can produce a ranked Sweden/Finland public-company watchlist using free sources.
- Each ranked company includes reasons, risks, source links, and data-quality notes.
- `openclaw deep-dive <ticker>` can produce a balanced research note for a selected company.
- The scoring model is transparent and covered by tests.
- Source failures degrade gracefully instead of breaking the whole run.
