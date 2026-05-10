# InvestmentAgent Live Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fixture/live provider selection and a mocked-testable Nasdaq Nordic live provider skeleton without changing the existing scoring and reporting flow.

**Architecture:** Keep `FixtureResearchProvider` as the default and add `LiveNasdaqNordicProvider` behind the existing `ResearchProvider` protocol. A small provider factory in `investmentagent.providers` will let the CLI choose `fixture` or `live`, while tests inject deterministic fetchers so the suite never needs internet access.

**Tech Stack:** Python 3.12, standard-library `urllib.request`, dataclasses/enums already in the project, Typer, pytest.

---

## File Structure

- Modify `src/investmentagent/providers.py`: add provider factory, provider-name validation, live provider, public listing URL constant, and parsing helpers.
- Modify `src/investmentagent/cli.py`: add `--provider fixture|live` to `watchlist`, `deep-dive`, and `sources test`.
- Modify `tests/test_providers.py`: add live provider parsing, filtering, failure, and provider factory tests.
- Modify `tests/test_cli.py`: add provider-selection and invalid-provider CLI tests.
- Modify `README.md`: document provider selection and live-data limitations.

## Task 1: Provider Factory

**Files:**
- Modify: `src/investmentagent/providers.py`
- Modify: `tests/test_providers.py`

- [ ] **Step 1: Write failing provider factory tests**

Append to `tests/test_providers.py`:

```python
import pytest

from investmentagent.providers import FixtureResearchProvider, create_provider


def test_create_provider_defaults_to_fixture():
    provider = create_provider("fixture")

    assert isinstance(provider, FixtureResearchProvider)


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="provider must be 'fixture' or 'live'"):
        create_provider("unknown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: FAIL with `ImportError` or `AttributeError` because `create_provider` does not exist.

- [ ] **Step 3: Implement minimal provider factory**

Update `src/investmentagent/providers.py`:

```python
def create_provider(name: str) -> ResearchProvider:
    normalized = name.strip().lower()
    if normalized == "fixture":
        return FixtureResearchProvider()
    if normalized == "live":
        return LiveNasdaqNordicProvider()
    raise ValueError("provider must be 'fixture' or 'live'")
```

Add a temporary `LiveNasdaqNordicProvider` class below `FixtureResearchProvider` so the factory can import cleanly. It will be expanded in Task 2:

```python
class LiveNasdaqNordicProvider:
    def list_companies(
        self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True
    ) -> list[Company]:
        return []

    def get_research(self, ticker: str) -> CompanyResearch:
        raise LookupError(f"No live research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        return [
            SourceCheck(
                name="nasdaq nordic live data",
                status="unavailable",
                detail="Live provider is not implemented yet",
            )
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/providers.py tests/test_providers.py
git commit -m "feat: add provider factory"
```

## Task 2: Live Provider Parsing

**Files:**
- Modify: `src/investmentagent/providers.py`
- Modify: `tests/test_providers.py`

- [ ] **Step 1: Write failing live-provider tests**

Append to `tests/test_providers.py`:

```python
from investmentagent.models import ListingSegment
from investmentagent.providers import LiveNasdaqNordicProvider


LIVE_SAMPLE_CSV = """name,ticker,country,exchange,segment,sector,currency,isin
Nordic Value AB,NVAL,SE,Nasdaq Stockholm,main_market,Industrials,SEK,SE0000000001
First Growth Oyj,FGRO,FI,Nasdaq First North Growth Market,first_north,Software,EUR,FI0000000002
Ignored Denmark A/S,IGN,DK,Nasdaq Copenhagen,main_market,Industrials,DKK,DK0000000003
"""


def test_live_provider_parses_companies_from_sample_payload():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies] == ["NVAL", "FGRO"]
    assert companies[0].country == "SE"
    assert companies[1].segment == ListingSegment.FIRST_NORTH


def test_live_provider_filters_first_north():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=False)

    assert [company.ticker for company in companies] == ["NVAL"]


def test_live_provider_returns_thin_research_with_evidence():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    research = provider.get_research("FGRO")

    assert research.company.ticker == "FGRO"
    assert research.data_quality.value == "thin"
    assert research.financials.data_quality.value == "thin"
    assert research.risks == ("Sparse live-source data",)
    assert research.evidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: FAIL because `LiveNasdaqNordicProvider` does not accept `fetcher` or parse data.

