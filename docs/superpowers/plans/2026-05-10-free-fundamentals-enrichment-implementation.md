# Free Fundamentals Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich live Sweden/Finland watchlists and deep dives with best-effort free fundamentals so `long-term` and `balanced` strategies can use real valuation and financial signals.

**Architecture:** Add a new `fundamentals.py` module for source-specific fundamentals lookup and merge logic. Keep `LiveNasdaqNordicProvider` focused on listings/live market data, then wrap it with an `EnrichedResearchProvider` when fundamentals mode is `free`. Add CLI plumbing through `--fundamentals off|free` without requiring internet in tests by using injectable fetchers and fixture responses.

**Tech Stack:** Python 3.11+, dataclasses, urllib JSON fetches, Typer CLI, pytest.

---

## File Structure

- Create `src/investmentagent/fundamentals.py`: fundamentals dataclass, Yahoo-style adapter, ticker candidate generation, merge helpers, enriched provider wrapper.
- Modify `src/investmentagent/providers.py`: no planned production edits; provider protocol compatibility is handled by duck-typing existing `get_company_research`.
- Modify `src/investmentagent/cli.py`: add `--fundamentals off|free`, wrap live provider when enabled, save metadata.
- Modify `src/investmentagent/reports.py`: no scoring rewrite expected, but use enriched company data returned by the provider.
- Test `tests/test_fundamentals.py`: unit tests for ticker mapping, parsing, enrichment, and best-effort failure behavior.
- Modify `tests/test_cli.py`: CLI option validation and saved report metadata.
- Modify `tests/test_reports.py`: long-term strategy ranks enriched value candidate above pure intraday mover through provider wrapper.

## Task 1: Fundamentals Module And Yahoo-Style Parsing

**Files:**
- Create: `src/investmentagent/fundamentals.py`
- Create: `tests/test_fundamentals.py`

- [ ] **Step 1: Add failing fundamentals tests**

Create `tests/test_fundamentals.py`:

```python
import json

from investmentagent.fundamentals import (
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    yahoo_symbol_candidates,
)
from investmentagent.models import Company, DataQuality, ListingSegment


def make_company(
    ticker: str = "KAR",
    country: str = "SE",
    name: str = "Karnov Group AB",
) -> Company:
    return Company(
        name=name,
        ticker=ticker,
        country=country,
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        currency="SEK" if country == "SE" else "EUR",
    )


def yahoo_payload() -> str:
    return json.dumps(
        {
            "quoteSummary": {
                "result": [
                    {
                        "price": {
                            "shortName": "Karnov Group AB",
                            "currency": "SEK",
                            "marketCap": {"raw": 5_500_000_000},
                        },
                        "summaryDetail": {
                            "trailingPE": {"raw": 11.2},
                            "priceToBook": {"raw": 1.1},
                            "averageDailyVolume10Day": {"raw": 250_000},
                            "previousClose": {"raw": 110.0},
                        },
                        "financialData": {
                            "revenueGrowth": {"raw": 0.08},
                            "operatingMargins": {"raw": 0.14},
                            "debtToEquity": {"raw": 52.0},
                            "totalCash": {"raw": 900_000_000},
                            "totalDebt": {"raw": 650_000_000},
                        },
                    }
                ],
                "error": None,
            }
        }
    )


def test_yahoo_symbol_candidates_for_sweden_and_finland():
    assert yahoo_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert yahoo_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_yahoo_symbol_candidates_normalize_spaces_and_share_classes():
    assert yahoo_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_yahoo_provider_parses_fundamentals_with_evidence():
    requested_urls: list[str] = []

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        return yahoo_payload()

    provider = YahooFundamentalsProvider(fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 550.0
    assert snapshot.financials.pe_ratio == 11.2
    assert snapshot.financials.price_to_book == 1.1
    assert snapshot.financials.revenue_growth_pct == 8.0
    assert snapshot.financials.operating_margin_pct == 14.0
    assert snapshot.financials.debt_to_equity == 0.52
    assert snapshot.financials.net_cash_eur_m == 25.0
    assert snapshot.financials.average_daily_value_eur == 2_750_000.0
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "yahoo"
    assert "KAR.ST" in snapshot.evidence.label
    assert requested_urls


def test_yahoo_provider_returns_none_for_malformed_or_missing_data():
    provider = YahooFundamentalsProvider(fetcher=lambda url: "{}")

    assert provider.get_fundamentals(make_company()) is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py -q
```

Expected: import failure because `investmentagent.fundamentals` does not exist.

