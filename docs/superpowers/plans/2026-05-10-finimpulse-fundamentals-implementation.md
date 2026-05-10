# Finimpulse Fundamentals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Finimpulse fundamentals enrichment for live Sweden/Finland watchlists using `FINIMPULSE_API_KEY`.

**Architecture:** Reuse the existing fundamentals enrichment boundary. Add a `FinimpulseFundamentalsProvider` that returns `FundamentalsSnapshot`, then update CLI selection so `auto` prefers Finimpulse, then Finnhub, then the free provider.

**Tech Stack:** Python 3, Typer CLI, standard-library `urllib`, pytest, existing InvestmentAgent provider/report/scoring modules.

---

## File Structure

- Modify `src/investmentagent/fundamentals.py`: add Finimpulse endpoint constants, symbol candidates, POST fetch helper, parser, provider, and token-safe errors.
- Modify `src/investmentagent/cli.py`: import Finimpulse provider, accept `finimpulse` mode, read `FINIMPULSE_API_KEY`, and choose it before Finnhub in `auto`.
- Modify `tests/test_fundamentals.py`: add deterministic Finimpulse response fixtures and provider tests.
- Modify `tests/test_cli.py`: add CLI selection, missing-token, blank-token, and metadata tests.
- No new runtime dependencies.

## Task 1: Finimpulse Provider and Parser

**Files:**
- Modify: `src/investmentagent/fundamentals.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Write failing tests for candidates, parsing, and source checks**

Update the import block in `tests/test_fundamentals.py`:

```python
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    finimpulse_symbol_candidates,
    finnhub_symbol_candidates,
    yahoo_symbol_candidates,
)
```

Add this fixture near `finnhub_payload`:

```python
def finimpulse_search_payload() -> str:
    return json.dumps(
        {
            "status_code": 20000,
            "status_message": "OK",
            "data": {
                "symbols": ["KAR.ST"],
                "quote_types": ["stock"],
                "limit": 1,
            },
            "result": {
                "total_count": 1,
                "items_count": 1,
                "items": [
                    {
                        "symbol": "KAR.ST",
                        "short_name": "Karnov Group AB",
                        "long_name": "Karnov Group AB (publ)",
                        "quote_type": "stock",
                        "currency": "SEK",
                        "regular_market_price": 72.0,
                        "average_daily_volume_10_day": 485039,
                        "one_year_return": -16.473,
                        "fifty_two_week_high_change_percent": -44.272444,
                        "market_region": "SE",
                        "sector": "Industrials",
                        "industry": "Specialty Business Services",
                        "amount": 7024167424,
                        "revenue_growth": 0.24636247668524147,
                        "net_margin": 0.36760195,
                        "free_cash_flow_margin": 0.19304025,
                        "debt_to_equity": 0.29354096,
                    }
                ],
            },
        }
    )
```

Add these tests near the Finnhub tests:

```python
def test_finimpulse_symbol_candidates_for_sweden_and_finland():
    assert finimpulse_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert finimpulse_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_finimpulse_symbol_candidates_normalize_spaces_and_share_classes():
    assert finimpulse_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_finimpulse_provider_parses_search_result_with_token_safe_evidence():
    requested: list[tuple[str, str, dict[str, str]]] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested.append((url, payload, headers))
        return finimpulse_search_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 702.42
    assert snapshot.financials.revenue_growth_pct == 24.64
    assert snapshot.financials.operating_margin_pct == 36.76
    assert snapshot.financials.debt_to_equity == 0.29354096
    assert snapshot.financials.one_year_return_pct == -16.473
    assert snapshot.financials.distance_from_52w_high_pct == -44.272444
    assert snapshot.financials.average_daily_value_eur == 3_492_280.8
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "finimpulse"
    assert "KAR.ST" in snapshot.evidence.label
    assert "secret-token" not in snapshot.evidence.url
    assert requested
    assert requested[0][0] == "https://api.finimpulse.com/v1/search"
    assert "secret-token" in requested[0][2]["Authorization"]
```

Add source-safety tests:

```python
def test_finimpulse_provider_returns_none_for_empty_search_results():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, payload, headers: json.dumps(
            {"status_code": 20000, "result": {"items": []}}
        ),
    )

    assert provider.get_fundamentals(make_company()) is None


