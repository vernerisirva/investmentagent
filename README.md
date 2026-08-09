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
investmentagent watchlist --provider live --country se,fi --limit 20 \
  --refresh-limit 30 \
  --fundamentals-cache .investmentagent/fundamentals-cache.json
investmentagent deep-dive FREEM --provider live
```

The live provider does not silently fall back to fixture data. If the public source cannot be fetched or parsed, `sources test --provider live` reports the failure and live watchlists or deep dives stop with a clear source error.

`--limit` controls only the final watchlist size. `--refresh-limit` (also accepted
as `--enrichment-limit`) bounds external fundamentals refreshes and defaults to
30. When `--fundamentals-cache` is configured, every eligible company may reuse
validated cached fundamentals even when it is outside today's refresh selection.
Missing companies are refreshed first, followed by stale companies from oldest
to newest. `--cache-max-age-days` controls snapshot freshness and defaults to 45.
Use `--refresh-limit 0` to make no fundamentals requests.

The cache is a private, configurable runtime file containing normalized accepted
values rather than vendor payloads or credentials. It is ignored by Git, must not
be placed under `docs/`, and the scheduled workflow persists it through GitHub
Actions cache storage. Confirm applicable provider redistribution terms before
choosing a repository-backed cache deployment.

## Performance v2 evaluation snapshots

Trading and long-term watchlists can persist the complete final ranked universe
from the same scoring run used for the public top N:

```bash
investmentagent watchlist --provider fixture --strategy long-term --limit 3 \
  --evaluation-dir data/evaluations \
  --evaluation-decision-at 2026-08-10T08:30:00+00:00
```

Snapshots are versioned JSONL files under `data/evaluations/<date>/<strategy>/`.
They contain stable company identity, final ranks, score components, gate outputs,
structured threshold flags, field-availability/provenance summaries, cache state,
and universe diagnostics. They deliberately omit raw financial values and full
provider observations, which remain in the private fundamentals cache.

An explicit decision timestamp is accepted only for deterministic fixture runs.
Live evaluation timestamps are captured after enrichment and final ranking, so
the CLI does not provide a production historical-backfill path. Evaluation files
are also rejected under `docs/` to keep them outside GitHub Pages.

## Performance v2 market outcomes

Performance v2 keeps future market outcomes separate from immutable evaluation
snapshots. The live historical-price adapter uses EODHD end-of-day data and only
accepts `adjusted_close`, which EODHD documents as adjusted for splits and
dividends. It never substitutes a raw close into the primary research return.

Configure `EODHD_API_KEY`, then refresh due outcomes and run the offline analysis:

```bash
investmentagent evaluate outcomes \
  --evaluation-root data/evaluations \
  --outcome-root data/evaluation-outcomes \
  --price-provider eodhd \
  --price-cache .investmentagent/market-price-cache.json \
  --max-price-api-calls 20

investmentagent evaluate analyze \
  --evaluation-root data/evaluations \
  --outcome-root data/evaluation-outcomes \
  --output-json data/evaluation-analysis/performance-v2.json \
  --output-markdown data/evaluation-analysis/performance-v2.md
```

Outcomes are keyed by evaluation run, stable company identity, and horizon.
Trading defaults to 1, 5, 20, and 60 valid market sessions; long-term defaults to
20, 60, 126, and 252 sessions. Entry is the first Stockholm or Helsinki session
close strictly after the recorded decision timestamp. Holidays, local time zones,
and recurring Stockholm equity half days are part of the session calculation.

The outcome store under `data/evaluation-outcomes/` is normalized, versioned,
atomic, and idempotent. Established entries and priced outcomes are frozen. If a
provider later revises an established adjusted entry, the record is excluded with
an explicit corporate-action status instead of being silently rewritten. Missing
entries, exits, mappings, and provider failures remain visible.

Outcome refresh first plans the union of due entry and exit sessions across all
selected evaluation dates and both strategies. Accepted adjusted-close
observations are reused from the private normalized cache by stable company ID,
provider, symbol, market, and session. Only the smallest range spanning missing
sessions is requested once per security, so trading, long-term, and challenger
analysis share the same archive without changing outcome calculations.

`--max-price-api-calls` is a hard per-invocation budget and defaults to 20.
Unestablished entries, shorter due horizons, older evaluations, and stable
company identity determine deterministic backlog order. Completed cache and
outcome work is retained when the budget is exhausted; deferred securities are
reported in CLI diagnostics and remain refreshable. Conflicting provider
revisions are recorded in the cache while the first accepted observation and
established evaluation entries remain immutable.

The operational cache contains normalized observations and revision evidence,
not provider payloads, API keys, or public report data. It is ignored by Git,
must stay outside `docs/`, and the scheduled workflow restores it through GitHub
Actions cache. Losing it increases future API calls but does not invalidate the
durable evaluation or outcome stores.

Analysis is performed per evaluation run before aggregation and never pools model
versions. It reports score and final-rank Spearman IC, equal-weight original-
universe and same-country comparisons, rank buckets, top-decile spreads, long-term
gate tiers, country splits, and missingness. Returns are gross and exclude spread,
commissions, and slippage. Small samples are labeled as insufficient for reliable
inference.

EODHD's free plan has a low daily request allowance and may be insufficient for a
complete daily Nordic universe. Tests and fixture analysis require no credential,
but durable live coverage requires an EODHD plan/quota appropriate to the number
of due unique securities.

## Shadow challenger experiments

Long-term production runs can record the `relative-valuation-v1` shadow
challenger from the same final research universe used by the production ranking:

```bash
investmentagent watchlist --provider fixture --strategy long-term --limit 3 \
  --evaluation-dir data/evaluations \
  --experiment-dir data/evaluation-experiments \
  --evaluation-decision-at 2026-08-10T08:30:00+00:00

