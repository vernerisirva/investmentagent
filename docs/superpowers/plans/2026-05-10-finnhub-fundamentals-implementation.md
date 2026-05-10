# Finnhub Fundamentals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Finnhub fundamentals enrichment for live Sweden/Finland watchlists using `FINNHUB_API_KEY`, while preserving the no-key free fallback.

**Architecture:** Reuse the existing `EnrichedResearchProvider` boundary. Add a `FinnhubFundamentalsProvider` that returns the same `FundamentalsSnapshot` model as `YahooFundamentalsProvider`, then update CLI mode selection so `auto` chooses Finnhub only when the key exists.

**Tech Stack:** Python 3, Typer CLI, standard-library `urllib`, pytest, existing InvestmentAgent model/provider/report modules.

---

## File Structure

- Modify `src/investmentagent/fundamentals.py`: add Finnhub URLs, symbol candidates, request helper, parser, and source checks.
- Modify `src/investmentagent/cli.py`: import Finnhub provider, accept `finnhub` mode, choose effective mode from environment, construct the correct fundamentals provider.
- Modify `tests/test_fundamentals.py`: add deterministic Finnhub parser, symbol, source-check, and token-redaction tests.
- Modify `tests/test_cli.py`: add CLI mode-selection tests for explicit and automatic Finnhub behavior.
- No new runtime dependencies.

## Task 1: Finnhub Symbol Candidates and Parser

**Files:**
- Modify: `src/investmentagent/fundamentals.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Write failing tests for symbols and payload parsing**

Add these imports in `tests/test_fundamentals.py`:

```python
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FinnhubFundamentalsProvider,
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    finnhub_symbol_candidates,
    yahoo_symbol_candidates,
)
```

Add this fixture payload and tests near the Yahoo provider tests:

```python
def finnhub_payload() -> str:
    return json.dumps(
        {
            "profile": {
                "country": "SE",
                "currency": "SEK",
                "exchange": "ST",
                "marketCapitalization": 5500.0,
                "name": "Karnov Group AB",
                "ticker": "KAR.ST",
            },
            "metrics": {
                "metric": {
                    "peBasicExclExtraTTM": 11.2,
                    "pbQuarterly": 1.1,
                    "revenueGrowthTTMYoy": 8.0,
                    "operatingMarginTTM": 14.0,
                    "totalDebt/totalEquityQuarterly": 52.0,
                }
            },
        }
    )


def test_finnhub_symbol_candidates_for_sweden_and_finland():
    assert finnhub_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert finnhub_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_finnhub_symbol_candidates_normalize_spaces_and_share_classes():
    assert finnhub_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_finnhub_provider_parses_profile_and_metrics_with_token_safe_evidence():
    requested_urls: list[str] = []
    payload = json.loads(finnhub_payload())

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        if "/stock/profile2" in url:
            return json.dumps(payload["profile"])
        return json.dumps(payload["metrics"])

    provider = FinnhubFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 550.0
    assert snapshot.financials.pe_ratio == 11.2
    assert snapshot.financials.price_to_book == 1.1
    assert snapshot.financials.revenue_growth_pct == 8.0
    assert snapshot.financials.operating_margin_pct == 14.0
    assert snapshot.financials.debt_to_equity == 0.52
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "finnhub"
    assert "KAR.ST" in snapshot.evidence.label
    assert "secret-token" not in snapshot.evidence.url
    assert "token=" not in snapshot.evidence.url
    assert requested_urls
    assert any("secret-token" in url for url in requested_urls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_fundamentals.py::test_finnhub_symbol_candidates_for_sweden_and_finland tests/test_fundamentals.py::test_finnhub_provider_parses_profile_and_metrics_with_token_safe_evidence -v
```

Expected: fail because `FinnhubFundamentalsProvider` and `finnhub_symbol_candidates` do not exist.

- [ ] **Step 3: Implement symbol candidates and parsing**

Add constants near the Yahoo constants in `src/investmentagent/fundamentals.py`:

```python
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={token}"
FINNHUB_METRIC_URL = (
    "https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={token}"
)
FINNHUB_PROFILE_DOC_URL = "https://finnhub.io/docs/api/company-profile2"
FINNHUB_FETCH_TIMEOUT_SECONDS = 3
```

Add symbol generation after `yahoo_symbol_candidates`:

```python
def finnhub_symbol_candidates(company: Company) -> tuple[str, ...]:
    suffix_by_country = {"SE": ".ST", "FI": ".HE"}
    suffix = suffix_by_country.get(company.country.upper())
    if suffix is None:
        return ()

    ticker = company.ticker.strip().upper()
    normalized = "-".join(ticker.split())
    compact = normalized.replace("-", "")

    candidates = [f"{normalized}{suffix}"]
    if compact != normalized:
        candidates.append(f"{compact}{suffix}")
    return tuple(dict.fromkeys(candidates))
```

Add the provider before `EnrichedResearchProvider`:

```python
class FinnhubFundamentalsProvider:
    def __init__(
        self, api_key: str, fetcher: Callable[[str], str] | None = None
    ) -> None:
        self.api_key = api_key
        self._fetcher = fetcher or _fetch_url
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in finnhub_symbol_candidates(company):
            self.attempted_lookups += 1
            profile_url = _finnhub_profile_url(symbol, self.api_key)
            metric_url = _finnhub_metric_url(symbol, self.api_key)
            try:
                payload = json.dumps(
                    {
                        "profile": json.loads(self._fetcher(profile_url)),
                        "metrics": json.loads(self._fetcher(metric_url)),
                    }
                )
                snapshot = _parse_finnhub_payload(
                    payload=payload,
                    symbol=symbol,
                    fallback_currency=company.currency,
                )
            except Exception as exc:
                self.last_error = _token_safe_error(exc)
                continue
            if snapshot is not None:
                self.successful_lookups += 1
                self.last_error = None
                return snapshot
        return None

    def source_check(self) -> SourceCheck:
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="finnhub fundamentals",
                status="warning",
                detail="No lookups attempted for Finnhub fundamentals",
            )

        ratio = f"{self.successful_lookups}/{self.attempted_lookups} Finnhub lookups parsed"
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(name="finnhub fundamentals", status="ok", detail=ratio)

        if self.successful_lookups == 0:
            detail = f"No successful Finnhub fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(name="finnhub fundamentals", status="warning", detail=detail)

        return SourceCheck(name="finnhub fundamentals", status="warning", detail=ratio)
