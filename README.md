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

The workflow runs at about 08:48 Europe/Helsinki on weekdays and writes public Markdown reports under `docs/reports/`. It publishes two top-10 lists:

- Trading ideas, generated with `--strategy trading`.
- Long-term investment ideas, generated with `--strategy long-term`.

Both public lists use `--min-country FI:3`, so each top 10 includes at least three Finnish companies when enough Finnish candidates are available.
Long-term reports also include a conviction bucket, a plain-English thesis, and component scores for business quality, valuation, growth, balance sheet, momentum, risk, and data confidence.

The performance page tracks published picks over 1d, 5d, 20d, and 60d horizons. It summarizes results publicly and may suggest scoring ideas after enough observations, but it does not change ranking weights automatically.

Public pages:

- Latest landing page: `https://vernerisirva.github.io/investmentagent/`
- Latest trading ideas: `https://vernerisirva.github.io/investmentagent/reports/trading/latest.html`
- Latest long-term ideas: `https://vernerisirva.github.io/investmentagent/reports/long-term/latest.html`
- Performance scorecard: `https://vernerisirva.github.io/investmentagent/performance/`
- Dated trading ideas: `https://vernerisirva.github.io/investmentagent/reports/trading/YYYY-MM-DD.html`
- Dated long-term ideas: `https://vernerisirva.github.io/investmentagent/reports/long-term/YYYY-MM-DD.html`

Reports are research triage only. They are not financial advice.
