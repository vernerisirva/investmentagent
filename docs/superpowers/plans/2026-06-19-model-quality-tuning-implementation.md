# Model Quality Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve InvestmentAgent pick quality by tightening long-term promotion, reducing weak generic trading boosts, and adding Yahoo-style valuation fallback when FinImpulse lacks valuation support.

**Architecture:** Keep FinImpulse as the primary enrichment provider and add a focused `FallbackFundamentalsProvider` that tries a secondary provider only when the primary snapshot lacks valuation support. Keep the long-term gate as the authority for research-candidate tiers, but make missing valuation a stronger blocker for promotion unless the company has unusually strong durable evidence. Keep Global AI separate and let it reuse the same fallback provider through explicit symbols.

**Tech Stack:** Python 3.11+, Typer CLI, pytest, dataclasses, existing provider/rendering modules.

---

## File Structure

- Modify `src/investmentagent/fundamentals.py`: add explicit Yahoo symbol lookup, public valuation-support helpers, fallback provider composition, valuation fallback source checks, and merge-only-missing fallback behavior.
- Modify `src/investmentagent/cli.py`: construct FinImpulse plus Yahoo fallback for live watchlists and Global AI reports.
- Modify `src/investmentagent/global_ai.py`: update metadata to reflect `finimpulse+yahoo-fallback` and keep report scoring unchanged except when fallback fields are present.
- Modify `src/investmentagent/scoring.py`: reduce generic high-turnover catalyst scoring and keep explicit momentum scoring unchanged.
- Modify `src/investmentagent/reports.py`: reduce trading-strategy adjustment strength and preserve discovery/small-cap signals.
- Modify `src/investmentagent/long_term_quality.py`: make missing valuation a stronger gate blocker and require extra durable anchors before a missing-valuation row can appear as a research candidate.
- Modify `src/investmentagent/renderers.py`: update long-term empty/main-section wording to say speculative monitors are not primary investment ideas.
- Modify `tests/test_fundamentals.py`: cover explicit Yahoo symbol lookup and fallback provider behavior.
- Modify `tests/test_cli.py`: cover fallback provider wiring for live watchlists and Global AI.
- Modify `tests/test_global_ai.py`: cover valuation fallback appearing in Global AI report output.
- Modify `tests/test_scoring.py`: cover lower high-turnover catalyst score.
- Modify `tests/test_reports.py`: cover reduced trading strategy boost and stricter long-term ranking/presentation.
- Modify `tests/test_long_term_quality.py`: cover missing-valuation demotion and exceptional-quality allowance.

## Task 1: Add Explicit Yahoo Symbol Lookup And Valuation Diagnostics

**Files:**
- Modify: `tests/test_fundamentals.py`
- Modify: `src/investmentagent/fundamentals.py`

- [ ] **Step 1: Write failing tests for explicit Yahoo lookup and valuation coverage**

Add this test near existing Yahoo provider tests in `tests/test_fundamentals.py`:

```python
def test_yahoo_provider_fetches_explicit_global_symbol():
    requested_urls: list[str] = []

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        return yahoo_payload()

    provider = YahooFundamentalsProvider(fetcher=fetcher)

    snapshot = provider.get_fundamentals_for_symbol("msft", fallback_currency="USD")

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "MSFT"
    assert requested_urls == [
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/MSFT"
        "?modules=price,summaryDetail,financialData"
    ]
    assert snapshot.financials.pe_ratio == 11.2
    assert provider.source_check().status == "ok"
    assert "valuation support 1/1" in provider.source_check().detail
```

Add this source-check test below the Yahoo source-check tests:

```python
def test_yahoo_source_check_reports_valuation_coverage():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Yahoo-style lookups parsed" in check.detail
    assert "valuation support 1/1" in check.detail
    assert "direct valuation 1/1" in check.detail
    assert "missing valuation support 0/1" in check.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_yahoo_provider_fetches_explicit_global_symbol tests/test_fundamentals.py::test_yahoo_source_check_reports_valuation_coverage -v
```

Expected: fails because `YahooFundamentalsProvider` has no `get_fundamentals_for_symbol`, and the source check lacks valuation coverage detail.

- [ ] **Step 3: Implement explicit Yahoo lookup and coverage counters**

In `YahooFundamentalsProvider.__init__`, add:

```python
self.valuation_support_lookups = 0
self.direct_valuation_lookups = 0
self.proxy_input_lookups = 0
```

Change `get_fundamentals()` to delegate to a private symbol helper:

```python
def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
    for symbol in yahoo_symbol_candidates(company):
        snapshot = self._get_fundamentals_for_symbol(
            symbol, fallback_currency=company.currency
        )
        if snapshot is not None:
            return snapshot
    return None
```

Add public and private explicit symbol methods:

```python
def get_fundamentals_for_symbol(
    self, symbol: str, fallback_currency: str | None = None
) -> FundamentalsSnapshot | None:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    return self._get_fundamentals_for_symbol(
        normalized_symbol, fallback_currency=fallback_currency
    )


def _get_fundamentals_for_symbol(
    self, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    self.attempted_lookups += 1
    url = _yahoo_quote_summary_url(symbol)
    try:
        snapshot = _parse_fundamentals_payload(
            payload=self._fetcher(url),
            symbol=symbol,
            url=url,
            fallback_currency=fallback_currency,
        )
    except Exception as exc:
        self.last_error = str(exc)
        return None
    if snapshot is None:
        return None
    self._record_valuation_coverage(snapshot)
    self.successful_lookups += 1
    self.last_error = None
    return snapshot
```

Add `_record_valuation_coverage()` to `YahooFundamentalsProvider`:

```python
def _record_valuation_coverage(self, snapshot: FundamentalsSnapshot) -> None:
    financials = snapshot.financials
    if has_valuation_support(financials):
        self.valuation_support_lookups += 1
    if has_any_financial_field(financials, DIRECT_VALUATION_FIELDS):
        self.direct_valuation_lookups += 1
    if has_any_financial_field(financials, PROXY_VALUATION_FIELDS):
        self.proxy_input_lookups += 1
```

Add a Yahoo `_source_detail()` method matching FinImpulse's format but with `Yahoo-style` wording:

```python
def _source_detail(self, ratio: str) -> str:
    return (
        f"{ratio}; valuation support {self.valuation_support_lookups}/"
        f"{self.successful_lookups}; direct valuation "
        f"{self.direct_valuation_lookups}/{self.successful_lookups}; "
        f"proxy inputs {self.proxy_input_lookups}/{self.successful_lookups}; "
        f"missing valuation support "
        f"{self.successful_lookups - self.valuation_support_lookups}/"
        f"{self.successful_lookups}"
    )
```

Update successful and mixed-success `source_check()` returns to use `self._source_detail(ratio)`.

- [ ] **Step 4: Rename valuation helpers to public module helpers**

Rename:

```python
def _has_any_financial_field(...)
def _has_valuation_support(...)
```

to:

```python
def has_any_financial_field(
    financials: FinancialSnapshot, field_names: tuple[str, ...]
) -> bool:
    return any(getattr(financials, field_name) is not None for field_name in field_names)


def has_valuation_support(financials: FinancialSnapshot) -> bool:
    return has_any_financial_field(
        financials, DIRECT_VALUATION_FIELDS + PROXY_VALUATION_FIELDS
    )
```

Update `FinimpulseFundamentalsProvider._record_valuation_coverage()` to call the public helper names.

- [ ] **Step 5: Verify Yahoo tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_yahoo_provider_fetches_explicit_global_symbol tests/test_fundamentals.py::test_yahoo_source_check_reports_valuation_coverage -v
```

Expected: both tests pass.

## Task 2: Add Fallback Fundamentals Provider

**Files:**
- Modify: `tests/test_fundamentals.py`
- Modify: `src/investmentagent/fundamentals.py`

- [ ] **Step 1: Write failing tests for fallback provider behavior**

Import `FallbackFundamentalsProvider` in `tests/test_fundamentals.py`.

Add this helper class near `StaticFundamentalsProvider`:

```python
class SymbolFundamentalsProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.company_requests: list[Company] = []
        self.symbol_requests: list[tuple[str, str | None]] = []

    def get_fundamentals(self, company: Company):
        self.company_requests.append(company)
        return self.snapshot

    def get_fundamentals_for_symbol(self, symbol: str, fallback_currency: str | None = None):
        self.symbol_requests.append((symbol, fallback_currency))
        return self.snapshot

    def source_check(self):
        return SourceCheck("symbol provider", "ok", "fixture provider")