```

Add parser helpers near the Yahoo parser:

```python
def _parse_finnhub_payload(
    payload: str, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    data = json.loads(payload)
    profile = _dict_value(data, "profile")
    metrics_payload = _dict_value(data, "metrics")
    metrics = _dict_value(metrics_payload, "metric")

    currency = str(profile.get("currency") or fallback_currency or "").upper()
    fx_rate = _EUR_RATES.get(currency)
    market_cap = _number(profile.get("marketCapitalization"))
    market_cap_eur_m = _currency_m_to_eur_m(market_cap, fx_rate)

    financials = FinancialSnapshot(
        pe_ratio=_first_number(metrics, ("peBasicExclExtraTTM", "peNormalizedAnnual")),
        price_to_book=_first_number(metrics, ("pbQuarterly", "pbAnnual")),
        revenue_growth_pct=_first_number(
            metrics, ("revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy")
        ),
        operating_margin_pct=_first_number(metrics, ("operatingMarginTTM", "operatingMarginAnnual")),
        debt_to_equity=_debt_to_equity_ratio(
            _first_number(metrics, ("totalDebt/totalEquityQuarterly", "totalDebt/totalEquityAnnual"))
        ),
        data_quality=DataQuality.PARTIAL,
    )

    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=financials,
        evidence=Evidence(
            label=f"Finnhub fundamentals lookup ({symbol})",
            url=FINNHUB_PROFILE_DOC_URL,
            source="finnhub",
        ),
    )
```

Add numeric helpers:

```python
def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(source.get(key))
        if value is not None:
            return value
    return None


def _currency_m_to_eur_m(value_m: float | None, fx_rate: float | None) -> float | None:
    if value_m is None or fx_rate is None:
        return None
    return round(value_m * fx_rate, 2)


def _debt_to_equity_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 100, 4)


def _token_safe_error(exc: Exception) -> str:
    return str(exc).replace("token=", "token=<redacted>")
```

Add URL builders:

```python
def _finnhub_profile_url(symbol: str, token: str) -> str:
    return FINNHUB_PROFILE_URL.format(symbol=quote(symbol, safe=""), token=quote(token, safe=""))


def _finnhub_metric_url(symbol: str, token: str) -> str:
    return FINNHUB_METRIC_URL.format(symbol=quote(symbol, safe=""), token=quote(token, safe=""))
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_fundamentals.py::test_finnhub_symbol_candidates_for_sweden_and_finland tests/test_fundamentals.py::test_finnhub_symbol_candidates_normalize_spaces_and_share_classes tests/test_fundamentals.py::test_finnhub_provider_parses_profile_and_metrics_with_token_safe_evidence -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "feat: parse finnhub fundamentals"
```

## Task 2: Finnhub Error Handling and Source Checks

**Files:**
- Modify: `src/investmentagent/fundamentals.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Write failing tests for malformed data and token-safe errors**