- [ ] **Step 3: Implement live provider parsing**

Update `src/investmentagent/providers.py` imports:

```python
import csv
from collections.abc import Callable
from io import StringIO
from urllib.request import urlopen
```

Add constants:

```python
NASDAQ_NORDIC_LISTINGS_URL = "https://www.nasdaqomxnordic.com/shares/listed-companies"
```

Replace the temporary live provider with:

```python
def _default_fetcher(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


class LiveNasdaqNordicProvider:
    def __init__(
        self,
        source_url: str = NASDAQ_NORDIC_LISTINGS_URL,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.source_url = source_url
        self._fetcher = fetcher or _default_fetcher
        self._companies: list[Company] | None = None
        self._last_error: str | None = None

    def list_companies(
        self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True
    ) -> list[Company]:
        companies = self._load_companies()
        wanted = {country.upper() for country in countries}
        return [
            company
            for company in companies
            if company.country in wanted
            and (include_first_north or company.segment != ListingSegment.FIRST_NORTH)
        ]

    def get_research(self, ticker: str) -> CompanyResearch:
        normalized = ticker.strip().upper()
        for company in self._load_companies():
            if company.ticker == normalized:
                return CompanyResearch(
                    company=company,
                    financials=FinancialSnapshot(data_quality=DataQuality.THIN),
                    risks=("Sparse live-source data",),
                    evidence=(
                        Evidence(
                            label="Nasdaq Nordic listing source",
                            url=self.source_url,
                            source="nasdaq",
                        ),
                    ),
                    data_quality=DataQuality.THIN,
                )
        raise LookupError(f"No live research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        companies = self._load_companies()
        if self._last_error is not None:
            return [
                SourceCheck(
                    name="nasdaq nordic live data",
                    status="error",
                    detail=self._last_error,
                )
            ]
        return [
            SourceCheck(
                name="nasdaq nordic live data",
                status="ok",
                detail=f"{len(companies)} companies parsed from {self.source_url}",
            )
        ]

    def _load_companies(self) -> list[Company]:
        if self._companies is not None:
            return self._companies
        try:
            payload = self._fetcher(self.source_url)
            self._companies = _parse_live_company_payload(payload)
            self._last_error = None
        except Exception as exc:
            self._companies = []
            self._last_error = str(exc)
        return self._companies
```

Add parser helpers:

```python
def _parse_live_company_payload(payload: str) -> list[Company]:
    reader = csv.DictReader(StringIO(payload))
    companies: list[Company] = []
    for row in reader:
        ticker = (row.get("ticker") or row.get("symbol") or "").strip()
        name = (row.get("name") or row.get("company") or "").strip()
        country = (row.get("country") or "").strip().upper()
        exchange = (row.get("exchange") or "Nasdaq Nordic").strip()
        segment = _parse_listing_segment(row.get("segment") or row.get("market") or "")
        if not ticker or not name or country not in {"SE", "FI"}:
            continue
        companies.append(
            Company(
                name=name,
                ticker=ticker,
                country=country,
                exchange=exchange,
                segment=segment,
                sector=(row.get("sector") or None),
                currency=(row.get("currency") or None),
            )
        )
    return companies


def _parse_listing_segment(raw: str) -> ListingSegment:
    normalized = raw.strip().lower().replace("-", " ")
    if "first north" in normalized or normalized == "first_north":
        return ListingSegment.FIRST_NORTH
    if "spotlight" in normalized:
        return ListingSegment.SPOTLIGHT
    if "main" in normalized:
        return ListingSegment.MAIN_MARKET
    return ListingSegment.OTHER_PUBLIC
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/providers.py tests/test_providers.py
git commit -m "feat: parse live Nasdaq Nordic listings"
```

## Task 3: Live Failure Diagnostics

**Files:**
- Modify: `tests/test_providers.py`
- Modify: `src/investmentagent/providers.py`

- [ ] **Step 1: Write failing failure-diagnostics test**

Append to `tests/test_providers.py`:

```python
def test_live_provider_reports_fetch_failures_in_source_checks():
    def failing_fetcher(url: str) -> str:
        raise OSError("network unavailable")

    provider = LiveNasdaqNordicProvider(fetcher=failing_fetcher)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)
    checks = provider.source_checks()

    assert companies == []
    assert checks[0].name == "nasdaq nordic live data"
    assert checks[0].status == "error"
    assert "network unavailable" in checks[0].detail
```