- [ ] **Step 3: Implement `fundamentals.py`**

Create `src/investmentagent/fundamentals.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import quote
from urllib.request import Request, urlopen

from investmentagent.models import Company, DataQuality, Evidence, FinancialSnapshot


YAHOO_QUOTE_SUMMARY_URL = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=price,summaryDetail,financialData"
)


@dataclass(frozen=True)
class FundamentalsSnapshot:
    symbol: str
    market_cap_eur_m: float | None = None
    financials: FinancialSnapshot = field(
        default_factory=lambda: FinancialSnapshot(data_quality=DataQuality.PARTIAL)
    )
    evidence: Evidence | None = None


class YahooFundamentalsProvider:
    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher or _fetch_url
        self._last_error: str | None = None
        self._successful_lookups = 0
        self._attempted_lookups = 0

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in yahoo_symbol_candidates(company):
            self._attempted_lookups += 1
            try:
                payload = json.loads(self._fetcher(_yahoo_url(symbol)))
                snapshot = _snapshot_from_yahoo_payload(company, symbol, payload)
            except Exception as exc:
                self._last_error = str(exc)
                continue
            if snapshot is not None:
                self._successful_lookups += 1
                self._last_error = None
                return snapshot
        return None

    def source_check(self):
        from investmentagent.models import SourceCheck

        if self._successful_lookups:
            return SourceCheck(
                name="free fundamentals",
                status="ok",
                detail=(
                    f"{self._successful_lookups} fundamentals lookups succeeded "
                    f"from Yahoo-style quoteSummary"
                ),
            )
        if self._attempted_lookups and self._last_error:
            return SourceCheck(
                name="free fundamentals",
                status="warning",
                detail=f"No fundamentals lookups succeeded: {self._last_error}",
            )
        return SourceCheck(
            name="free fundamentals",
            status="warning",
            detail="No fundamentals lookups attempted",
        )


def yahoo_symbol_candidates(company: Company) -> tuple[str, ...]:
    suffix = {"SE": ".ST", "FI": ".HE"}.get(company.country)
    if suffix is None:
        return ()
    base = company.ticker.strip().upper().replace(" ", "-")
    candidates = [f"{base}{suffix}"]
    compact = base.replace("-", "")
    if compact != base:
        candidates.append(f"{compact}{suffix}")
    return tuple(dict.fromkeys(candidates))


def _fetch_url(url: str) -> str:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def _yahoo_url(symbol: str) -> str:
    return YAHOO_QUOTE_SUMMARY_URL.format(symbol=quote(symbol, safe=""))


def _snapshot_from_yahoo_payload(
    company: Company, symbol: str, payload: dict
) -> FundamentalsSnapshot | None:
    result = (payload.get("quoteSummary", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        return None
    price = result.get("price", {})
    summary = result.get("summaryDetail", {})
    financial = result.get("financialData", {})

    market_cap_eur_m = _money_to_eur_m(_raw(price.get("marketCap")), price.get("currency"))
    pe_ratio = _raw(summary.get("trailingPE"))
    price_to_book = _raw(summary.get("priceToBook"))
    revenue_growth_pct = _ratio_to_pct(_raw(financial.get("revenueGrowth")))
    operating_margin_pct = _ratio_to_pct(_raw(financial.get("operatingMargins")))
    debt_to_equity = _percent_to_ratio(_raw(financial.get("debtToEquity")))
    net_cash_eur_m = _net_cash_eur_m(financial, price.get("currency"))
    average_daily_value_eur = _average_daily_value_eur(summary, price.get("currency"))

    if not any(
        value is not None
        for value in (
            market_cap_eur_m,
            pe_ratio,
            price_to_book,
            revenue_growth_pct,
            operating_margin_pct,
            debt_to_equity,
            net_cash_eur_m,
            average_daily_value_eur,
        )
    ):
        return None

    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            price_to_book=price_to_book,
            net_cash_eur_m=net_cash_eur_m,
            debt_to_equity=debt_to_equity,
            revenue_growth_pct=revenue_growth_pct,
            operating_margin_pct=operating_margin_pct,
            average_daily_value_eur=average_daily_value_eur,
            data_quality=DataQuality.PARTIAL,
        ),
        evidence=Evidence(
            label=f"Yahoo-style fundamentals lookup ({symbol})",
            url=_yahoo_url(symbol),
            source="yahoo",
        ),
    )


def _raw(value) -> float | None:
    if isinstance(value, dict):
        value = value.get("raw")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_to_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 2)


def _percent_to_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 100.0, 4)


def _money_to_eur_m(value: float | None, currency) -> float | None:
    if value is None:
        return None
    rate = _currency_to_eur_rate(currency)
    if rate is None:
        return None
    return round(value * rate / 1_000_000, 2)


def _net_cash_eur_m(financial: dict, currency) -> float | None:
    cash = _raw(financial.get("totalCash"))
    debt = _raw(financial.get("totalDebt"))
    if cash is None or debt is None:
        return None
    return _money_to_eur_m(cash - debt, currency)


def _average_daily_value_eur(summary: dict, currency) -> float | None:
    volume = _raw(summary.get("averageDailyVolume10Day"))
    previous_close = _raw(summary.get("previousClose"))
    if volume is None or previous_close is None:
        return None
    rate = _currency_to_eur_rate(currency)
    if rate is None:
        return None
    return round(volume * previous_close * rate, 2)


def _currency_to_eur_rate(currency) -> float | None:
    normalized = str(currency or "").upper()
    if normalized == "EUR":
        return 1.0
    if normalized == "SEK":
        return 0.1
    return None
```