Add these tests:

```python
def test_finnhub_provider_returns_none_for_malformed_or_missing_data():
    provider = FinnhubFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url: json.dumps({}),
    )

    assert provider.get_fundamentals(make_company()) is None


def test_finnhub_source_check_warns_without_leaking_token_when_all_lookups_fail():
    def fetcher(url: str) -> str:
        raise RuntimeError(f"failed url {url}")

    provider = FinnhubFundamentalsProvider(api_key="secret-token", fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.name == "finnhub fundamentals"
    assert check.status == "warning"
    assert "no successful" in check.detail.lower()
    assert "secret-token" not in check.detail
    assert "token=" not in check.detail


def test_finnhub_source_check_ok_when_lookup_succeeds():
    payload = json.loads(finnhub_payload())

    def fetcher(url: str) -> str:
        if "/stock/profile2" in url:
            return json.dumps(payload["profile"])
        return json.dumps(payload["metrics"])

    provider = FinnhubFundamentalsProvider(
        api_key="secret-token",
        fetcher=fetcher,
    )
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Finnhub lookups parsed" in check.detail
```

- [ ] **Step 2: Run tests to verify failures**

Run:

```bash
pytest tests/test_fundamentals.py::test_finnhub_provider_returns_none_for_malformed_or_missing_data tests/test_fundamentals.py::test_finnhub_source_check_warns_without_leaking_token_when_all_lookups_fail tests/test_fundamentals.py::test_finnhub_source_check_ok_when_lookup_succeeds -v
```

Expected: failures around fixture shape and token redaction until implementation is hardened.

- [ ] **Step 3: Harden fetch and redaction**

Update `FinnhubFundamentalsProvider` so a test fetcher can return either combined fixture payloads or endpoint-shaped payloads:

```python
raw_profile = json.loads(self._fetcher(profile_url))
if "profile" in raw_profile and "metrics" in raw_profile:
    payload = json.dumps(raw_profile)
else:
    payload = json.dumps(
        {
            "profile": raw_profile,
            "metrics": json.loads(self._fetcher(metric_url)),
        }
    )
```

Update `_token_safe_error` to remove the token value from full URLs:

```python
def _token_safe_error(exc: Exception) -> str:
    message = str(exc)
    return re.sub(r"token=[^&\\s]+", "token=<redacted>", message)
```

Add `import re` at the top of `src/investmentagent/fundamentals.py`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_fundamentals.py -v
```

Expected: all fundamentals tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "test: cover finnhub source safety"
```

## Task 3: CLI Mode Selection

**Files:**
- Modify: `src/investmentagent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests after `test_watchlist_auto_fundamentals_wraps_live_provider`:

```python
def test_watchlist_auto_fundamentals_prefers_finnhub_when_key_is_present(monkeypatch):
    wrapped = {}

    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class YahooProvider:
        pass

    class FinnhubProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    class EnrichedProvider:
        def __init__(self, base_provider, fundamentals_provider, max_enrichments=None):
            wrapped["fundamentals_provider"] = fundamentals_provider
            wrapped["max_enrichments"] = max_enrichments
            self.base_provider = base_provider

        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return self.base_provider.source_checks()

    monkeypatch.setenv("FINNHUB_API_KEY", "secret-token")
    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "YahooFundamentalsProvider", YahooProvider, raising=False)
    monkeypatch.setattr(cli, "FinnhubFundamentalsProvider", FinnhubProvider, raising=False)
    monkeypatch.setattr(cli, "EnrichedResearchProvider", EnrichedProvider, raising=False)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--limit", "7"])

    assert result.exit_code == 0
    assert isinstance(wrapped["fundamentals_provider"], FinnhubProvider)
    assert wrapped["fundamentals_provider"].api_key == "secret-token"
    assert wrapped["max_enrichments"] == 7


def test_watchlist_explicit_finnhub_requires_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    result = runner.invoke(
        app, ["watchlist", "--provider", "live", "--fundamentals", "finnhub"]
    )

    assert result.exit_code != 0
    assert "FINNHUB_API_KEY is required" in result.output


def test_watchlist_rejects_invalid_fundamentals_mentions_finnhub(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid fundamentals mode")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--fundamentals", "bad"])

    assert result.exit_code != 0
    assert "fundamentals must be 'auto', 'off', 'free', or 'finnhub'" in result.output
