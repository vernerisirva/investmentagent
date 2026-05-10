# Watchlist Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add strategy-aware live watchlists so InvestmentAgent separates balanced investment candidates, long-term ideas, trading ideas, discovery names, and raw momentum movers.

**Architecture:** Keep the provider responsible for extracting live facts and risks from Nasdaq Nordic rows. Keep the scoring engine as the base score, then apply a small strategy adjustment in `reports.py` before sorting and ranking. Keep the CLI as a thin option parser that validates strategy input and records it in saved report metadata.

**Tech Stack:** Python 3.11+, Typer CLI, pytest, dataclasses, local fixture tests, Nasdaq Nordic live provider.

---

## File Structure

- Modify `src/investmentagent/providers.py`: add live risk labels and deduplicate Nasdaq screener rows by `(ticker, country)`.
- Modify `src/investmentagent/reports.py`: add strategy validation, strategy score adjustment, and strategy-aware `build_watchlist`.
- Modify `src/investmentagent/cli.py`: add `--strategy` option, validate before provider creation, pass strategy to reports, and save it in metadata.
- Modify `tests/test_providers.py`: cover new live risks and duplicate ticker handling.
- Modify `tests/test_reports.py`: cover strategy ranking/filtering behavior.
- Modify `tests/test_cli.py`: cover CLI validation and saved metadata.

## Task 1: Live Provider Risk Signals And Deduplication

**Files:**
- Modify: `src/investmentagent/providers.py`
- Test: `tests/test_providers.py`

- [ ] **Step 1: Add failing provider tests**

Add these tests to `tests/test_providers.py` after the existing live signal tests:

```python
def test_live_provider_research_adds_extreme_spike_and_low_price_risks():
    payload = LIVE_NASDAQ_SCREENER_RESPONSE.replace("+6.25%", "+155.65%").replace(
        "34.90", "0.86"
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: payload)

    research = provider.get_research("ACAST")

    assert "Extreme intraday spike" in research.risks
    assert "Speculative low-price share" in research.risks


def test_live_provider_deduplicates_nasdaq_rows_by_ticker_and_country():
    duplicate_payload = LIVE_NASDAQ_SCREENER_RESPONSE.replace(
        '"fullName": "Foreign Issuer Listed Stockholm"',
        '"fullName": "Acast Duplicate"',
    ).replace('"symbol": "FIL"', '"symbol": "ACAST"').replace(
        '"isin": "DK0000000001"', '"isin": "SE0015960935"'
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: duplicate_payload)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies].count("ACAST") == 1
```

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
python -m pytest tests/test_providers.py::test_live_provider_research_adds_extreme_spike_and_low_price_risks tests/test_providers.py::test_live_provider_deduplicates_nasdaq_rows_by_ticker_and_country -q
```

Expected: the first test fails because the risks do not exist yet. The second test fails because deduplication currently includes exchange in the key.

- [ ] **Step 3: Implement provider changes**

In `src/investmentagent/providers.py`, change the dedupe key in `_parse_nasdaq_nordic_screener_responses` from:

```python
seen: set[tuple[str, str, str]] = set()
...
key = (company.ticker, company.country, company.exchange)
```

to:

```python
seen: set[tuple[str, str]] = set()
...
key = (company.ticker, company.country)
```

Then update `_live_market_risks` to include:

```python
price = market_row.get("price")
if percentage_change is not None and percentage_change >= 40.0:
    risks.append("Extreme intraday spike")
if price is not None and 0 < price < 1.0:
    risks.append("Speculative low-price share")
```

Keep the existing selloff, low turnover, and missing turnover rules.

- [ ] **Step 4: Run provider tests and verify pass**

Run:

```bash
python -m pytest tests/test_providers.py -q
```

Expected: all provider tests pass.

- [ ] **Step 5: Commit provider work**

Run:

```bash
git add src/investmentagent/providers.py tests/test_providers.py
git commit -m "feat: flag risky live market rows"
```

## Task 2: Strategy-Aware Watchlist Ranking

**Files:**
- Modify: `src/investmentagent/reports.py`
- Test: `tests/test_reports.py`

- [ ] **Step 1: Add failing report strategy tests**

In `tests/test_reports.py`, update `make_research` to accept optional `catalysts`, `risks`, and `segment` parameters:

```python
def make_research(
    ticker: str,
    *,
    pe_ratio: float | None = 10.0,
    price_to_book: float | None = 1.0,
    net_cash_eur_m: float | None = 5.0,
    price: float | None = None,
    currency: str | None = None,
    catalysts=(),
    risks=(),
    segment: ListingSegment = ListingSegment.MAIN_MARKET,
    data_quality: DataQuality = DataQuality.GOOD,
    evidence=(),
) -> CompanyResearch:
    company = Company(
        name=f"{ticker} AB",
        ticker=ticker,
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=segment,
        sector="Industrials",
        market_cap_eur_m=200,
    )
    financials = FinancialSnapshot(
        price=price,
        currency=currency,
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        net_cash_eur_m=net_cash_eur_m,
        data_quality=data_quality,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        catalysts=tuple(catalysts),
        risks=tuple(risks),
        evidence=evidence,
        data_quality=data_quality,
    )
