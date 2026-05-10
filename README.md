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

## Current data mode

V1 starts with bundled fixture data so the scoring, reports, and CLI can be tested deterministically. The provider boundary is intentionally separate from scoring and rendering so future free-source fetchers can replace or augment the fixture provider.

## Scoring model

The score is transparent:

```text
total score = value score + discovery score + catalyst score - risk penalty - data quality penalty
```

Every report should show reasons, risks, data quality, and evidence links.