investmentagent evaluate experiments \
  --experiment-root data/evaluation-experiments
```

The challenger leaves `nordic-ranking-v1`, its gates, public ranks, and public
reports unchanged. It applies a bounded `-6 ... +6` adjustment from the
contemporaneous cross-sectional ranks of positive P/E, P/B, and EV/EBIT values.
Normalization is country-relative with at least five observations per metric and
falls back to the full universe with at least three; missing and non-positive
values are neutral. Sidecars contain derived factor values rather than raw
financial data and are stored under
`data/evaluation-experiments/<date>/long-term/relative-valuation-v1/`.

Pass `--experiment-root data/evaluation-experiments` to `evaluate analyze` to add
paired champion-versus-challenger diagnostics. Historical evaluations without a
contemporaneous sidecar are reported as `challenger not recorded`; they are never
reconstructed from newer fundamentals. Fewer than 20 completed paired dates is
explicitly treated as insufficient history, and no result promotes a challenger
automatically.

## Scoring model

The score is transparent:

```text
total score = value score + discovery score + catalyst score - risk penalty - data quality penalty
```

Every report should show reasons, risks, data quality, and evidence links.

## Public weekday reports

The repository includes a GitHub Actions workflow named `Daily public watchlist` that can publish a public watchlist every weekday morning.

Setup:

1. Add a repository secret named `FINIMPULSE_API_KEY` in GitHub: Settings -> Secrets and variables -> Actions -> New repository secret. Add `EODHD_API_KEY` to enable Performance v2 market outcomes; if it is absent, that step is skipped explicitly without blocking the daily report.
2. Enable GitHub Pages: Settings -> Pages -> Build and deployment -> Deploy from a branch -> branch `main`, folder `/docs`.
3. Run the workflow manually once from Actions -> Daily public watchlist -> Run workflow, or wait for the weekday schedule.

The workflow polls from the early weekday morning and publishes after 08:00 Europe/Helsinki once per day, but scheduled runs skip days when Nasdaq Stockholm or Nasdaq Helsinki is closed. GitHub scheduled runs are best-effort, so the report can still drift, but the repeated checks make late starts less likely. It writes public Markdown reports under `docs/reports/` and publishes two top-10 lists:

- Trading ideas, generated with `--strategy trading`.
- Long-term investment ideas, generated with `--strategy long-term`.

Trading ideas require a short-term setup, such as strong momentum, unusual turnover, or an event-style catalyst. On quiet days the trading list may include fewer than 10 names instead of filling the report with generic small-cap ideas.
Both public lists use `--min-country FI:3`, so each top 10 includes at least three Finnish companies when enough Finnish candidates are available.
Long-term reports also include a conviction bucket, a plain-English thesis, and component scores for business quality, valuation, growth, balance sheet, momentum, risk, and data confidence.

The performance page tracks published picks over 1d, 5d, 20d, and 60d horizons. It includes hit rate, average return, downside/risk metrics, broad market context, and same-country equal-weight benchmark comparison when matching market snapshots are available. It summarizes results publicly and may suggest scoring ideas after enough observations, but it does not change ranking weights automatically.

Public pages:

- Latest landing page: `https://vernerisirva.github.io/investmentagent/`
- Latest trading ideas: `https://vernerisirva.github.io/investmentagent/reports/trading/latest.html`
- Latest long-term ideas: `https://vernerisirva.github.io/investmentagent/reports/long-term/latest.html`
- Performance scorecard: `https://vernerisirva.github.io/investmentagent/performance/`
- Dated trading ideas: `https://vernerisirva.github.io/investmentagent/reports/trading/YYYY-MM-DD.html`
- Dated long-term ideas: `https://vernerisirva.github.io/investmentagent/reports/long-term/YYYY-MM-DD.html`

Reports are research triage only. They are not financial advice.