def test_finimpulse_source_check_warns_without_leaking_token_when_lookups_fail():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        raise RuntimeError(f"failed Authorization: {headers['Authorization']}")

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.name == "finimpulse fundamentals"
    assert check.status == "warning"
    assert "no successful" in check.detail.lower()
    assert "secret-token" not in check.detail
    assert "<redacted>" in check.detail
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py::test_finimpulse_symbol_candidates_for_sweden_and_finland tests/test_fundamentals.py::test_finimpulse_provider_parses_search_result_with_token_safe_evidence -v
```

Expected: fail because Finimpulse names are not implemented yet.

- [ ] **Step 3: Implement the provider and parser**

In `src/investmentagent/fundamentals.py`, add constants near the other provider constants:

```python
FINIMPULSE_SEARCH_URL = "https://api.finimpulse.com/v1/search"
FINIMPULSE_SEARCH_DOC_URL = "https://developers.finimpulse.com/v1/search/"
FINIMPULSE_FETCH_TIMEOUT_SECONDS = 3
```

Add `FinimpulseFundamentalsProvider` before `FinnhubFundamentalsProvider`:

```python
class FinimpulseFundamentalsProvider:
    def __init__(
        self,
        api_key: str,
        fetcher: Callable[[str, str, dict[str, str]], str] | None = None,
    ) -> None:
        self.api_key = api_key
        self._fetcher = fetcher or _post_json
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in finimpulse_symbol_candidates(company):
            self.attempted_lookups += 1
            payload = json.dumps(
                {"symbols": [symbol], "quote_types": ["stock"], "limit": 1}
            )
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            try:
                snapshot = _parse_finimpulse_search_payload(
                    payload=self._fetcher(FINIMPULSE_SEARCH_URL, payload, headers),
                    symbol=symbol,
                    fallback_currency=company.currency,
                )
            except Exception as exc:
                self.last_error = _token_safe_error(exc, self.api_key)
                continue
            if snapshot is not None:
                self.successful_lookups += 1
                self.last_error = None
                return snapshot
        return None

    def source_check(self) -> SourceCheck:
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="finimpulse fundamentals",
                status="warning",
                detail="No lookups attempted for Finimpulse fundamentals",
            )

        ratio = (
            f"{self.successful_lookups}/{self.attempted_lookups} "
            "Finimpulse lookups parsed"
        )
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(name="finimpulse fundamentals", status="ok", detail=ratio)

        if self.successful_lookups == 0:
            detail = f"No successful Finimpulse fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="finimpulse fundamentals",
                status="warning",
                detail=detail,
            )

        return SourceCheck(name="finimpulse fundamentals", status="warning", detail=ratio)
```

Add symbol candidates:

```python
def finimpulse_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)
```

Add parser:

```python
def _parse_finimpulse_search_payload(
    payload: str, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    data = json.loads(payload)
    result = _dict_value(data, "result")
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return None
    item = next(
        (
            candidate
            for candidate in items
            if isinstance(candidate, dict)
            and str(candidate.get("symbol") or "").upper() == symbol.upper()
        ),
        None,
    )
    if item is None:
        item = items[0] if isinstance(items[0], dict) else None
    if item is None:
        return None

    currency = str(item.get("currency") or fallback_currency or "").upper()
    fx_rate = _EUR_RATES.get(currency)
    market_cap_eur_m = _eur_m(_number(item, "amount"), fx_rate)
    average_daily_value_eur = None
    price = _number(item, "regular_market_price")
    average_volume = _number(item, "average_daily_volume_10_day")
    if price is not None and average_volume is not None and fx_rate is not None:
        average_daily_value_eur = round(price * average_volume * fx_rate, 2)

    financials = FinancialSnapshot(
        revenue_growth_pct=_ratio_to_percent(_number(item, "revenue_growth")),
        operating_margin_pct=_ratio_to_percent(
            _first_number(item, ("net_margin", "free_cash_flow_margin"))
        ),
        debt_to_equity=_number(item, "debt_to_equity"),
        one_year_return_pct=_number(item, "one_year_return"),
        distance_from_52w_high_pct=_number(item, "fifty_two_week_high_change_percent"),
        average_daily_value_eur=average_daily_value_eur,
        data_quality=DataQuality.PARTIAL,
    )
    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=financials,
        evidence=Evidence(
            label=f"Finimpulse fundamentals lookup ({symbol})",
            url=FINIMPULSE_SEARCH_DOC_URL,
            source="finimpulse",
        ),
    )