```

Add this test:

```python
def test_fallback_provider_merges_valuation_without_overwriting_profile():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            market_cap_eur_m=3_000_000,
            business_description="FinImpulse profile text",
            ir_url="https://investor.nvidia.com/",
            financials=FinancialSnapshot(
                revenue_growth_pct=51.7,
                operating_margin_pct=55.6,
                debt_to_equity=0.05,
                data_quality=DataQuality.PARTIAL,
            ),
            evidence=Evidence("FinImpulse lookup", "https://finimpulse.example", "finimpulse"),
        )
    )
    fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            market_cap_eur_m=3_100_000,
            financials=FinancialSnapshot(
                pe_ratio=31.2,
                price_to_book=19.0,
                average_daily_value_eur=9_000_000_000,
                data_quality=DataQuality.PARTIAL,
            ),
            evidence=Evidence("Yahoo valuation lookup", "https://yahoo.example", "yahoo"),
        )
    )
    provider = FallbackFundamentalsProvider(primary, fallback)

    snapshot = provider.get_fundamentals_for_symbol("NVDA", fallback_currency="USD")

    assert snapshot is not None
    assert snapshot.business_description == "FinImpulse profile text"
    assert snapshot.ir_url == "https://investor.nvidia.com/"
    assert snapshot.market_cap_eur_m == 3_000_000
    assert snapshot.financials.pe_ratio == 31.2
    assert snapshot.financials.revenue_growth_pct == 51.7
    assert snapshot.evidence.source == "finimpulse"
    assert fallback.symbol_requests == [("NVDA", "USD")]
```

Add this test:

```python
def test_fallback_provider_skips_fallback_when_primary_has_valuation():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="KAR.ST",
            financials=FinancialSnapshot(pe_ratio=12.0, data_quality=DataQuality.PARTIAL),
        )
    )
    fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="KAR.ST",
            financials=FinancialSnapshot(pe_ratio=9.0, data_quality=DataQuality.PARTIAL),
        )
    )
    provider = FallbackFundamentalsProvider(primary, fallback)

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.financials.pe_ratio == 12.0
    assert fallback.company_requests == []
```

Add this test:

```python
def test_fallback_provider_source_checks_include_both_providers():
    primary = SymbolFundamentalsProvider(None)
    fallback = SymbolFundamentalsProvider(None)
    provider = FallbackFundamentalsProvider(primary, fallback)

    checks = provider.source_checks()

    assert [check.name for check in checks] == [
        "symbol provider",
        "symbol provider",
        "valuation fallback",
    ]
    assert checks[-1].status == "warning"
    assert "0 fallback valuation enrichments" in checks[-1].detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_fallback_provider_merges_valuation_without_overwriting_profile tests/test_fundamentals.py::test_fallback_provider_skips_fallback_when_primary_has_valuation tests/test_fundamentals.py::test_fallback_provider_source_checks_include_both_providers -v
```

Expected: import failure for `FallbackFundamentalsProvider`.

- [ ] **Step 3: Implement fallback provider**

Add this class after `FinimpulseFundamentalsProvider` in `src/investmentagent/fundamentals.py`:

```python
class FallbackFundamentalsProvider:
    def __init__(self, primary_provider, fallback_provider) -> None:
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.fallback_attempts = 0
        self.fallback_successes = 0
        self.fallback_valuation_successes = 0

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        primary = self.primary_provider.get_fundamentals(company)
        if primary is not None and has_valuation_support(primary.financials):
            return primary
        self.fallback_attempts += 1
        fallback = self.fallback_provider.get_fundamentals(company)
        return self._merge(primary, fallback)

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ) -> FundamentalsSnapshot | None:
        primary_lookup = getattr(self.primary_provider, "get_fundamentals_for_symbol")
        primary = primary_lookup(symbol, fallback_currency=fallback_currency)
        if primary is not None and has_valuation_support(primary.financials):
            return primary
        self.fallback_attempts += 1
        fallback_lookup = getattr(self.fallback_provider, "get_fundamentals_for_symbol")
        fallback = fallback_lookup(symbol, fallback_currency=fallback_currency)
        return self._merge(primary, fallback)

    def source_check(self) -> SourceCheck:
        if self.fallback_attempts == 0:
            return SourceCheck(
                "valuation fallback",
                "warning",
                "No fallback valuation lookups attempted",
            )
        status = "ok" if self.fallback_valuation_successes else "warning"
        return SourceCheck(
            "valuation fallback",
            status,
            (
                f"{self.fallback_successes}/{self.fallback_attempts} fallback "
                f"lookups parsed; {self.fallback_valuation_successes} fallback "
                "valuation enrichments"
            ),
        )

    def source_checks(self):
        checks = []
        for provider in (self.primary_provider, self.fallback_provider):
            source_checks = getattr(provider, "source_checks", None)
            if callable(source_checks):
                checks.extend(source_checks())
                continue
            source_check = getattr(provider, "source_check", None)
            if callable(source_check):
                checks.append(source_check())
        checks.append(self.source_check())
        return checks

    def _merge(
        self,
        primary: FundamentalsSnapshot | None,
        fallback: FundamentalsSnapshot | None,
    ) -> FundamentalsSnapshot | None:
        if fallback is None:
            return primary
        self.fallback_successes += 1
        if has_valuation_support(fallback.financials):
            self.fallback_valuation_successes += 1
        if primary is None:
            return fallback
        return replace(
            primary,
            financials=_merge_financials(primary.financials, fallback.financials),
        )
