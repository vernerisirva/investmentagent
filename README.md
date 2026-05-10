# InvestmentAgent

InvestmentAgent is a CLI-first research triage tool for Swedish and Finnish publicly listed stocks, including First North companies. It focuses on small and mid-cap discovery with a value bias.

InvestmentAgent is not financial advice. It ranks research candidates, shows evidence, and highlights uncertainty so a human investor can decide what to investigate next.

## Install for local development

```bash
python -m pip install -e ".[dev]"
```

## Commands

```bash
investmentagent watchlist --country se,fi --limit 20
investmentagent watchlist --country se,fi --limit 5 --output json
investmentagent deep-dive FREEM
investmentagent sources test
```

## Data providers

InvestmentAgent defaults to deterministic fixture data so scoring, reports, and CLI behavior can be tested repeatably:

```bash
investmentagent watchlist --provider fixture
investmentagent deep-dive FREEM --provider fixture
investmentagent sources test --provider fixture
```

The live provider is an early free-source integration point for Sweden and Finland listed-company discovery:

```bash
investmentagent sources test --provider live
investmentagent watchlist --provider live --country se,fi --limit 20
investmentagent deep-dive FREEM --provider live
```

The live provider does not silently fall back to fixture data. If the public source cannot be fetched or parsed, `sources test --provider live` reports the failure and live watchlists or deep dives stop with a clear source error.

## Scoring model

The score is transparent:

```text
total score = value score + discovery score + catalyst score - risk penalty - data quality penalty
```

Every report should show reasons, risks, data quality, and evidence links.

## Public weekday reports

The repository includes a GitHub Actions workflow named `Daily public watchlist` that can publish a public watchlist every weekday morning.

Setup:

1. Add a repository secret named `FINIMPULSE_API_KEY` in GitHub: Settings -> Secrets and variables -> Actions -> New repository secret.
2. Enable GitHub Pages: Settings -> Pages -> Build and deployment -> Deploy from a branch -> branch `main`, folder `/docs`.
3. Run the workflow manually once from Actions -> Daily public watchlist -> Run workflow, or wait for the weekday schedule.

The workflow runs at 08:00 Europe/Helsinki on weekdays, generates a Finimpulse-enriched live watchlist, and writes public Markdown reports under `docs/reports/`.

Public pages:

- Latest landing page: `https://vernerisirva.github.io/investmentagent/`
- Latest report: `https://vernerisirva.github.io/investmentagent/reports/latest.html`
- Dated reports: `https://vernerisirva.github.io/investmentagent/reports/YYYY-MM-DD.html`

Reports are research triage only. They are not financial advice.
