# OpenClaw Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-first OpenClaw v1 that ranks Swedish and Finnish public small/mid-cap stock opportunities and generates evidence-aware deep-dive reports.

**Architecture:** Implement a Python package with focused domain models, deterministic scoring, provider interfaces, fixture-backed free-source providers, and Typer CLI commands. The first working version must run offline from bundled seed data while keeping provider boundaries ready for real free web sources later.

**Tech Stack:** Python 3.11+, Typer, dataclasses, pytest, optional httpx/beautifulsoup4 in later provider work.

---

## File Structure

- Create `pyproject.toml`: package metadata, console script, pytest config, dependencies.
- Create `README.md`: quickstart, commands, and research disclaimer.
- Create `src/openclaw/__init__.py`: package version.
- Create `src/openclaw/models.py`: domain dataclasses and enums for companies, metrics, evidence, scores, watchlist items, reports, and source checks.
- Create `src/openclaw/scoring.py`: deterministic scoring engine.
- Create `src/openclaw/providers.py`: provider protocols and fixture-backed provider implementation.
- Create `src/openclaw/data/nordic_seed_companies.json`: small bundled seed universe with Swedish/Finnish listed examples.
- Create `src/openclaw/reports.py`: watchlist and deep-dive builders.
- Create `src/openclaw/renderers.py`: text and JSON renderers.
- Create `src/openclaw/cli.py`: Typer CLI commands.
- Create `tests/test_models.py`: model sanity tests.
- Create `tests/test_scoring.py`: scoring tests.
- Create `tests/test_providers.py`: provider tests.
- Create `tests/test_reports.py`: watchlist and deep-dive tests.
- Create `tests/test_cli.py`: CLI command tests.

## Task 1: Package Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/openclaw/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing package import test**

Create `tests/test_models.py`:

```python
from openclaw import __version__


def test_package_exposes_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_package_exposes_version -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw'`.

- [ ] **Step 3: Add package metadata**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "openclaw"
version = "0.1.0"
description = "CLI-first Nordic small/mid-cap investing research agent"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
]