- [ ] **Step 4: Run fundamentals tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py -q
```

Expected: all fundamentals tests pass.

- [ ] **Step 5: Commit module work**

Run:

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "feat: add free fundamentals parser"
```

## Task 2: Enriched Provider Wrapper

**Files:**
- Modify: `src/investmentagent/fundamentals.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Add failing enrichment tests**

Append to `tests/test_fundamentals.py`:

```python
from investmentagent.fundamentals import EnrichedResearchProvider
from investmentagent.models import CompanyResearch


class BaseProvider:
    def __init__(self) -> None:
        self.company = make_company()

    def list_companies(self, countries, include_first_north):
        return [self.company]

    def get_research(self, ticker: str) -> CompanyResearch:
        return CompanyResearch(
            company=self.company,
            financials=FinancialSnapshot(price=110.0, currency="SEK", data_quality=DataQuality.THIN),
            catalysts=("Live price available from Nasdaq Nordic",),
            risks=("Sparse live-source data",),
            evidence=(),
            data_quality=DataQuality.THIN,
        )

    def get_company_research(self, company: Company) -> CompanyResearch:
        return self.get_research(company.ticker)

    def source_checks(self):
        return []


class StaticFundamentalsProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_fundamentals(self, company: Company):
        return self.snapshot

    def source_check(self):
        from investmentagent.models import SourceCheck

        return SourceCheck("free fundamentals", "ok", "fixture fundamentals available")


def test_enriched_provider_merges_fundamentals_into_research():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        market_cap_eur_m=550.0,
        financials=FinancialSnapshot(
            pe_ratio=11.2,
            price_to_book=1.1,
            operating_margin_pct=14.0,
            data_quality=DataQuality.PARTIAL,
        ),
        evidence=Evidence("Yahoo-style fundamentals lookup (KAR.ST)", "https://example.test", "yahoo"),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m == 550.0
    assert research.financials.price == 110.0
    assert research.financials.currency == "SEK"
    assert research.financials.pe_ratio == 11.2
    assert research.financials.price_to_book == 1.1
    assert research.financials.operating_margin_pct == 14.0
    assert research.financials.data_quality == DataQuality.PARTIAL
    assert research.data_quality == DataQuality.PARTIAL
    assert research.evidence[-1].source == "yahoo"


def test_enriched_provider_leaves_research_unchanged_when_fundamentals_missing():
    base = BaseProvider()
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(None))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m is None
    assert research.financials.pe_ratio is None
    assert research.data_quality == DataQuality.THIN
```

Also add missing imports at the top of the file:

```python
from investmentagent.models import Company, CompanyResearch, DataQuality, Evidence, FinancialSnapshot, ListingSegment
```

- [ ] **Step 2: Run enrichment tests and verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py::test_enriched_provider_merges_fundamentals_into_research tests/test_fundamentals.py::test_enriched_provider_leaves_research_unchanged_when_fundamentals_missing -q
```

Expected: import failure because `EnrichedResearchProvider` does not exist.

- [ ] **Step 3: Implement `EnrichedResearchProvider`**

Add to `src/investmentagent/fundamentals.py`:

```python
from dataclasses import replace
from investmentagent.models import CompanyResearch
```

Add this class:

```python
class EnrichedResearchProvider:
    def __init__(self, base_provider, fundamentals_provider) -> None:
        self.base_provider = base_provider
        self.fundamentals_provider = fundamentals_provider

    def list_companies(self, countries, include_first_north):
        return self.base_provider.list_companies(countries, include_first_north)

    def get_research(self, ticker: str) -> CompanyResearch:
        research = self.base_provider.get_research(ticker)
        return self._enrich(research)

    def get_company_research(self, company: Company) -> CompanyResearch:
        get_company_research = getattr(self.base_provider, "get_company_research", None)
        if callable(get_company_research):
            research = get_company_research(company)
        else:
            research = self.base_provider.get_research(company.ticker)
        return self._enrich(research)

    def source_checks(self):
        checks = list(self.base_provider.source_checks())
        source_check = getattr(self.fundamentals_provider, "source_check", None)
        if callable(source_check):
            checks.append(source_check())
        return checks

    def _enrich(self, research: CompanyResearch) -> CompanyResearch:
        snapshot = self.fundamentals_provider.get_fundamentals(research.company)
        if snapshot is None:
            return research
        company = replace(research.company, market_cap_eur_m=snapshot.market_cap_eur_m)
        financials = _merge_financials(research.financials, snapshot.financials)
        evidence = research.evidence
        if snapshot.evidence is not None:
            evidence = (*evidence, snapshot.evidence)
        return CompanyResearch(
            company=company,
            financials=financials,
            catalysts=research.catalysts,
            risks=research.risks,
            evidence=evidence,
            data_quality=financials.data_quality,
        )
```

Add helper:

```python
def _merge_financials(base: FinancialSnapshot, enrichment: FinancialSnapshot) -> FinancialSnapshot:
    return FinancialSnapshot(
        price=base.price,
        currency=base.currency,
        pe_ratio=enrichment.pe_ratio if enrichment.pe_ratio is not None else base.pe_ratio,
        price_to_book=(
            enrichment.price_to_book if enrichment.price_to_book is not None else base.price_to_book
        ),
        ev_to_ebit=enrichment.ev_to_ebit if enrichment.ev_to_ebit is not None else base.ev_to_ebit,
        net_cash_eur_m=(
            enrichment.net_cash_eur_m
            if enrichment.net_cash_eur_m is not None
            else base.net_cash_eur_m
        ),
        debt_to_equity=(
            enrichment.debt_to_equity
            if enrichment.debt_to_equity is not None
            else base.debt_to_equity
        ),
        revenue_growth_pct=(
            enrichment.revenue_growth_pct
            if enrichment.revenue_growth_pct is not None
            else base.revenue_growth_pct
        ),
        operating_margin_pct=(
            enrichment.operating_margin_pct
            if enrichment.operating_margin_pct is not None
            else base.operating_margin_pct
        ),
        one_year_return_pct=base.one_year_return_pct,
        distance_from_52w_high_pct=base.distance_from_52w_high_pct,
        average_daily_value_eur=(
            enrichment.average_daily_value_eur
            if enrichment.average_daily_value_eur is not None
            else base.average_daily_value_eur
        ),
        data_quality=DataQuality.PARTIAL,
    )
```

- [ ] **Step 4: Run fundamentals tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py -q
```

Expected: all fundamentals tests pass.

- [ ] **Step 5: Commit provider wrapper**

Run:

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "feat: enrich research with fundamentals"
```

## Task 3: Strategy Ranking Uses Enriched Fundamentals

**Files:**
- Modify: `tests/test_reports.py`
- Production edit: `src/investmentagent/reports.py` only if the new test proves long-term weighting is too weak for enriched valuation data.

- [ ] **Step 1: Add failing or confirming report integration test**

Add to `tests/test_reports.py` near strategy tests:

```python
def test_long_term_strategy_prefers_enriched_value_over_intraday_mover():
    provider = FakeResearchProvider(
        (
            make_research(
                "MOVER",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("Strong intraday momentum (+12.93%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "VALUE",
                pe_ratio=8.5,
                price_to_book=0.9,
                net_cash_eur_m=30.0,
                catalysts=("Live price available from Nasdaq Nordic",),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.PARTIAL,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert items[0].research.company.ticker == "VALUE"
```

- [ ] **Step 2: Run report test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_long_term_strategy_prefers_enriched_value_over_intraday_mover -q
```

Expected: pass if existing strategy work already supports enriched fields. If it fails, inspect the score components and adjust only `reports.py` strategy weighting enough to make actual valuation beat pure intraday momentum in `long-term`.

- [ ] **Step 3: Run report tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py -q
```