- [ ] **Step 2: Run tests to verify the behavior**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py::test_live_provider_reports_fetch_failures_in_source_checks -v
```

Expected: PASS if Task 2 already implemented this behavior. If it fails, update `LiveNasdaqNordicProvider._load_companies()` and `source_checks()` so fetch failures are captured in `_last_error` and returned as a `SourceCheck` with `status="error"`.

- [ ] **Step 3: Run provider tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit if files changed**

If only the test was added:

```bash
git add tests/test_providers.py
git commit -m "test: cover live provider source failures"
```

If implementation also changed:

```bash
git add src/investmentagent/providers.py tests/test_providers.py
git commit -m "fix: report live provider source failures"
```

## Task 4: CLI Provider Selection

**Files:**
- Modify: `src/investmentagent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI provider tests**

Append to `tests/test_cli.py`:

```python
def test_watchlist_accepts_fixture_provider_option():
    result = runner.invoke(app, ["watchlist", "--provider", "fixture", "--limit", "1"])

    assert result.exit_code == 0
    assert "#1" in result.output


def test_sources_test_accepts_fixture_provider_option():
    result = runner.invoke(app, ["sources", "test", "--provider", "fixture"])

    assert result.exit_code == 0
    assert "bundled seed data: ok" in result.output


def test_cli_rejects_invalid_provider_option():
    result = runner.invoke(app, ["watchlist", "--provider", "bad"])

    assert result.exit_code != 0
    assert "provider must be 'fixture' or 'live'" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py -v
```

Expected: FAIL because `--provider` does not exist.

- [ ] **Step 3: Implement CLI provider selection**

Update `src/investmentagent/cli.py` imports:

```python
from investmentagent.providers import create_provider
```

Remove direct `FixtureResearchProvider` import.

Add helper:

```python
def _provider_from_option(name: str):
    try:
        return create_provider(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
```

Add a `provider` option to `watchlist`:

```python
provider_name: str = typer.Option("fixture", "--provider", help="Data provider: fixture or live."),
```

Inside `watchlist`, replace `provider = FixtureResearchProvider()` with:

```python
provider = _provider_from_option(provider_name)
```

Add the same `provider_name` option to `deep_dive` and `test_sources`. Use `_provider_from_option(provider_name)` in each command.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: add CLI provider selection"
```

## Task 5: README Provider Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Add this section after the command examples:

```markdown
## Data providers

InvestmentAgent defaults to deterministic fixture data:

```bash
investmentagent watchlist --provider fixture
```

The live provider is an early free-source integration point:

```bash
investmentagent sources test --provider live
investmentagent watchlist --provider live --country se,fi --limit 20
```

The live provider does not silently fall back to fixture data. If the public source cannot be fetched or parsed, `sources test --provider live` reports the failure and live watchlists may be empty.
```

- [ ] **Step 2: Run tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document provider selection"
```

## Task 6: Final Verification

**Files:**
- No expected code changes unless verification finds a defect.

- [ ] **Step 1: Run full test suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -v
```

Expected: PASS.

- [ ] **Step 2: Run fixture CLI smoke checks**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider fixture --country se,fi --limit 1
```

Expected: output includes `Research triage only. Not financial advice.` and `#1`.

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent sources test --provider fixture
```

Expected: output includes `bundled seed data: ok`.

- [ ] **Step 3: Run live diagnostics smoke check**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent sources test --provider live
```

Expected: command exits without traceback and prints either `nasdaq nordic live data: ok - ...` or `nasdaq nordic live data: error - ...`.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: clean working tree.

## Self-Review

Spec coverage:

- Provider selection: Task 1 and Task 4.
- Live provider skeleton: Task 2.
- Source diagnostics: Task 2 and Task 3.
- Graceful failure: Task 3.
- Mocked tests without internet: Task 2 and Task 3.
- Fixture default preserved: Task 4 and Task 6.
- README documentation: Task 5.

The plan intentionally does not add full quote, market-cap, ratio, news, filings, or AI synthesis. Those are excluded from the approved spec and should be separate follow-up branches.