```

Add helper:

```python
def _ratio_to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1 <= value <= 1:
        return round(value * 100, 2)
    return round(value, 2)
```

Add POST helper near `_fetch_url`:

```python
def _post_json(url: str, payload: str, headers: dict[str, str]) -> str:
    request = Request(
        url,
        data=payload.encode("utf-8"),
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
            **headers,
        },
        method="POST",
    )
    with urlopen(request, timeout=FINIMPULSE_FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_fundamentals.py::test_finimpulse_symbol_candidates_for_sweden_and_finland tests/test_fundamentals.py::test_finimpulse_symbol_candidates_normalize_spaces_and_share_classes tests/test_fundamentals.py::test_finimpulse_provider_parses_search_result_with_token_safe_evidence tests/test_fundamentals.py::test_finimpulse_provider_returns_none_for_empty_search_results tests/test_fundamentals.py::test_finimpulse_source_check_warns_without_leaking_token_when_lookups_fail -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "feat: parse finimpulse fundamentals"
```

## Task 2: CLI Selection and Metadata

**Files:**
- Modify: `src/investmentagent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Update test names and fixtures around existing fundamentals tests.

Add these tests after the existing Finnhub auto test:

```python
def test_watchlist_auto_fundamentals_prefers_finimpulse_over_finnhub(monkeypatch):
    wrapped = {}

    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class FinimpulseProvider:
        def __init__(self, api_key):
            self.api_key = api_key

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

    monkeypatch.setenv("FINIMPULSE_API_KEY", "finimpulse-token")
    monkeypatch.setenv("FINNHUB_API_KEY", "finnhub-token")
    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "FinimpulseFundamentalsProvider", FinimpulseProvider, raising=False)
    monkeypatch.setattr(cli, "FinnhubFundamentalsProvider", FinnhubProvider, raising=False)
    monkeypatch.setattr(cli, "EnrichedResearchProvider", EnrichedProvider, raising=False)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--limit", "7"])

    assert result.exit_code == 0
    assert isinstance(wrapped["fundamentals_provider"], FinimpulseProvider)
    assert wrapped["fundamentals_provider"].api_key == "finimpulse-token"
    assert wrapped["max_enrichments"] == 7
```

Add explicit token tests:

```python
def test_watchlist_explicit_finimpulse_requires_api_key(monkeypatch):
    monkeypatch.delenv("FINIMPULSE_API_KEY", raising=False)

    result = runner.invoke(
        app, ["watchlist", "--provider", "live", "--fundamentals", "finimpulse"]
    )

    assert result.exit_code != 0
    assert "FINIMPULSE_API_KEY is required" in result.output


def test_watchlist_explicit_finimpulse_rejects_blank_api_key(monkeypatch):
    monkeypatch.setenv("FINIMPULSE_API_KEY", "   ")

    result = runner.invoke(
        app, ["watchlist", "--provider", "live", "--fundamentals", "finimpulse"]
    )

    assert result.exit_code != 0
    assert "FINIMPULSE_API_KEY is required" in result.output
```

Add metadata test near the Finnhub metadata test:

```python
def test_watchlist_saves_effective_finimpulse_fundamentals_metadata(monkeypatch):
    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class FinimpulseProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    class EnrichedProvider:
        def __init__(self, base_provider, fundamentals_provider, max_enrichments=None):
            self.base_provider = base_provider

        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return self.base_provider.source_checks()

    monkeypatch.setenv("FINIMPULSE_API_KEY", "finimpulse-token")
    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "FinimpulseFundamentalsProvider", FinimpulseProvider, raising=False)
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
    assert payload["metadata"]["fundamentals"] == "finimpulse"
```

Update the invalid fundamentals assertion to include `finimpulse`:

```python
assert "fundamentals must be 'auto', 'off', 'free', 'finnhub', or 'finimpulse'" in result.output
```

Make the existing `test_watchlist_auto_fundamentals_wraps_live_provider` clear both keyed env vars:

```python
monkeypatch.delenv("FINIMPULSE_API_KEY", raising=False)
monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
```

Make the existing Finnhub auto test clear Finimpulse:

```python
monkeypatch.delenv("FINIMPULSE_API_KEY", raising=False)
```

- [ ] **Step 2: Run focused CLI tests to verify failures**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_auto_fundamentals_prefers_finimpulse_over_finnhub tests/test_cli.py::test_watchlist_explicit_finimpulse_requires_api_key tests/test_cli.py::test_watchlist_rejects_invalid_fundamentals_before_provider_work -v
```

Expected: fail because CLI does not know `finimpulse` yet.

- [ ] **Step 3: Implement CLI selection**

Update imports in `src/investmentagent/cli.py`:

```python
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    YahooFundamentalsProvider,
)
```

Update validation:

```python
def _normalize_fundamentals_option(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "off", "free", "finnhub", "finimpulse"}:
        raise typer.BadParameter(
            "fundamentals must be 'auto', 'off', 'free', 'finnhub', or 'finimpulse'"
        )
    return normalized