Expected: all report tests pass.

- [ ] **Step 4: Commit integration test**

Run:

```bash
git add tests/test_reports.py src/investmentagent/reports.py
git commit -m "test: cover long-term fundamentals ranking"
```

## Task 4: CLI Fundamentals Mode

**Files:**
- Modify: `src/investmentagent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Add to `tests/test_cli.py` near watchlist option tests:

```python
def test_watchlist_accepts_fundamentals_option():
    result = runner.invoke(
        app, ["watchlist", "--provider", "fixture", "--fundamentals", "off", "--limit", "1"]
    )

    assert result.exit_code == 0
    assert "#1" in result.output


def test_watchlist_rejects_invalid_fundamentals_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid fundamentals mode")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--fundamentals", "bad"])

    assert result.exit_code != 0
    assert "fundamentals must be 'off' or 'free'" in result.output


def test_watchlist_saves_fundamentals_metadata():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "fixture",
                "--fundamentals",
                "off",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["fundamentals"] == "off"
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_accepts_fundamentals_option tests/test_cli.py::test_watchlist_rejects_invalid_fundamentals_before_provider_work tests/test_cli.py::test_watchlist_saves_fundamentals_metadata -q
```

Expected: failures because `--fundamentals` does not exist.

- [ ] **Step 3: Implement CLI mode normalization and wrapping**

In `src/investmentagent/cli.py`, import:

```python
from investmentagent.fundamentals import EnrichedResearchProvider, YahooFundamentalsProvider
```

Add helper:

```python
def _normalize_fundamentals_option(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "free"}:
        raise typer.BadParameter("fundamentals must be 'off' or 'free'")
    return normalized
```

Add watchlist option:

```python
fundamentals: str = typer.Option(
    "free",
    "--fundamentals",
    help="Fundamentals enrichment mode: off or free.",
),
```

Normalize before provider creation:

```python
normalized_fundamentals = _normalize_fundamentals_option(fundamentals)
```

After provider creation and live source check, wrap only live provider when mode is `free`:

```python
if provider_name.strip().lower() == "live" and normalized_fundamentals == "free":
    provider = EnrichedResearchProvider(provider, YahooFundamentalsProvider())
```

Add saved metadata:

```python
"fundamentals": normalized_fundamentals,
```

For fixture provider, `--fundamentals free` should not wrap the fixture provider in this first version. It should simply record the requested mode if used. This preserves deterministic fixture behavior.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit CLI mode**

Run:

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: add fundamentals mode option"
```

## Task 5: Provider Source Checks And Live Smoke Tests

**Files:**
- Modify: `tests/test_fundamentals.py`
- Production edit: `src/investmentagent/fundamentals.py` only if the source-check test exposes a missing wrapper behavior.

- [ ] **Step 1: Add source check test**

Add to `tests/test_fundamentals.py`:

```python
def test_enriched_provider_appends_fundamentals_source_check():
    base = BaseProvider()
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(None))

    checks = provider.source_checks()

    assert checks[-1].name == "free fundamentals"
    assert checks[-1].status == "ok"
```

- [ ] **Step 2: Run fundamentals tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py -q
```

Expected: all fundamentals tests pass.

- [ ] **Step 3: Run full tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run fixture smoke tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider fixture --fundamentals off --strategy long-term --limit 3
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider fixture --fundamentals free --strategy long-term --limit 3
```

Expected: both commands exit 0. Fixture output remains deterministic.

- [ ] **Step 5: Run live smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --fundamentals free --strategy long-term --country se,fi --limit 10 --verbose
```

Expected: command exits 0 even if Yahoo-style fundamentals are partially unavailable. Verbose output includes a `free fundamentals` source check with `ok` or `warning`.

- [ ] **Step 6: Save report smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --fundamentals free --strategy long-term --country se,fi --limit 10 --save reports/watchlists/2026-05-10-long-term-fundamentals.md
```

Expected: report is saved and metadata includes `fundamentals: free`.

- [ ] **Step 7: Commit source check test**

Run:

```bash
git add tests/test_fundamentals.py
git commit -m "test: cover fundamentals source checks"
```

Expected: a commit is created for the source-check regression test.

## Task 6: Push

**Files:**
- No code changes expected.

- [ ] **Step 1: Final status check**

Run:

```bash
git status --short
```

Expected: only untracked generated `reports/` may remain.

- [ ] **Step 2: Push main**

Run:

```bash
git push origin main
```

Expected: GitHub `main` is updated.