```

Add these tests after the existing watchlist filter tests:

```python
def test_balanced_strategy_ranks_extreme_spikes_below_orderly_candidates():
    provider = FakeResearchProvider(
        (
            make_research(
                "SPIKE",
                catalysts=("Strong intraday momentum (+155.65%)", "High live turnover"),
                risks=("Sparse live-source data", "Extreme intraday spike"),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "ORDERLY",
                catalysts=("Positive intraday momentum (+6.25%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="balanced"
    )

    assert [item.research.company.ticker for item in items] == ["ORDERLY", "SPIKE"]


def test_momentum_strategy_can_surface_extreme_spikes():
    provider = FakeResearchProvider(
        (
            make_research(
                "SPIKE",
                catalysts=("Strong intraday momentum (+155.65%)", "High live turnover"),
                risks=("Sparse live-source data", "Extreme intraday spike"),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "ORDERLY",
                catalysts=("Positive intraday momentum (+6.25%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="momentum"
    )

    assert items[0].research.company.ticker == "SPIKE"


def test_long_term_strategy_discounts_intraday_trading_setup():
    provider = FakeResearchProvider(
        (
            make_research(
                "TRADER",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("Strong intraday momentum (+12.93%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "VALUE",
                pe_ratio=9.0,
                price_to_book=0.9,
                net_cash_eur_m=20.0,
                catalysts=("Moderate live turnover",),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.PARTIAL,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert items[0].research.company.ticker == "VALUE"


def test_build_watchlist_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategy must be one of"):
        build_watchlist(
            FixtureResearchProvider(),
            countries=("SE", "FI"),
            limit=1,
            include_first_north=True,
            strategy="bad",
        )
```

- [ ] **Step 2: Run report tests and verify failure**

Run:

```bash
python -m pytest tests/test_reports.py::test_balanced_strategy_ranks_extreme_spikes_below_orderly_candidates tests/test_reports.py::test_momentum_strategy_can_surface_extreme_spikes tests/test_reports.py::test_long_term_strategy_discounts_intraday_trading_setup tests/test_reports.py::test_build_watchlist_rejects_unknown_strategy -q
```

Expected: failures because `build_watchlist` does not accept `strategy`.

- [ ] **Step 3: Implement strategy helpers**

In `src/investmentagent/reports.py`, add constants and helpers near the top:

```python
WATCHLIST_STRATEGIES = ("balanced", "long-term", "trading", "momentum", "discovery")


def normalize_watchlist_strategy(strategy: str) -> str:
    normalized = strategy.strip().lower()
    if normalized not in WATCHLIST_STRATEGIES:
        allowed = ", ".join(WATCHLIST_STRATEGIES)
        raise ValueError(f"strategy must be one of: {allowed}")
    return normalized
```

Add a strategy adjustment helper:

```python
def _strategy_adjustment(research: CompanyResearch, strategy: str) -> float:
    risks = set(research.risks)
    catalysts = set(research.catalysts)
    adjustment = 0.0

    if strategy == "momentum":
        return 0.0

    if "Extreme intraday spike" in risks:
        adjustment -= 18.0
    if "Missing live turnover" in risks:
        adjustment -= 12.0
    if "Low live turnover" in risks:
        adjustment -= 10.0
    if "Speculative low-price share" in risks:
        adjustment -= 8.0

    if strategy == "long-term":
        if any("intraday momentum" in catalyst for catalyst in catalysts):
            adjustment -= 10.0
        if research.financials.pe_ratio is not None and research.financials.pe_ratio <= 12:
            adjustment += 6.0
        if research.financials.price_to_book is not None and research.financials.price_to_book <= 1.2:
            adjustment += 4.0
        if research.financials.net_cash_eur_m is not None and research.financials.net_cash_eur_m > 0:
            adjustment += 4.0
    elif strategy == "trading":
        if "High live turnover" in catalysts:
            adjustment += 6.0
        if "Moderate live turnover" in catalysts:
            adjustment += 3.0
        if any(catalyst.startswith("Strong intraday momentum") for catalyst in catalysts):
            adjustment += 5.0
        if "Extreme intraday spike" in risks:
            adjustment -= 8.0
    elif strategy == "discovery":
        if research.company.segment == ListingSegment.FIRST_NORTH:
            adjustment += 4.0
        if "Extreme intraday spike" in risks or "Missing live turnover" in risks:
            adjustment -= 10.0

    return adjustment
```

Import `ListingSegment` and `ScoreBreakdown` from `investmentagent.models`.

- [ ] **Step 4: Apply strategy in `build_watchlist`**

Change the function signature:

```python
def build_watchlist(
    provider: ResearchProvider,
    countries: tuple[str, ...],
    limit: int,
    include_first_north: bool,
    min_market_cap: float | None = None,
    max_market_cap: float | None = None,
    sector: str | None = None,
    strategy: str = "balanced",
) -> list[WatchlistItem]:
```

After the limit check, normalize the strategy:

```python
strategy = normalize_watchlist_strategy(strategy)
```

Replace direct `score_research(research)` construction with:

```python
base_score = score_research(research)
adjusted_total = round(base_score.total + _strategy_adjustment(research, strategy), 2)
score = ScoreBreakdown(
    value=base_score.value,
    discovery=base_score.discovery,
    catalyst=base_score.catalyst,
    risk_penalty=base_score.risk_penalty,
    data_quality_penalty=base_score.data_quality_penalty,
    total=adjusted_total,
    reasons=base_score.reasons,
    warnings=base_score.warnings,
)
scored_items.append(WatchlistItem(rank=0, research=research, score=score))
```

- [ ] **Step 5: Run report tests and verify pass**

Run:

```bash
python -m pytest tests/test_reports.py -q
```

Expected: all report tests pass.

- [ ] **Step 6: Commit report work**

Run:

```bash
git add src/investmentagent/reports.py tests/test_reports.py
git commit -m "feat: add watchlist strategy ranking"
```

## Task 3: CLI Strategy Option And Saved Metadata

**Files:**
- Modify: `src/investmentagent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

In `tests/test_cli.py`, add these tests near the watchlist validation tests:

```python
def test_watchlist_accepts_strategy_option():
    result = runner.invoke(app, ["watchlist", "--strategy", "long-term", "--limit", "1"])

    assert result.exit_code == 0
    assert "#1" in result.output


def test_watchlist_rejects_invalid_strategy_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid strategy")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--strategy", "bad"])

    assert result.exit_code != 0
    assert "strategy must be one of" in result.output


def test_watchlist_saves_strategy_metadata():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--strategy",
                "trading",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["strategy"] == "trading"
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
python -m pytest tests/test_cli.py::test_watchlist_accepts_strategy_option tests/test_cli.py::test_watchlist_rejects_invalid_strategy_before_provider_work tests/test_cli.py::test_watchlist_saves_strategy_metadata -q
```

Expected: failures because `--strategy` does not exist.

- [ ] **Step 3: Implement CLI option**

In `src/investmentagent/cli.py`, import `normalize_watchlist_strategy`:

```python
from investmentagent.reports import build_deep_dive, build_watchlist, normalize_watchlist_strategy
```

Add this option to `watchlist` before `output`:

```python
strategy: str = typer.Option(
    "balanced",
    "--strategy",
    help="Watchlist strategy: balanced, long-term, trading, momentum, or discovery.",
),
```

Normalize before provider creation:

```python
normalized_strategy = normalize_watchlist_strategy(strategy)
```

Pass it into `build_watchlist`:

```python
strategy=normalized_strategy,
```

Add it to saved metadata:

```python
"strategy": normalized_strategy,
```

- [ ] **Step 4: Run CLI tests and verify pass**

Run:

```bash
python -m pytest tests/test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit CLI work**

Run:

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: expose watchlist strategies in cli"
```

## Task 4: Full Verification And Live Smoke Test

**Files:**
- No code changes expected unless tests reveal an issue.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run fixture CLI smoke tests**

Run:

```bash
investmentagent watchlist --strategy balanced --limit 3
investmentagent watchlist --strategy long-term --limit 3
investmentagent watchlist --strategy trading --limit 3
```

Expected: each command exits successfully and prints ranked watchlist text.

- [ ] **Step 3: Run live CLI smoke tests**

Run:

```bash
investmentagent watchlist --provider live --country se,fi --limit 10 --strategy balanced
investmentagent watchlist --provider live --country se,fi --limit 10 --strategy trading
investmentagent watchlist --provider live --country se,fi --limit 10 --strategy long-term
```

Expected: each command exits successfully. `balanced` and `long-term` should no longer be dominated by extreme one-day spikes. `trading` may show stronger daily movers, but risks should be visible.

- [ ] **Step 4: Save a report metadata smoke test**

Run:

```bash
investmentagent watchlist --provider live --country se,fi --limit 10 --strategy balanced --save reports/watchlists/$(date +%F)-balanced.md
```

Expected: a Markdown report is saved, and its metadata contains `strategy: balanced`.

- [ ] **Step 5: Push commits**

Run:

```bash
git push origin main
```

Expected: GitHub branch `main` receives the strategy implementation commits.