```

Keep `_merge_financials()` as the existing merge-only-missing helper so fallback does not overwrite FinImpulse fields.

- [ ] **Step 4: Verify fallback tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_fallback_provider_merges_valuation_without_overwriting_profile tests/test_fundamentals.py::test_fallback_provider_skips_fallback_when_primary_has_valuation tests/test_fundamentals.py::test_fallback_provider_source_checks_include_both_providers -v
```

Expected: all selected tests pass.

## Task 3: Wire Fallback Provider Into CLI And Global AI

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_global_ai.py`
- Modify: `src/investmentagent/cli.py`
- Modify: `src/investmentagent/global_ai.py`

- [ ] **Step 1: Write failing CLI wiring tests**

In `tests/test_cli.py`, update imports and add this test near existing fundamentals wiring tests:

```python
def test_watchlist_finimpulse_wraps_yahoo_valuation_fallback(monkeypatch):
    wrapped = {}

    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class FinimpulseProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    class YahooProvider:
        pass

    class FallbackProvider:
        def __init__(self, primary_provider, fallback_provider):
            wrapped["primary_provider"] = primary_provider
            wrapped["fallback_provider"] = fallback_provider

    class EnrichedProvider:
        def __init__(self, base_provider, fundamentals_provider, max_enrichments=None):
            wrapped["fundamentals_provider"] = fundamentals_provider
            self.base_provider = base_provider

        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return self.base_provider.source_checks()

    monkeypatch.setenv("FINIMPULSE_API_KEY", "finimpulse-token")
    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "FinimpulseFundamentalsProvider", FinimpulseProvider)
    monkeypatch.setattr(cli, "YahooFundamentalsProvider", YahooProvider)
    monkeypatch.setattr(cli, "FallbackFundamentalsProvider", FallbackProvider)
    monkeypatch.setattr(cli, "EnrichedResearchProvider", EnrichedProvider)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--limit", "3"])

    assert result.exit_code == 0
    assert isinstance(wrapped["fundamentals_provider"], FallbackProvider)
    assert isinstance(wrapped["primary_provider"], FinimpulseProvider)
    assert isinstance(wrapped["fallback_provider"], YahooProvider)
```

Add this Global AI wiring test:

```python
def test_global_ai_top5_uses_yahoo_valuation_fallback(monkeypatch):
    wrapped = {}

    class FinimpulseProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    class YahooProvider:
        pass

    class FallbackProvider:
        def __init__(self, primary_provider, fallback_provider):
            wrapped["primary_provider"] = primary_provider
            wrapped["fallback_provider"] = fallback_provider

    def build_report(provider, limit, generated_at):
        wrapped["provider"] = provider
        return cli.build_global_ai_top5(provider, limit=limit, generated_at=generated_at)

    monkeypatch.setenv("FINIMPULSE_API_KEY", "finimpulse-token")
    monkeypatch.setattr(cli, "FinimpulseFundamentalsProvider", FinimpulseProvider)
    monkeypatch.setattr(cli, "YahooFundamentalsProvider", YahooProvider)
    monkeypatch.setattr(cli, "FallbackFundamentalsProvider", FallbackProvider)
    monkeypatch.setattr(cli, "build_global_ai_top5", lambda provider, limit, generated_at: sample_cli_global_ai_report())

    result = runner.invoke(app, ["global-ai", "top-5", "--limit", "1"])

    assert result.exit_code == 0
    assert isinstance(wrapped["primary_provider"], FinimpulseProvider)
    assert isinstance(wrapped["fallback_provider"], YahooProvider)