```

Add a generic env helper or Finimpulse-specific helper:

```python
def _api_key_from_environment(name: str) -> str | None:
    api_key = os.environ.get(name)
    if api_key is None:
        return None
    stripped = api_key.strip()
    return stripped or None
```

Update `_effective_fundamentals_mode`:

```python
def _effective_fundamentals_mode(
    normalized_mode: str,
    normalized_provider_name: str,
    finimpulse_api_key: str | None,
    finnhub_api_key: str | None,
) -> str:
    if normalized_provider_name != "live":
        return "off"
    if normalized_mode == "auto":
        if finimpulse_api_key:
            return "finimpulse"
        if finnhub_api_key:
            return "finnhub"
        return "free"
    return normalized_mode
```

In `watchlist`, read both keys:

```python
finimpulse_api_key = _api_key_from_environment("FINIMPULSE_API_KEY")
finnhub_api_key = _api_key_from_environment("FINNHUB_API_KEY")
effective_fundamentals = _effective_fundamentals_mode(
    normalized_fundamentals,
    normalized_provider_name,
    finimpulse_api_key,
    finnhub_api_key,
)
```

Update explicit-mode validation and provider construction:

```python
if effective_fundamentals == "finimpulse" and finimpulse_api_key is None:
    raise typer.BadParameter("FINIMPULSE_API_KEY is required for --fundamentals finimpulse")
if effective_fundamentals == "finnhub" and finnhub_api_key is None:
    raise typer.BadParameter("FINNHUB_API_KEY is required for --fundamentals finnhub")

fundamentals_provider = None
if effective_fundamentals == "free":
    fundamentals_provider = YahooFundamentalsProvider()
elif effective_fundamentals == "finnhub":
    fundamentals_provider = FinnhubFundamentalsProvider(finnhub_api_key)
elif effective_fundamentals == "finimpulse":
    fundamentals_provider = FinimpulseFundamentalsProvider(finimpulse_api_key)
```

Update help text to:

```python
help="Fundamentals enrichment mode: auto, off, free, finnhub, or finimpulse.",
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: select finimpulse fundamentals from cli"
```

## Task 3: Environment Guidance and Full Verification

**Files:**
- Modify: `.env.example` if created
- Verify: full repo

- [ ] **Step 1: Decide whether to add `.env.example`**

If the repository has no `.env.example`, create one with placeholders only:

```text
FINIMPULSE_API_KEY=
FINNHUB_API_KEY=
```

Do not include real tokens.

- [ ] **Step 2: Run full test suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run token-safe live smoke if `.env` contains Finimpulse token**

Only run if local `.env` has `FINIMPULSE_API_KEY` or the old token is still temporarily stored under `FINNHUB_API_KEY`. Do not print the token.

If needed, use:

```bash
set -a
source .env
set +a
export FINIMPULSE_API_KEY="${FINIMPULSE_API_KEY:-$FINNHUB_API_KEY}"
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --fundamentals finimpulse --country se,fi --limit 5 --verbose
```

Expected: Nasdaq source check ok, Finimpulse source check at least partially successful, rendered watchlist output, and no token text or `Authorization` header in output.

- [ ] **Step 4: Commit env example if created**

```bash
git add .env.example
git commit -m "docs: add env example for fundamentals providers"
```

If no files changed, skip this commit.

## Self-Review

- Spec coverage: provider, data mapping, CLI modes, auto preference order, token safety, metadata, env guidance, and full verification are covered.
- Placeholder scan: no TODO/TBD placeholders remain.
- Type consistency: plan uses existing `FundamentalsSnapshot`, `FinancialSnapshot`, `Evidence`, `SourceCheck`, `DataQuality`, and `EnrichedResearchProvider` names.
