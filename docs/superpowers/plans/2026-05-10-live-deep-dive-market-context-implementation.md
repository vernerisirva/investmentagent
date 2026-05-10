# Live Deep Dive Market Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add available live price context to deep-dive valuation text without changing provider interfaces or claiming unavailable valuation data.

**Architecture:** Keep the change in `src/investmentagent/reports.py`, where deep-dive valuation sentences are assembled. Tests exercise `build_deep_dive()` with an in-memory provider so no public internet is required.

**Tech Stack:** Python 3.12, pytest, existing dataclass models.

---

### Task 1: Add Live Price Valuation Sentence

**Files:**
- Modify: `tests/test_reports.py`
- Modify: `src/investmentagent/reports.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_reports.py`:

```python
def test_build_deep_dive_includes_live_price_when_available():
    provider = FakeResearchProvider(
        (
            make_research(
                "LIVE",
                price=34.9,
                currency="SEK",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                data_quality=DataQuality.THIN,
            ),
        )
    )

    report = build_deep_dive(provider, "LIVE")

    assert report.valuation_view[0] == "Live price is 34.9 SEK from Nasdaq Nordic."
    assert "P/E is unavailable" in report.valuation_view[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_build_deep_dive_includes_live_price_when_available -v
```

Expected: FAIL because `build_deep_dive()` does not include price in `valuation_view`.

- [ ] **Step 3: Implement minimal report helper**

In `src/investmentagent/reports.py`, build `valuation_view` as a list. Add a price sentence before P/E when both `financials.price` and `financials.currency` are available:

```python
valuation_view = []
if financials.price is not None and financials.currency:
    valuation_view.append(
        f"Live price is {financials.price:g} {financials.currency} from Nasdaq Nordic."
    )
valuation_view.extend(
    (
        _metric_sentence("P/E", financials.pe_ratio),
        _metric_sentence("Price/book", financials.price_to_book),
        _net_cash_or_debt_sentence(financials.net_cash_eur_m),
    )
)
```

Pass `valuation_view=tuple(valuation_view)` into `DeepDiveReport`.

- [ ] **Step 4: Run focused test**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Run report tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py -v
```

Expected: PASS.

### Task 2: Verify CLI Behavior

**Files:**
- No additional source changes expected.

- [ ] **Step 1: Run full suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run fixture deep dive**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent deep-dive FREEM --provider fixture
```

Expected: command exits 0 and still prints valuation sections.

- [ ] **Step 3: Run live deep dive**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent deep-dive 2CUREX --provider live
```

Expected: command exits 0 and the Valuation section includes a live price sentence plus unavailable valuation metric sentences.

- [ ] **Step 4: Commit**

Run:

```bash
git add src/investmentagent/reports.py tests/test_reports.py docs/superpowers/plans/2026-05-10-live-deep-dive-market-context-implementation.md
git commit -m "feat: add live deep dive market context"
```
