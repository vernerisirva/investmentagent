# Public Idea Reports And Company Descriptions Design

## Goal

Improve the public InvestmentAgent report so it publishes two daily top-10 lists and explains what each company actually does in readable Markdown.

## Report Types

The weekday publishing workflow should generate:

- Trading ideas: top 10 companies using `--strategy trading`.
- Long-term investment ideas: top 10 companies using `--strategy long-term`.

The public landing page should link to the latest version of both reports and keep dated historical report files.

## Company Descriptions

Sector labels are not enough. The public reports should include a "What the company does" section for each company.

For Finimpulse-enriched live reports, the provider should call the Finimpulse profile endpoint after a successful search lookup and use `long_business_summary` when available. The summary should be stored on the `Company` model as `business_description` so renderers can stay source-agnostic.

If the profile call fails or the field is missing, the report should fall back to the existing deterministic sector/listing presentation.

## Markdown Formatting

Saved Markdown watchlist reports should be structured for GitHub Pages instead of embedding raw CLI text.

Each company should render as:

- A second-level heading with rank, name, and ticker.
- A compact listing line.
- A "What the company does" paragraph.
- Score and data quality.
- Reasons as bullets.
- Risks as bullets.
- Evidence as bullets.

The report should avoid duplicated "Watchlist" headings and run-on paragraphs.

## Security And API Behavior

Finimpulse tokens must remain header-only and must not appear in reports, source checks, logs, evidence URLs, or exceptions. Profile calls are best-effort: search/fundamentals data can still be used when profile data fails.

## Acceptance Criteria

- Public workflow publishes separate trading and long-term top-10 Markdown reports each weekday.
- Public landing page links to both latest reports and dated files.
- Markdown reports are readable on GitHub Pages.
- Company descriptions use Finimpulse `long_business_summary` when available.
- Reports fall back gracefully when no business description exists.
- Tests cover profile parsing, enrichment, Markdown formatting, and report output.
