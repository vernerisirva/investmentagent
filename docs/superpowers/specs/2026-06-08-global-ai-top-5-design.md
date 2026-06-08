# Global AI Top 5 Design

## Goal

Add a separate public report that ranks the best global AI investment candidates
from a curated stock universe. The report should focus on quality plus
valuation, not market-cap size or AI hype.

The first version should produce a standalone `Global AI Top 5` report. It
should not change the Nordic trading or long-term First North reports.

## User Intent

The user wants better investment picks and still cares most about long-term
quality. First North small-caps remain the main local focus, but global AI is a
separate thematic opportunity set. The global AI report should help compare
large and mid-sized AI-exposed companies on valuation discipline, profitability,
growth, and business quality.

## Scope

In scope:

- Add a curated global AI stock universe.
- Generate a standalone `Global AI Top 5` report.
- Rank candidates by combined quality, growth, risk, and valuation.
- Show key valuation metrics where available.
- Show each candidate's AI exposure category.
- Use existing fundamentals enrichment patterns where possible.
- Include source checks and data-quality warnings.
- Add the report link to the public index.
- Keep the workflow daily so the report refreshes with the existing morning run.

Out of scope for the first version:

- Automatic global AI stock discovery.
- Performance tracking for global AI picks.
- Portfolio sizing.
- Buy/sell recommendations.
- Position weights.
- Options or crypto exposure.
- Replacing the Nordic small-cap reports.

## Report Shape

The report should be saved under:

- `docs/reports/global-ai/YYYY-MM-DD.md`
- `docs/reports/global-ai/latest.md`

The public index should link to:

- `Top 5 Global AI Candidates`

The report title should be:

`InvestmentAgent Global AI Top 5`

The report should include:

- Metadata.
- Source checks.
- A ranked top 5 list.
- AI exposure category for each company.
- Valuation snapshot.
- Quality and growth summary.
- Main risk flags.
- Evidence links.
- A disclaimer that the report is research triage only, not financial advice.

## Curated Universe

The first version should use a repository-maintained JSON universe file. Each
entry should define:

- Company name.
- Ticker.
- Country or listing market.
- Primary exchange suffix or provider symbol.
- AI exposure category.
- Short AI thesis.
- Optional sector.

Starter AI exposure categories:

- AI compute semiconductors.
- Semiconductor equipment.
- Cloud AI platform.
- Model/application platform.
- Enterprise AI software.
- AI infrastructure hardware.
- Data and analytics platform.

The initial universe should be curated and intentionally small enough to review.
It can include globally relevant AI-exposed public companies such as large AI
compute, semiconductor equipment, cloud platform, enterprise software, and data
platform names. The design should avoid treating every company that mentions AI
as eligible.

## Data Source

The first version should reuse the existing fundamentals-provider style where
possible.

If FinImpulse supports the global symbols in the curated universe, use it as the
primary fundamentals source. If some global symbols do not parse, the report
should still render and clearly show missing data in source checks and row-level
warnings.

The report should not silently rank missing-data companies above better-covered
companies. Missing valuation or quality fields should reduce confidence and
create visible risk flags.

## Scoring Model

The ranking should be long-term oriented and theme-aware. It should reward
companies that combine AI exposure with durable financial quality and valuation
discipline.

Suggested scoring buckets:

- Valuation: direct multiples such as P/E, price/book, EV/EBIT, and proxy
  ratios such as market-cap-to-sales when direct multiples are unavailable.
- Quality: profitability, operating margin, balance sheet conservatism, and
  business profile clarity.
- Growth: revenue growth and evidence that AI demand can support durable
  expansion.
- AI relevance: exposure category and whether the company is picks-and-shovels,
  platform, application, or hardware infrastructure.
- Risk: excessive valuation, weak profitability, missing data, customer
  concentration, cyclicality, or speculative hype.

The top 5 should be ranked by total score, but the report should make valuation
visible enough that an expensive AI leader does not look automatically better
than a reasonably valued high-quality compounder.

## Report Wording

The report should use sober language. It should avoid calling ideas "buys" and
should use terms like:

- Candidate.
- Watchlist idea.
- Research thesis.
- Valuation risk.
- Data confidence.

Rows with missing valuation data should remain eligible only if other evidence
is strong, and the report should clearly mark the valuation gap.

## Workflow Integration

The existing daily workflow should generate this report after the trading and
long-term Nordic reports.

The workflow should commit:

- `docs/reports/global-ai/YYYY-MM-DD.md`
- `docs/reports/global-ai/latest.md`
- Updated `docs/index.md`

The first version should not add global AI rows to the performance ledger.
Performance tracking is a follow-up feature that depends on verified global
quote and outcome support.

## Error Handling

If no global AI companies can be enriched, the workflow should still produce a
report showing source-check failures and an empty or low-confidence result set.

If one provider symbol fails, the report should continue with other companies.

If a configured required secret is missing, the workflow should fail visibly,
matching the existing FinImpulse behavior for the daily reports.

## Testing

Tests should cover:

- Loading the curated AI universe.
- Rejecting malformed universe entries.
- Ranking candidates by quality plus valuation.
- Penalizing missing valuation data.
- Rendering the standalone report title and top 5 rows.
- Showing AI exposure category and thesis.
- Showing source checks.
- Updating the public index link.
- Keeping the global AI report out of the existing performance ledger.
- Preserving existing trading and long-term report behavior.

## Rollout

Implement the report as a separate feature path. After it runs for a few days,
review whether:

- FinImpulse provides enough global valuation coverage.
- The curated universe should be expanded.
- The ranking is surfacing quality names rather than only mega-cap AI leaders.
- Performance tracking should be added for global AI candidates.