```

Replace the old invalid-fundamentals assertion with the updated message.

- [ ] **Step 2: Run tests to verify failures**

Run:

```bash
pytest tests/test_cli.py::test_watchlist_auto_fundamentals_prefers_finnhub_when_key_is_present tests/test_cli.py::test_watchlist_explicit_finnhub_requires_api_key tests/test_cli.py::test_watchlist_rejects_invalid_fundamentals_before_provider_work -v
```

Expected: fail because CLI does not import or select Finnhub yet, and the validation message still omits `finnhub`.

- [ ] **Step 3: Implement CLI selection**

Update imports in `src/investmentagent/cli.py`:

```python
import os
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FinnhubFundamentalsProvider,
    YahooFundamentalsProvider,
)
```

Update validation:

```python
def _normalize_fundamentals_option(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "off", "free", "finnhub"}:
        raise typer.BadParameter(
            "fundamentals must be 'auto', 'off', 'free', or 'finnhub'"
        )
    return normalized
```

Replace `_effective_fundamentals_mode` with:

```python
def _effective_fundamentals_mode(
    normalized_mode: str, normalized_provider_name: str, finnhub_api_key: str | None
) -> str:
    if normalized_provider_name != "live":
        return "off"
    if normalized_mode == "auto":
        return "finnhub" if finnhub_api_key else "free"
    return normalized_mode
```

In `watchlist`, read and validate the key before constructing enrichment:

```python
finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
effective_fundamentals = _effective_fundamentals_mode(
    normalized_fundamentals, normalized_provider_name, finnhub_api_key
)
if effective_fundamentals == "finnhub" and not finnhub_api_key:
    raise typer.BadParameter("FINNHUB_API_KEY is required for --fundamentals finnhub")
```

Update enrichment construction:

```python
if effective_fundamentals == "free":
    fundamentals_provider = YahooFundamentalsProvider()
elif effective_fundamentals == "finnhub":
    fundamentals_provider = FinnhubFundamentalsProvider(finnhub_api_key)
else:
    fundamentals_provider = None

if fundamentals_provider is not None:
    provider = EnrichedResearchProvider(
        provider,
        fundamentals_provider,
        max_enrichments=limit,
    )
```

Update the Typer help text to:

```python
help="Fundamentals enrichment mode: auto, off, free, or finnhub.",
```

- [ ] **Step 4: Run focused CLI tests**

Run:

```bash
pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: select finnhub fundamentals from cli"
```

## Task 4: Metadata, Full Verification, and Live Smoke

**Files:**
- Modify: `tests/test_cli.py`
- Verify: full repo

- [ ] **Step 1: Add saved metadata test for Finnhub**

Add this test near existing metadata tests:

```python
def test_watchlist_saves_effective_finnhub_fundamentals_metadata(monkeypatch):
    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class FinnhubProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    class EnrichedProvider:
        def __init__(self, base_provider, fundamentals_provider, max_enrichments=None):
            self.base_provider = base_provider

        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return self.base_provider.source_checks()

    monkeypatch.setenv("FINNHUB_API_KEY", "secret-token")
    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "FinnhubFundamentalsProvider", FinnhubProvider, raising=False)
    monkeypatch.setattr(cli, "EnrichedResearchProvider", EnrichedProvider, raising=False)

    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "live",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["fundamentals"] == "finnhub"
```

- [ ] **Step 2: Run metadata test**

Run:

```bash
pytest tests/test_cli.py::test_watchlist_saves_effective_finnhub_fundamentals_metadata -v
```

Expected: pass after Task 3.

- [ ] **Step 3: Run full test suite**

Run:

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 4: Optional live smoke with user-provided environment**

Only run this after the user has exported `FINNHUB_API_KEY` in the shell/session:

```bash
investmentagent watchlist --provider live --fundamentals finnhub --country se,fi --limit 5 --verbose
```

Expected: report renders; stderr includes `finnhub fundamentals` source check; output does not contain the API key or `token=`.

- [ ] **Step 5: Commit final verification test if needed**

```bash
git add tests/test_cli.py
git commit -m "test: record finnhub fundamentals metadata"
```

If no files changed after Task 3, skip this commit.

## Self-Review

- Spec coverage: the plan covers provider creation, environment-only key access, `auto|off|free|finnhub` CLI behavior, token-safe evidence/source checks, data mapping, enrichment budget preservation through existing wrapper, metadata, and deterministic tests.
- Placeholder scan: no TODO/TBD placeholders remain.
- Type consistency: all plan snippets use existing `Company`, `FundamentalsSnapshot`, `FinancialSnapshot`, `Evidence`, `SourceCheck`, `DataQuality`, and `EnrichedResearchProvider` names.
