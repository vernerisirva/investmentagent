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