```

Use the existing `snapshot_for()` helper to create `sample_cli_global_ai_report()` or import the report dataclasses and create a one-item report directly.

- [ ] **Step 2: Write failing Global AI fallback output test**

In `tests/test_global_ai.py`, add:

```python
def test_build_global_ai_top5_includes_fallback_valuation():
    entry = valid_universe_entry(
        name="Fallback AI",
        ticker="FALL",
        provider_symbol="FALL",
    )
    provider = StaticFundamentalsProvider(
        {
            "FALL": snapshot_for(
                symbol="FALL",
                pe_ratio=24,
                price_to_book=5,
                operating_margin_pct=30,
                revenue_growth_pct=18,
            )
        }
    )

    report = build_global_ai_top5(
        provider,
        entries=(entry,),
        limit=1,
        generated_at="2026-06-19 08:00 EEST",
    )

    assert report.metadata["fundamentals"] == "finimpulse+yahoo-fallback"
    assert report.items[0].valuation_summary == "P/E 24; P/B 5"
    assert "missing valuation support" not in report.items[0].risk_flags
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_cli.py::test_watchlist_finimpulse_wraps_yahoo_valuation_fallback tests/test_global_ai.py::test_build_global_ai_top5_includes_fallback_valuation -v
```

Expected: CLI import/wiring test fails because no fallback provider is imported; Global AI metadata still says `finimpulse`.

- [ ] **Step 4: Implement CLI fallback wiring**

In `src/investmentagent/cli.py`, import `FallbackFundamentalsProvider`:

```python
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FallbackFundamentalsProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    YahooFundamentalsProvider,
)
```

In the live watchlist fundamentals block, replace the FinImpulse branch with:

```python
elif effective_fundamentals == "finimpulse":
    fundamentals_provider = FallbackFundamentalsProvider(
        FinimpulseFundamentalsProvider(finimpulse_api_key),
        YahooFundamentalsProvider(),
    )
```

In `global_ai_top5()`, replace:

```python
provider = FinimpulseFundamentalsProvider(finimpulse_api_key)
```

with:

```python
provider = FallbackFundamentalsProvider(
    FinimpulseFundamentalsProvider(finimpulse_api_key),
    YahooFundamentalsProvider(),
)
```

- [ ] **Step 5: Update Global AI metadata**

In `src/investmentagent/global_ai.py`, change:

```python
"fundamentals": "finimpulse",
```

to:

```python
"fundamentals": "finimpulse+yahoo-fallback",
```

- [ ] **Step 6: Verify CLI and Global AI tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_cli.py::test_watchlist_finimpulse_wraps_yahoo_valuation_fallback tests/test_global_ai.py::test_build_global_ai_top5_includes_fallback_valuation -v
```

Expected: selected tests pass.

## Task 4: Tune Trading Signal Weights

**Files:**
- Modify: `tests/test_scoring.py`
- Modify: `tests/test_reports.py`
- Modify: `src/investmentagent/scoring.py`
- Modify: `src/investmentagent/reports.py`

- [ ] **Step 1: Write failing high-turnover catalyst score test**

In `tests/test_scoring.py`, add:

```python
def test_high_live_turnover_is_low_confidence_catalyst():
    research = make_research(
        catalysts=("High live turnover",),
        financials=FinancialSnapshot(data_quality=DataQuality.GOOD),
        data_quality=DataQuality.GOOD,
    )

    score = score_research(research)

    assert score.catalyst == 3.0
    assert score.total == 3.0
```

Use the existing helper names in `tests/test_scoring.py`; if the helper takes different arguments, create a local `CompanyResearch` with `Company`, `FinancialSnapshot`, and `ListingSegment.MAIN_MARKET`.

- [ ] **Step 2: Write failing trading strategy adjustment test**

In `tests/test_reports.py`, add:

