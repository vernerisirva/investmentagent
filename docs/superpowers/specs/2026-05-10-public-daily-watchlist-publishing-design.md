# Public Daily Watchlist Publishing Design

## Goal

Publish InvestmentAgent's live Sweden/Finland watchlist to a public web page every weekday morning so it can be shared with family through one stable link.

## Recommendation

Use GitHub Actions plus GitHub Pages from the existing public repository. A scheduled workflow will run the live watchlist with Finimpulse enrichment, save a dated Markdown report under `docs/reports/`, update `docs/reports/latest.md`, update the public landing page at `docs/index.md`, commit those report files back to `main`, and let GitHub Pages serve the `docs/` folder.

## Schedule

The workflow should run Monday-Friday at 08:00 Europe/Helsinki time. GitHub cron is UTC-only, so the workflow will trigger at both 05:00 UTC and 06:00 UTC on weekdays and skip the duplicate run unless the current Helsinki hour is `08`. This handles daylight saving time without manual edits.

## Data And Secrets

The workflow will read `FINIMPULSE_API_KEY` from GitHub repository secrets. The key must never be committed, printed, or included in generated report files. If the secret is missing, the workflow should fail clearly before trying to generate a report.

## Public Output

The public site will contain:

- `docs/index.md`: stable landing page for the latest public report.
- `docs/reports/latest.md`: the latest watchlist.
- `docs/reports/YYYY-MM-DD.md`: dated historical watchlists.

Reports remain research triage only and must retain the existing "Not financial advice" disclaimer.

## GitHub Pages Setup

After the workflow is pushed, GitHub Pages should be configured in repository settings to deploy from branch `main`, folder `/docs`. The stable public URL will be the repository's GitHub Pages URL.

## Acceptance Criteria

- A GitHub Actions workflow exists for weekday morning report generation.
- The workflow can also be started manually with `workflow_dispatch`.
- The workflow installs the package, runs the live Finimpulse watchlist, saves Markdown reports, updates the public landing page, and commits only when generated files changed.
- The workflow never stores or echoes API tokens.
- Documentation tells the user where to put the GitHub secret and how to enable Pages.