[project.scripts]
openclaw = "openclaw.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
openclaw = ["data/*.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `README.md`:

```markdown
# OpenClaw

OpenClaw is a CLI-first research triage tool for Swedish and Finnish publicly listed stocks, including First North companies. It focuses on small and mid-cap discovery with a value bias.

OpenClaw is not financial advice. It ranks research candidates, shows evidence, and highlights uncertainty so a human investor can decide what to investigate next.

## Commands

```bash
openclaw watchlist --country se,fi --limit 20
openclaw deep-dive <ticker>
openclaw sources test
```
```

Create `src/openclaw/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_package_exposes_version -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md src/openclaw/__init__.py tests/test_models.py
git commit -m "chore: scaffold OpenClaw package"
```

## Task 2: Domain Models

**Files:**
- Create: `src/openclaw/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append to `tests/test_models.py`:

```python
from openclaw.models import Company, DataQuality, Evidence, FinancialSnapshot, ListingSegment


def test_company_normalizes_ticker_and_country():
    company = Company(
        name="Example AB",
        ticker=" exab ",
        country=" se ",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.FIRST_NORTH,
        sector="Industrials",
    )

    assert company.ticker == "EXAB"
    assert company.country == "SE"


def test_financial_snapshot_defaults_to_thin_quality():
    snapshot = FinancialSnapshot()

    assert snapshot.data_quality == DataQuality.THIN


def test_evidence_requires_label_and_url():
    evidence = Evidence(label="IR page", url="https://example.com/ir")

    assert evidence.label == "IR page"
    assert evidence.url == "https://example.com/ir"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.models'`.

- [ ] **Step 3: Implement models**

Create `src/openclaw/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DataQuality(str, Enum):
    GOOD = "good"
    PARTIAL = "partial"
    THIN = "thin"


class ListingSegment(str, Enum):
    MAIN_MARKET = "main_market"
    FIRST_NORTH = "first_north"
    SPOTLIGHT = "spotlight"
    OTHER_PUBLIC = "other_public"


@dataclass(frozen=True)
class Evidence:
    label: str
    url: str
    source: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class Company:
    name: str
    ticker: str
    country: str
    exchange: str
    segment: ListingSegment
    sector: str | None = None
    market_cap_eur_m: float | None = None
    currency: str | None = None
    ir_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "country", self.country.strip().upper())


@dataclass(frozen=True)
class FinancialSnapshot:
    price: float | None = None
    currency: str | None = None
    pe_ratio: float | None = None
    price_to_book: float | None = None
    ev_to_ebit: float | None = None
    net_cash_eur_m: float | None = None
    debt_to_equity: float | None = None
    revenue_growth_pct: float | None = None
    operating_margin_pct: float | None = None
    one_year_return_pct: float | None = None
    distance_from_52w_high_pct: float | None = None
    average_daily_value_eur: float | None = None
    data_quality: DataQuality = DataQuality.THIN


@dataclass(frozen=True)
class CompanyResearch:
    company: Company
    financials: FinancialSnapshot
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    data_quality: DataQuality = DataQuality.THIN


@dataclass(frozen=True)
class ScoreBreakdown:
    value: float
    discovery: float
    catalyst: float
    risk_penalty: float
    data_quality_penalty: float
    total: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WatchlistItem:
    rank: int
    research: CompanyResearch
    score: ScoreBreakdown


@dataclass(frozen=True)
class DeepDiveReport:
    research: CompanyResearch
    score: ScoreBreakdown
    business_summary: str
    why_it_appeared: tuple[str, ...]
    valuation_view: tuple[str, ...]
    bull_case: tuple[str, ...]
    base_case: tuple[str, ...]
    bear_case: tuple[str, ...]
    next_manual_checks: tuple[str, ...]


@dataclass(frozen=True)
class SourceCheck:
    name: str
    status: str
    detail: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openclaw/models.py tests/test_models.py
git commit -m "feat: add OpenClaw domain models"
```

## Task 3: Scoring Engine

**Files:**
- Create: `src/openclaw/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `tests/test_scoring.py`:

```python
from openclaw.models import Company, CompanyResearch, DataQuality, FinancialSnapshot, ListingSegment
from openclaw.scoring import score_research


def make_research(**financial_overrides):
    financials = FinancialSnapshot(
        pe_ratio=9.0,
        price_to_book=0.8,
        net_cash_eur_m=12.0,
        one_year_return_pct=-35.0,
        distance_from_52w_high_pct=-45.0,
        average_daily_value_eur=80_000,
        data_quality=DataQuality.GOOD,
        **financial_overrides,
    )
    company = Company(
        name="Hidden Value Oyj",
        ticker="HVO",
        country="FI",
        exchange="Nasdaq Helsinki",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
        market_cap_eur_m=90,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        catalysts=("New contract announced",),
        risks=("Low liquidity",),
        data_quality=financials.data_quality,
    )


def test_score_rewards_small_value_companies_with_catalysts():
    score = score_research(make_research())

    assert score.value > 0
    assert score.discovery > 0
    assert score.catalyst > 0
    assert score.total > 0
    assert "low P/E" in " ".join(score.reasons)


def test_score_penalizes_thin_data_quality():
    good = score_research(make_research(data_quality=DataQuality.GOOD))
    thin = score_research(make_research(data_quality=DataQuality.THIN))

    assert thin.data_quality_penalty > good.data_quality_penalty
    assert thin.total < good.total


def test_score_penalizes_expensive_unprofitable_profile():
    score = score_research(
        make_research(
            pe_ratio=80.0,
            price_to_book=8.0,
            net_cash_eur_m=-30.0,
            operating_margin_pct=-12.0,
        )
    )

    assert score.risk_penalty > 0
    assert score.total < 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scoring.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.scoring'`.

- [ ] **Step 3: Implement scoring engine**

Create `src/openclaw/scoring.py`:

```python
from __future__ import annotations

from openclaw.models import CompanyResearch, DataQuality, ListingSegment, ScoreBreakdown


def score_research(research: CompanyResearch) -> ScoreBreakdown:
    financials = research.financials
    company = research.company
    reasons: list[str] = []
    warnings: list[str] = []

    value = 0.0
    if financials.pe_ratio is not None and financials.pe_ratio <= 12:
        value += 20
        reasons.append(f"low P/E ratio ({financials.pe_ratio:.1f})")
    if financials.price_to_book is not None and financials.price_to_book <= 1.2:
        value += 15
        reasons.append(f"low price/book ratio ({financials.price_to_book:.1f})")
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        value += 10
        reasons.append("net cash balance sheet")

    discovery = 0.0
    if company.market_cap_eur_m is not None and company.market_cap_eur_m <= 500:
        discovery += 15
        reasons.append(f"small/mid-cap market value ({company.market_cap_eur_m:.0f}m EUR)")
    if company.segment == ListingSegment.FIRST_NORTH:
        discovery += 10
        reasons.append("First North listing")
    if financials.one_year_return_pct is not None and financials.one_year_return_pct <= -25:
        discovery += 8
        reasons.append("meaningful one-year underperformance")
    if financials.distance_from_52w_high_pct is not None and financials.distance_from_52w_high_pct <= -35:
        discovery += 7
        reasons.append("trading far below 52-week high")

    catalyst = min(len(research.catalysts) * 8.0, 24.0)
    if catalyst:
        reasons.append(f"{len(research.catalysts)} public catalyst signal(s)")

    risk_penalty = 0.0
    if financials.average_daily_value_eur is not None and financials.average_daily_value_eur < 100_000:
        risk_penalty += 8
        warnings.append("low trading liquidity")
    if financials.debt_to_equity is not None and financials.debt_to_equity > 1.5:
        risk_penalty += 8
        warnings.append("elevated debt/equity")
    if financials.operating_margin_pct is not None and financials.operating_margin_pct < 0:
        risk_penalty += 10
        warnings.append("negative operating margin")
    if financials.pe_ratio is not None and financials.pe_ratio > 40:
        risk_penalty += 10
        warnings.append("high P/E ratio")
    if financials.price_to_book is not None and financials.price_to_book > 5:
        risk_penalty += 8
        warnings.append("high price/book ratio")
    risk_penalty += min(len(research.risks) * 3.0, 15.0)

    data_quality_penalty = {
        DataQuality.GOOD: 0.0,
        DataQuality.PARTIAL: 7.0,
        DataQuality.THIN: 14.0,
    }[research.data_quality]

    total = value + discovery + catalyst - risk_penalty - data_quality_penalty
    return ScoreBreakdown(
        value=value,
        discovery=discovery,
        catalyst=catalyst,
        risk_penalty=risk_penalty,
        data_quality_penalty=data_quality_penalty,
        total=round(total, 2),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scoring.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openclaw/scoring.py tests/test_scoring.py
git commit -m "feat: add transparent scoring engine"
```

## Task 4: Fixture-Backed Providers

**Files:**
- Create: `src/openclaw/providers.py`
- Create: `src/openclaw/data/nordic_seed_companies.json`
- Create: `tests/test_providers.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/test_providers.py`:

```python
from openclaw.models import DataQuality
from openclaw.providers import FixtureResearchProvider


def test_fixture_provider_filters_country_and_first_north():
    provider = FixtureResearchProvider()

    companies = provider.list_companies(countries=("FI",), include_first_north=True)

    assert companies
    assert all(company.country == "FI" for company in companies)
    assert any(company.segment.value == "first_north" for company in companies)


def test_fixture_provider_returns_research_with_evidence():
    provider = FixtureResearchProvider()
    company = provider.list_companies(countries=("SE",), include_first_north=True)[0]

    research = provider.get_research(company.ticker)

    assert research.company.ticker == company.ticker
    assert research.data_quality in {DataQuality.GOOD, DataQuality.PARTIAL, DataQuality.THIN}
    assert research.evidence


def test_source_checks_report_seed_data_available():
    provider = FixtureResearchProvider()

    checks = provider.source_checks()

    assert checks[0].name == "bundled seed data"
    assert checks[0].status == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.providers'`.

- [ ] **Step 3: Add seed data**

Create `src/openclaw/data/nordic_seed_companies.json`:

```json
[
  {
    "name": "Remedy Entertainment Oyj",
    "ticker": "REMEDY",
    "country": "FI",
    "exchange": "Nasdaq Helsinki",
    "segment": "main_market",
    "sector": "Gaming",
    "market_cap_eur_m": 330,
    "currency": "EUR",
    "ir_url": "https://investors.remedygames.com/",
    "financials": {
      "price": 24.0,
      "currency": "EUR",
      "pe_ratio": 28.0,
      "price_to_book": 3.4,
      "net_cash_eur_m": 20.0,
      "revenue_growth_pct": 12.0,
      "operating_margin_pct": 6.0,
      "one_year_return_pct": -30.0,
      "distance_from_52w_high_pct": -42.0,
      "average_daily_value_eur": 250000,
      "data_quality": "partial"
    },
    "catalysts": ["Pipeline releases and publishing model changes"],
    "risks": ["Hit-driven revenue", "Project timing risk"],
    "evidence": [
      {"label": "Investor relations", "url": "https://investors.remedygames.com/", "source": "company"}
    ]
  },
  {
    "name": "Gofore Oyj",
    "ticker": "GOFORE",
    "country": "FI",
    "exchange": "Nasdaq Helsinki",
    "segment": "main_market",
    "sector": "IT Services",
    "market_cap_eur_m": 300,
    "currency": "EUR",
    "ir_url": "https://gofore.com/en/invest/",
    "financials": {
      "price": 19.0,
      "currency": "EUR",
      "pe_ratio": 16.0,
      "price_to_book": 2.6,
      "net_cash_eur_m": 10.0,
      "revenue_growth_pct": 4.0,
      "operating_margin_pct": 11.0,
      "one_year_return_pct": -38.0,
      "distance_from_52w_high_pct": -45.0,
      "average_daily_value_eur": 160000,
      "data_quality": "partial"
    },
    "catalysts": ["Digital services demand recovery"],
    "risks": ["Consulting cycle sensitivity"],
    "evidence": [
      {"label": "Investor relations", "url": "https://gofore.com/en/invest/", "source": "company"}
    ]
  },
  {
    "name": "Karnov Group AB",
    "ticker": "KAR",
    "country": "SE",
    "exchange": "Nasdaq Stockholm",
    "segment": "main_market",
    "sector": "Information Services",
    "market_cap_eur_m": 420,
    "currency": "SEK",
    "ir_url": "https://www.karnovgroup.com/en/investors/",
    "financials": {
      "price": 50.0,
      "currency": "SEK",
      "pe_ratio": 11.0,
      "price_to_book": 1.1,
      "net_cash_eur_m": -15.0,
      "debt_to_equity": 0.8,
      "revenue_growth_pct": 8.0,
      "operating_margin_pct": 15.0,
      "one_year_return_pct": -28.0,
      "distance_from_52w_high_pct": -36.0,
      "average_daily_value_eur": 220000,
      "data_quality": "partial"
    },
    "catalysts": ["Integration and margin improvement potential"],
    "risks": ["Leverage after acquisitions"],
    "evidence": [
      {"label": "Investor relations", "url": "https://www.karnovgroup.com/en/investors/", "source": "company"}
    ]
  },
  {
    "name": "Freemelt Holding AB",
    "ticker": "FREEM",
    "country": "SE",
    "exchange": "Nasdaq First North Growth Market",
    "segment": "first_north",
    "sector": "Industrial Technology",
    "market_cap_eur_m": 35,
    "currency": "SEK",
    "ir_url": "https://freemelt.com/investors/",
    "financials": {
      "price": 5.0,
      "currency": "SEK",
      "pe_ratio": null,
      "price_to_book": 1.0,
      "net_cash_eur_m": 4.0,
      "revenue_growth_pct": 20.0,
      "operating_margin_pct": -25.0,
      "one_year_return_pct": -55.0,
      "distance_from_52w_high_pct": -65.0,
      "average_daily_value_eur": 35000,
      "data_quality": "thin"
    },
    "catalysts": ["Commercialization progress"],
    "risks": ["Negative earnings", "Low liquidity", "Funding risk"],
    "evidence": [
      {"label": "Investor relations", "url": "https://freemelt.com/investors/", "source": "company"}
    ]
  }
]
```

- [ ] **Step 4: Implement provider**

Create `src/openclaw/providers.py`:

```python
from __future__ import annotations

import json
from importlib.resources import files
from typing import Protocol

from openclaw.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
)


class ResearchProvider(Protocol):
    def list_companies(self, countries: tuple[str, ...], include_first_north: bool) -> list[Company]:
        ...

    def get_research(self, ticker: str) -> CompanyResearch:
        ...

    def source_checks(self) -> list[SourceCheck]:
        ...


class FixtureResearchProvider:
    def __init__(self) -> None:
        data_path = files("openclaw").joinpath("data/nordic_seed_companies.json")
        self._rows = json.loads(data_path.read_text(encoding="utf-8"))

    def list_companies(self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True) -> list[Company]:
        wanted = {country.upper() for country in countries}
        companies = [self._company_from_row(row) for row in self._rows]
        return [
            company
            for company in companies
            if company.country in wanted and (include_first_north or company.segment != ListingSegment.FIRST_NORTH)
        ]

    def get_research(self, ticker: str) -> CompanyResearch:
        normalized = ticker.strip().upper()
        for row in self._rows:
            if row["ticker"].upper() == normalized:
                return self._research_from_row(row)
        raise LookupError(f"No bundled research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        return [
            SourceCheck(
                name="bundled seed data",
                status="ok",
                detail=f"{len(self._rows)} companies available from local fixture data",
            )
        ]

    def _company_from_row(self, row: dict) -> Company:
        return Company(
            name=row["name"],
            ticker=row["ticker"],
            country=row["country"],
            exchange=row["exchange"],
            segment=ListingSegment(row["segment"]),
            sector=row.get("sector"),
            market_cap_eur_m=row.get("market_cap_eur_m"),
            currency=row.get("currency"),
            ir_url=row.get("ir_url"),
        )

    def _research_from_row(self, row: dict) -> CompanyResearch:
        financial_data = dict(row["financials"])
        financial_data["data_quality"] = DataQuality(financial_data["data_quality"])
        evidence = tuple(Evidence(**item) for item in row.get("evidence", []))
        financials = FinancialSnapshot(**financial_data)
        return CompanyResearch(
            company=self._company_from_row(row),
            financials=financials,
            catalysts=tuple(row.get("catalysts", [])),
            risks=tuple(row.get("risks", [])),
            evidence=evidence,
            data_quality=financials.data_quality,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_providers.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openclaw/providers.py src/openclaw/data/nordic_seed_companies.json tests/test_providers.py
git commit -m "feat: add fixture-backed Nordic research provider"
```

## Task 5: Watchlist and Deep-Dive Builders

**Files:**
- Create: `src/openclaw/reports.py`
- Create: `tests/test_reports.py`

- [ ] **Step 1: Write failing report tests**

Create `tests/test_reports.py`:

```python
from openclaw.providers import FixtureResearchProvider
from openclaw.reports import build_deep_dive, build_watchlist


def test_build_watchlist_returns_ranked_items_by_score():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=3, include_first_north=True)

    assert len(items) == 3
    assert [item.rank for item in items] == [1, 2, 3]
    assert items[0].score.total >= items[1].score.total


def test_build_deep_dive_includes_manual_checks_and_thesis():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    assert report.research.company.ticker == "FREEM"
    assert report.why_it_appeared
    assert report.valuation_view
    assert report.bull_case
    assert report.base_case
    assert report.bear_case
    assert report.next_manual_checks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reports.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.reports'`.

- [ ] **Step 3: Implement report builders**

Create `src/openclaw/reports.py`:

```python
from __future__ import annotations

from openclaw.models import DeepDiveReport, WatchlistItem
from openclaw.providers import ResearchProvider
from openclaw.scoring import score_research


def build_watchlist(
    provider: ResearchProvider,
    countries: tuple[str, ...],
    limit: int,
    include_first_north: bool,
) -> list[WatchlistItem]:
    items: list[WatchlistItem] = []
    for company in provider.list_companies(countries=countries, include_first_north=include_first_north):
        research = provider.get_research(company.ticker)
        score = score_research(research)
        items.append(WatchlistItem(rank=0, research=research, score=score))

    ranked = sorted(items, key=lambda item: item.score.total, reverse=True)[:limit]
    return [
        WatchlistItem(rank=index + 1, research=item.research, score=item.score)
        for index, item in enumerate(ranked)
    ]


def build_deep_dive(provider: ResearchProvider, ticker: str) -> DeepDiveReport:
    research = provider.get_research(ticker)
    score = score_research(research)
    company = research.company
    financials = research.financials

    valuation_view: list[str] = []
    if financials.pe_ratio is None:
        valuation_view.append("P/E ratio unavailable or not meaningful from current free data.")
    else:
        valuation_view.append(f"P/E ratio: {financials.pe_ratio:.1f}.")
    if financials.price_to_book is None:
        valuation_view.append("Price/book unavailable from current free data.")
    else:
        valuation_view.append(f"Price/book: {financials.price_to_book:.1f}.")
    if financials.net_cash_eur_m is None:
        valuation_view.append("Net cash/debt unavailable from current free data.")
    elif financials.net_cash_eur_m >= 0:
        valuation_view.append(f"Net cash: about {financials.net_cash_eur_m:.0f}m EUR.")
    else:
        valuation_view.append(f"Net debt: about {abs(financials.net_cash_eur_m):.0f}m EUR.")

    return DeepDiveReport(
        research=research,
        score=score,
        business_summary=(
            f"{company.name} is a {company.country} listed company in "
            f"{company.sector or 'an unspecified sector'} on {company.exchange}."
        ),
        why_it_appeared=score.reasons or ("The company matched the current discovery screen.",),
        valuation_view=tuple(valuation_view),
        bull_case=tuple(research.catalysts) or ("A positive catalyst could improve investor attention.",),
        base_case=("The current evidence is enough for research triage, but not for an investment decision.",),
        bear_case=tuple(research.risks) or ("The main downside is that available free-source evidence may be incomplete.",),
        next_manual_checks=(
            "Read the latest annual and interim reports.",
            "Check recent company announcements and insider or ownership disclosures.",
            "Verify liquidity and bid/ask spread before considering position sizing.",
            "Compare valuation against direct Nordic peers where possible.",
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reports.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openclaw/reports.py tests/test_reports.py
git commit -m "feat: build watchlist and deep-dive reports"
```

## Task 6: Renderers

**Files:**
- Create: `src/openclaw/renderers.py`
- Modify: `tests/test_reports.py`

- [ ] **Step 1: Write failing renderer tests**

Append to `tests/test_reports.py`:

```python
import json

from openclaw.renderers import render_deep_dive_text, render_watchlist_json, render_watchlist_text


def test_render_watchlist_text_includes_rank_score_risks_and_links():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True)

    output = render_watchlist_text(items)

    assert "#1" in output
    assert "Score:" in output
    assert "Risks:" in output
    assert "Evidence:" in output
    assert "Not financial advice" in output


def test_render_watchlist_json_is_machine_readable():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True)

    payload = json.loads(render_watchlist_json(items))

    assert payload["disclaimer"].startswith("Research triage")
    assert payload["items"][0]["rank"] == 1
    assert "evidence" in payload["items"][0]


def test_render_deep_dive_text_includes_thesis_sections():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    output = render_deep_dive_text(report)

    assert "Bull case" in output
    assert "Base case" in output
    assert "Bear case" in output
    assert "Next manual checks" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reports.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.renderers'`.

- [ ] **Step 3: Implement renderers**

Create `src/openclaw/renderers.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict

from openclaw.models import DeepDiveReport, WatchlistItem


DISCLAIMER = "Research triage only. Not financial advice."


def render_watchlist_text(items: list[WatchlistItem]) -> str:
    lines = [f"{DISCLAIMER}", ""]
    for item in items:
        research = item.research
        company = research.company
        lines.append(f"#{item.rank} {company.name} ({company.ticker})")
        lines.append(f"Country: {company.country} | Exchange: {company.exchange} | Segment: {company.segment.value}")
        lines.append(f"Score: {item.score.total:.2f}")
        lines.append(f"Reasons: {', '.join(item.score.reasons) if item.score.reasons else 'No strong positive signals.'}")
        lines.append(f"Risks: {', '.join(research.risks or item.score.warnings) if (research.risks or item.score.warnings) else 'No major risks captured in fixture data.'}")
        lines.append(f"Data quality: {research.data_quality.value}")
        if research.evidence:
            lines.append("Evidence:")
            for evidence in research.evidence:
                lines.append(f"- {evidence.label}: {evidence.url}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_watchlist_json(items: list[WatchlistItem]) -> str:
    payload = {
        "disclaimer": DISCLAIMER,
        "items": [
            {
                "rank": item.rank,
                "company": asdict(item.research.company),
                "financials": asdict(item.research.financials),
                "score": asdict(item.score),
                "risks": list(item.research.risks),
                "catalysts": list(item.research.catalysts),
                "evidence": [asdict(evidence) for evidence in item.research.evidence],
                "data_quality": item.research.data_quality.value,
            }
            for item in items
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_deep_dive_text(report: DeepDiveReport) -> str:
    company = report.research.company
    lines = [
        DISCLAIMER,
        "",
        f"{company.name} ({company.ticker})",
        "=" * (len(company.name) + len(company.ticker) + 3),
        "",
        report.business_summary,
        "",
        f"Score: {report.score.total:.2f} | Data quality: {report.research.data_quality.value}",
        "",
        "Why it appeared",
        *[f"- {item}" for item in report.why_it_appeared],
        "",
        "Valuation view",
        *[f"- {item}" for item in report.valuation_view],
        "",
        "Catalysts",
        *[f"- {item}" for item in (report.research.catalysts or ('No catalyst captured in fixture data.',))],
        "",
        "Bull case",
        *[f"- {item}" for item in report.bull_case],
        "",
        "Base case",
        *[f"- {item}" for item in report.base_case],
        "",
        "Bear case",
        *[f"- {item}" for item in report.bear_case],
        "",
        "Next manual checks",
        *[f"- {item}" for item in report.next_manual_checks],
        "",
        "Evidence",
    ]
    if report.research.evidence:
        lines.extend(f"- {evidence.label}: {evidence.url}" for evidence in report.research.evidence)
    else:
        lines.append("- No evidence links captured in fixture data.")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reports.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openclaw/renderers.py tests/test_reports.py
git commit -m "feat: render watchlists and deep dives"
```

## Task 7: CLI Commands

**Files:**
- Create: `src/openclaw/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from openclaw.cli import app


runner = CliRunner()


def test_watchlist_command_outputs_ranked_text():
    result = runner.invoke(app, ["watchlist", "--country", "se,fi", "--limit", "2"])

    assert result.exit_code == 0
    assert "#1" in result.output
    assert "Not financial advice" in result.output


def test_watchlist_command_outputs_json():
    result = runner.invoke(app, ["watchlist", "--country", "se,fi", "--limit", "1", "--output", "json"])

    assert result.exit_code == 0
    assert '"items"' in result.output
    assert '"rank": 1' in result.output


def test_deep_dive_command_outputs_report():
    result = runner.invoke(app, ["deep-dive", "FREEM"])

    assert result.exit_code == 0
    assert "Freemelt" in result.output
    assert "Next manual checks" in result.output


def test_sources_test_command_reports_fixture_status():
    result = runner.invoke(app, ["sources", "test"])

    assert result.exit_code == 0
    assert "bundled seed data: ok" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'openclaw.cli'`.

- [ ] **Step 3: Implement CLI**

Create `src/openclaw/cli.py`:

```python
from __future__ import annotations

from typing import Annotated

import typer

from openclaw.providers import FixtureResearchProvider
from openclaw.renderers import render_deep_dive_text, render_watchlist_json, render_watchlist_text
from openclaw.reports import build_deep_dive, build_watchlist


app = typer.Typer(help="OpenClaw Nordic investing research CLI.")
sources_app = typer.Typer(help="Source diagnostics.")
app.add_typer(sources_app, name="sources")


def _parse_countries(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in raw.split(",") if part.strip())


@app.command()
def watchlist(
    country: Annotated[str, typer.Option(help="Comma-separated country codes, such as se,fi.")] = "se,fi",
    limit: Annotated[int, typer.Option(min=1, max=100, help="Maximum number of companies to show.")] = 20,
    include_first_north: Annotated[bool, typer.Option(help="Include First North listings.")] = True,
    output: Annotated[str, typer.Option(help="Output format: text or json.")] = "text",
) -> None:
    provider = FixtureResearchProvider()
    items = build_watchlist(
        provider,
        countries=_parse_countries(country),
        limit=limit,
        include_first_north=include_first_north,
    )
    if output == "json":
        typer.echo(render_watchlist_json(items))
        return
    if output != "text":
        raise typer.BadParameter("output must be 'text' or 'json'")
    typer.echo(render_watchlist_text(items), nl=False)


@app.command("deep-dive")
def deep_dive(ticker: str) -> None:
    provider = FixtureResearchProvider()
    try:
        report = build_deep_dive(provider, ticker)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(render_deep_dive_text(report), nl=False)


@sources_app.command("test")
def sources_test() -> None:
    provider = FixtureResearchProvider()
    for check in provider.source_checks():
        typer.echo(f"{check.name}: {check.status} - {check.detail}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openclaw/cli.py tests/test_cli.py
git commit -m "feat: add OpenClaw CLI commands"
```

## Task 8: Final Verification and README Polish

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Expand README with install and usage**

Replace `README.md` with:

```markdown
# OpenClaw

OpenClaw is a CLI-first research triage tool for Swedish and Finnish publicly listed stocks, including First North companies. It focuses on small and mid-cap discovery with a value bias.

OpenClaw is not financial advice. It ranks research candidates, shows evidence, and highlights uncertainty so a human investor can decide what to investigate next.

## Install for local development

```bash
python -m pip install -e ".[dev]"
```

## Commands

```bash
openclaw watchlist --country se,fi --limit 20
openclaw watchlist --country se,fi --limit 5 --output json
openclaw deep-dive FREEM
openclaw sources test
```

## Current data mode

V1 starts with bundled fixture data so the scoring, reports, and CLI can be tested deterministically. The provider boundary is intentionally separate from scoring and rendering so future free-source fetchers can replace or augment the fixture provider.

## Scoring model

The score is transparent:

```text
total score = value score + discovery score + catalyst score - risk penalty - data quality penalty
```

Every report should show reasons, risks, data quality, and evidence links.
```

- [ ] **Step 2: Run final verification**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 3: Run CLI smoke checks**

Run: `python -m openclaw.cli --help`

Expected: CLI help renders without traceback.

Run: `python -m openclaw.cli watchlist --country se,fi --limit 3`

Expected: Text output contains `#1`, `Score:`, `Risks:`, `Evidence:`, and `Not financial advice`.

Run: `python -m openclaw.cli deep-dive FREEM`

Expected: Text output contains `Freemelt`, `Bull case`, `Bear case`, and `Next manual checks`.

- [ ] **Step 4: Check git status**

Run: `git status --short`

Expected: only intended changes are present.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document OpenClaw CLI usage"
```

## Self-Review

Spec coverage:

- Public Swedish/Finnish listed companies including First North: Task 4 seed provider and filters.
- Daily ranked watchlist: Tasks 5, 6, and 7.
- Deep-dive reports: Tasks 5, 6, and 7.
- Free/public-source-first design: Task 4 fixture provider plus provider boundary, with README stating current data mode.
- CLI-first interface: Task 7.
- Transparent scoring: Task 3 and README scoring section.
- Evidence, risks, data quality: Tasks 2, 4, 5, and 6.
- Testing: Every task is test-first and Task 8 runs full verification.

No placeholders are intentionally left in this plan. Real free web fetchers are not implemented in v1; the approved design allows provider replacement, and this plan delivers a deterministic CLI MVP that can be extended in the next iteration.
