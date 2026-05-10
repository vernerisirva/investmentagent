# Live Market Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve live watchlist ranking and report usefulness by deriving honest thin-data market signals from Nasdaq Nordic screener rows.

**Architecture:** Keep all live-source parsing inside `src/investmentagent/providers.py`. Add a small private live-row metadata store keyed by ticker so `get_research()` can attach parsed price/currency, catalysts, and risks without changing public model fields or fixture behavior.

**Tech Stack:** Python 3.12, dataclasses, pytest, Typer CLI smoke tests.

---

### Task 1: Parse Live Numeric Fields

**Files:**
- Modify: `tests/test_providers.py`
- Modify: `src/investmentagent/providers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_providers.py`:

```python
def test_live_provider_research_includes_market_signal_fields():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("ACAST")

    assert research.financials.price == 34.9
    assert research.financials.currency == "SEK"
    assert "Live price available from Nasdaq Nordic" in research.catalysts
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py::test_live_provider_research_includes_market_signal_fields -v
```

Expected: FAIL because live research currently creates an empty `FinancialSnapshot`.

- [ ] **Step 3: Write minimal implementation**

In `src/investmentagent/providers.py`, add a private metadata dict in `LiveNasdaqNordicProvider`, populate it while parsing Nasdaq rows, and use it in `get_research()`:

```python
self._live_market_rows: dict[str, dict] = {}
```

Parse `lastSalePrice` and `currency` from Nasdaq rows and return:

```python
FinancialSnapshot(
    price=market_row.get("price"),
    currency=market_row.get("currency"),
    data_quality=DataQuality.THIN,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run the focused test from Step 2. Expected: PASS.

- [ ] **Step 5: Run provider tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py -v
```

Expected: PASS.

### Task 2: Add Live Signal Catalysts And Risks

**Files:**
- Modify: `tests/test_providers.py`
- Modify: `src/investmentagent/providers.py`

- [ ] **Step 1: Write failing signal tests**

Add to `tests/test_providers.py`:

```python
def test_live_provider_research_adds_positive_momentum_signal():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("ACAST")

    assert "Positive intraday momentum" in research.catalysts


def test_live_provider_research_adds_selloff_and_liquidity_risks():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("AALLON")

    assert "Sharp intraday selloff" in research.risks
    assert "Low live turnover" in research.risks
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py::test_live_provider_research_adds_positive_momentum_signal tests/test_providers.py::test_live_provider_research_adds_selloff_and_liquidity_risks -v
```

Expected: FAIL because no signal catalysts or risks are derived yet.

- [ ] **Step 3: Implement signal helpers**

Add private helpers in `src/investmentagent/providers.py`:

```python
def _parse_live_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("%", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
```

Use parsed `percentageChange`, `turnover`, and `volume` to build catalysts and risks according to the spec.

- [ ] **Step 4: Run focused tests**

Run the focused command from Step 2. Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: PASS.

### Task 3: Verify Real Live CLI Behavior

**Files:**
- No file changes expected.

- [ ] **Step 1: Run fixture smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider fixture --country se,fi --limit 1
```

Expected: command exits 0 and prints a watchlist item.

- [ ] **Step 2: Run live source diagnostic**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent sources test --provider live
```

Expected: command exits 0 and reports `nasdaq nordic live data: ok`.

- [ ] **Step 3: Run live watchlist smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --country se,fi --limit 3
```

Expected: command exits 0 and prints live candidates with signal reasons or risks.

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add src/investmentagent/providers.py tests/test_providers.py docs/superpowers/plans/2026-05-10-live-market-signals-implementation.md
git commit -m "feat: add live market signals"
```