```python
def test_trading_strategy_adjustment_is_smaller_than_discovery_support():
    research = make_research(
        ticker="TURN",
        catalysts=("High live turnover",),
        financials=FinancialSnapshot(
            average_daily_value_eur=2_000_000,
            data_quality=DataQuality.GOOD,
        ),
        data_quality=DataQuality.GOOD,
    )

    score = _score_for_strategy(research, "trading")

    assert score.catalyst <= 8.0
    assert "trading strategy adjustment applied" in score.reasons
```

Import `_score_for_strategy` from `investmentagent.reports` if it is not already imported.

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_scoring.py::test_high_live_turnover_is_low_confidence_catalyst tests/test_reports.py::test_trading_strategy_adjustment_is_smaller_than_discovery_support -v
```

Expected: high-turnover catalyst is still 8, and trading adjustment pushes catalyst above the expected ceiling.

- [ ] **Step 4: Reduce high-turnover score**

In `src/investmentagent/scoring.py`, change:

```python
LIVE_CATALYST_SCORES = {
    "Live price available from Nasdaq Nordic": 2.0,
    "High live turnover": 8.0,
    "Moderate live turnover": 4.0,
}
```

to:

```python
LIVE_CATALYST_SCORES = {
    "Live price available from Nasdaq Nordic": 2.0,
    "High live turnover": 3.0,
    "Moderate live turnover": 2.0,
}
```

- [ ] **Step 5: Reduce trading strategy adjustment**

In `_score_for_strategy()` in `src/investmentagent/reports.py`, find the trading strategy branch and reduce the added catalyst boost. Use:

```python
if strategy == "trading":
    if _has_trading_setup(research):
        return replace(
            score,
            catalyst=round(score.catalyst + 3.0, 2),
            total=round(score.total + 3.0, 2),
            reasons=(*score.reasons, "trading strategy adjustment applied"),
        )
    return score
```

If the current branch contains a larger numeric value, only change the number and keep existing structure.

- [ ] **Step 6: Verify scoring tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_scoring.py tests/test_reports.py -v
```

Expected: all scoring and report tests pass.

## Task 5: Tighten Long-Term Gate And Report Wording

**Files:**
- Modify: `tests/test_long_term_quality.py`
- Modify: `tests/test_reports.py`
- Modify: `src/investmentagent/long_term_quality.py`
- Modify: `src/investmentagent/renderers.py`

- [ ] **Step 1: Write failing missing-valuation demotion test**

In `tests/test_long_term_quality.py`, add:

```python
def test_missing_valuation_requires_exceptional_durable_anchors_for_research_candidate():
    decision = assess_long_term_gate(
        make_research(
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            revenue_growth_pct=12.0,
            operating_margin_pct=15.0,
            debt_to_equity=0.2,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        )
    )

    assert decision.tier == LongTermGateTier.SPECULATIVE_MONITOR
    assert "missing valuation support" in decision.blockers
```

Add this allowance test:

```python
def test_missing_valuation_can_remain_watchlist_only_with_exceptional_quality():
    decision = assess_long_term_gate(
        make_research(
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=25.0,
            revenue_growth_pct=30.0,
            operating_margin_pct=25.0,
            debt_to_equity=0.1,
            average_daily_value_eur=600_000,
            data_quality=DataQuality.GOOD,
        )
    )

    assert decision.tier == LongTermGateTier.FUNDAMENTAL_WATCHLIST
    assert "missing valuation support" in decision.blockers
```

- [ ] **Step 2: Write failing report wording test**

In `tests/test_reports.py`, add or update a long-term markdown test:

```python
def test_long_term_report_marks_speculative_monitors_as_not_primary_ideas():
    item = WatchlistItem(
        rank=1,
        research=make_research(
            ticker="SPEC",
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            revenue_growth_pct=4.0,
            operating_margin_pct=None,
            average_daily_value_eur=120_000,
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0,
            discovery=10,
            catalyst=0,
            risk_penalty=0,
            data_quality_penalty=7,
            total=3,
        ),
    )

    markdown = render_watchlist_report_markdown(
        [item],
        {"strategy": "long-term"},
        [],
    )

    assert "not primary long-term investment ideas" in markdown
```

Use existing report-test helpers if they already create `WatchlistItem` objects.

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_long_term_quality.py::test_missing_valuation_requires_exceptional_durable_anchors_for_research_candidate tests/test_long_term_quality.py::test_missing_valuation_can_remain_watchlist_only_with_exceptional_quality tests/test_reports.py::test_long_term_report_marks_speculative_monitors_as_not_primary_ideas -v
```

Expected: current gate promotes one or both missing-valuation rows too highly, and wording does not contain the new phrase.

- [ ] **Step 4: Implement stricter missing valuation gate**

In `assess_long_term_gate()` in `src/investmentagent/long_term_quality.py`, after tier is initially assigned and before returning, add:

```python
missing_valuation = not valuation.has_support
exceptional_without_valuation = (
    missing_valuation
    and len(durable_anchors) >= 5
    and quality.bucket
    in {
        LongTermQualityBucket.QUALITY_SMALL_CAP,
        LongTermQualityBucket.FUNDAMENTAL_WATCHLIST,
    }
    and research.data_quality == DataQuality.GOOD
)

if missing_valuation and tier == LongTermGateTier.HIGH_CONVICTION:
    tier = LongTermGateTier.FUNDAMENTAL_WATCHLIST
if (
    missing_valuation
    and tier == LongTermGateTier.FUNDAMENTAL_WATCHLIST
    and not exceptional_without_valuation
):
    tier = LongTermGateTier.SPECULATIVE_MONITOR
```

Keep the existing high-conviction demotion guard, but ensure this stricter guard executes after it so missing valuation cannot slip into research tiers without exceptional evidence.

- [ ] **Step 5: Update renderer wording**

In `_long_term_markdown_sections()` in `src/investmentagent/renderers.py`, change the no-research note to:

```python
"_No long-term research candidates passed the gate today. "
"Rows below are speculative monitors or evidence-audit rows, "
"not primary long-term investment ideas._"
```

In the speculative monitor section, add a short note immediately after the heading:

```python
if tier == LongTermGateTier.SPECULATIVE_MONITOR:
    lines.extend(
        [
            "_These are not primary long-term investment ideas; they need "
            "valuation or stronger proof before promotion._",
            "",
        ]
    )
```

- [ ] **Step 6: Verify long-term tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_long_term_quality.py tests/test_reports.py -v
```

Expected: all long-term and report tests pass.

## Task 6: Full Verification And Publish

**Files:**
- All modified files from prior tasks.

- [ ] **Step 1: Run targeted model-quality tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py tests/test_cli.py tests/test_global_ai.py tests/test_scoring.py tests/test_reports.py tests/test_long_term_quality.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Inspect generated behavior with fixture provider**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m investmentagent.cli watchlist --strategy long-term --provider fixture --limit 5
```

Expected: output renders and speculative rows, if any, are clearly separated by the long-term gate wording.

- [ ] **Step 4: Commit feature branch**

Run:

```bash
git status --short
git add src/investmentagent/fundamentals.py src/investmentagent/cli.py src/investmentagent/global_ai.py src/investmentagent/scoring.py src/investmentagent/reports.py src/investmentagent/long_term_quality.py src/investmentagent/renderers.py tests/test_fundamentals.py tests/test_cli.py tests/test_global_ai.py tests/test_scoring.py tests/test_reports.py tests/test_long_term_quality.py
git commit -m "feat: tune model quality and valuation fallback"
```

- [ ] **Step 5: Fast-forward main and scheduler branch**

Run from `/Users/vernerisirva1/Documents/Investmentagent`:

```bash
git fetch origin main codex/investmentagent-live-data
git pull --ff-only origin main
git merge --ff-only codex/model-quality-tuning
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest
git push origin main
git push origin main:codex/investmentagent-live-data
```

Expected: push succeeds to both branches.

## Acceptance Criteria

- FinImpulse remains primary enrichment, with Yahoo-style valuation fallback only when valuation support is missing.
- Explicit Yahoo symbol lookup works for Global AI symbols.
- Fallback provider source checks show attempted and valuation-rich fallback coverage.
- Global AI report metadata shows `finimpulse+yahoo-fallback`.
- Global AI rows include valuation summaries when fallback provides direct multiples.
- Generic high-turnover and trading-adjustment boosts are lower.
- Missing valuation demotes ordinary long-term rows out of primary research tiers.
- Exceptional missing-valuation rows can appear only as fundamental watchlist, not high conviction.
- Speculative monitors remain visible but are explicitly labeled as not primary long-term investment ideas.
- Full pytest suite passes.
