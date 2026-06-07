# Long-Term Accounting And Valuation Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split long-term performance reporting into true research candidates, speculative monitors, and audit rows while improving FinImpulse valuation parsing and coverage diagnostics.

**Architecture:** Keep the performance ledger schema stable and derive reporting groups at render time from each pick's `long_term_gate.tier`. Keep provider enrichment local to `fundamentals.py`, using existing `FinancialSnapshot` valuation fields and compact source-check counters.

**Tech Stack:** Python 3.11+, Typer CLI, pytest, JSON/Markdown report rendering.

---

## File Structure

- Modify `tests/test_cli.py`: replace deprecated `CliRunner.isolated_filesystem()` usage with a local context manager so the full suite passes with current Typer.
- Modify `tests/test_fundamentals.py`: extend FinImpulse fixtures and add valuation coverage source-check tests.
- Modify `src/investmentagent/fundamentals.py`: parse direct valuation metrics and proxy inputs from FinImpulse payloads, and expose coverage counters in `source_check()`.
- Modify `tests/test_performance.py`: cover long-term research, monitor, audit, and legacy scorecard sections.
- Modify `src/investmentagent/performance.py`: add long-term performance groups and render them as separate sections.
- Modify `tests/test_reports.py`: cover the stronger no-research-candidates report wording.
- Modify `src/investmentagent/renderers.py`: change the long-term empty-gate note to distinguish research candidates from monitor/audit rows.
- Modify `docs/performance/index.md` and `docs/performance/latest.md`: regenerate the published scorecard from the current ledger after tests pass.

## Task 1: Restore CLI Test Compatibility

**Files:**
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the compatibility helper**

Add these imports near the top of `tests/test_cli.py`:

```python
import os
import tempfile
from contextlib import contextmanager
```

Add this helper after `runner = CliRunner()`:

```python
@contextmanager
def isolated_filesystem():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield
        finally:
            os.chdir(previous)
```

- [ ] **Step 2: Replace deprecated runner calls**

Replace every occurrence of:

```python
with runner.isolated_filesystem():
```

with:

```python
with isolated_filesystem():
```

- [ ] **Step 3: Run the affected CLI tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_cli.py::test_watchlist_saves_json_report tests/test_cli.py::test_watchlist_saves_markdown_report tests/test_cli.py::test_watchlist_can_save_markdown_and_json_from_one_run tests/test_cli.py::test_performance_update_creates_ledger_and_scorecard -v
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/test_cli.py
git commit -m "test: restore cli isolated filesystem helper"
```

## Task 2: Parse FinImpulse Valuation Fields And Diagnostics

**Files:**
- Modify: `tests/test_fundamentals.py`
- Modify: `src/investmentagent/fundamentals.py`

- [ ] **Step 1: Extend the FinImpulse search fixture**

In `finimpulse_search_payload()`, add these fields to the `items[0]` dictionary:

```python
"trailing_pe": 13.4,
"price_to_book": 1.2,
"enterprise_value_to_ebit": 9.8,
"total_revenue": 2_400_000_000,
"book_value": 840_000_000,
"net_income": 210_000_000,
```

- [ ] **Step 2: Add direct and proxy valuation assertions**

In `test_finimpulse_provider_parses_search_result_with_token_safe_evidence()`, add:

```python
assert snapshot.financials.pe_ratio == 13.4
assert snapshot.financials.price_to_book == 1.2
assert snapshot.financials.ev_to_ebit == 9.8
assert snapshot.financials.revenue_eur_m == 240.0
assert snapshot.financials.book_value_eur_m == 84.0
assert snapshot.financials.net_income_eur_m == 21.0
```

- [ ] **Step 3: Add a source-check diagnostics test**

Add this test below the existing FinImpulse source-check tests:

```python
def test_finimpulse_source_check_reports_valuation_coverage():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, payload, headers: finimpulse_search_payload(),
    )
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Finimpulse lookups parsed" in check.detail
    assert "valuation support 1/1" in check.detail
    assert "direct valuation 1/1" in check.detail
    assert "proxy inputs 1/1" in check.detail
    assert "missing valuation support 0/1" in check.detail
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_finimpulse_provider_parses_search_result_with_token_safe_evidence tests/test_fundamentals.py::test_finimpulse_source_check_reports_valuation_coverage -v
```

Expected: the new assertions fail because FinImpulse does not parse these valuation fields or expose coverage detail yet.

- [ ] **Step 5: Add valuation field key groups and coverage helpers**

In `src/investmentagent/fundamentals.py`, add these constants near `_EUR_RATES`:

```python
FINIMPULSE_PE_KEYS = ("pe_ratio", "trailing_pe", "trailingPE", "forward_pe")
FINIMPULSE_PRICE_TO_BOOK_KEYS = (
    "price_to_book",
    "priceToBook",
    "pb_ratio",
    "price_book_ratio",
)
FINIMPULSE_EV_TO_EBIT_KEYS = (
    "enterprise_value_to_ebit",
    "ev_to_ebit",
    "evEbit",
    "enterprise_value_ebit",
)
FINIMPULSE_REVENUE_KEYS = (
    "total_revenue",
    "revenue",
    "annual_revenue",
    "revenue_ttm",
)
FINIMPULSE_BOOK_VALUE_KEYS = (
    "book_value",
    "shareholders_equity",
    "stockholders_equity",
    "total_equity",
)
FINIMPULSE_NET_INCOME_KEYS = (
    "net_income",
    "net_income_common_stockholders",
    "net_income_ttm",
)
DIRECT_VALUATION_FIELDS = ("pe_ratio", "price_to_book", "ev_to_ebit")
PROXY_VALUATION_FIELDS = ("revenue_eur_m", "book_value_eur_m", "net_income_eur_m")
```

Add these helpers below `_has_meaningful_fields()`:

```python
def _has_any_financial_field(
    financials: FinancialSnapshot, field_names: tuple[str, ...]
) -> bool:
    return any(getattr(financials, field_name) is not None for field_name in field_names)


def _has_valuation_support(financials: FinancialSnapshot) -> bool:
    return _has_any_financial_field(
        financials, DIRECT_VALUATION_FIELDS + PROXY_VALUATION_FIELDS
    )
```

- [ ] **Step 6: Track FinImpulse valuation coverage**

In `FinimpulseFundamentalsProvider.__init__()`, add:

```python
self.valuation_support_lookups = 0
self.direct_valuation_lookups = 0
self.proxy_input_lookups = 0
```

In `get_fundamentals()`, after `snapshot = self._with_profile(snapshot, headers)`, add:

```python
self._record_valuation_coverage(snapshot)
```

Add this method to `FinimpulseFundamentalsProvider`:

```python
def _record_valuation_coverage(self, snapshot: FundamentalsSnapshot) -> None:
    financials = snapshot.financials
    if _has_valuation_support(financials):
        self.valuation_support_lookups += 1
    if _has_any_financial_field(financials, DIRECT_VALUATION_FIELDS):
        self.direct_valuation_lookups += 1
    if _has_any_financial_field(financials, PROXY_VALUATION_FIELDS):
        self.proxy_input_lookups += 1
```

Update the successful and partial `source_check()` detail to include:

```python
coverage = (
    f"{ratio}; valuation support {self.valuation_support_lookups}/"
    f"{self.successful_lookups}; direct valuation {self.direct_valuation_lookups}/"
    f"{self.successful_lookups}; proxy inputs {self.proxy_input_lookups}/"
    f"{self.successful_lookups}; missing valuation support "
    f"{self.successful_lookups - self.valuation_support_lookups}/"
    f"{self.successful_lookups}"
)
```

Return `coverage` as the detail when at least one lookup succeeded.

- [ ] **Step 7: Parse direct and proxy valuation fields**

In `_parse_finimpulse_search_payload()`, update the `FinancialSnapshot(...)` call with:

```python
pe_ratio=_first_number(item, FINIMPULSE_PE_KEYS),
price_to_book=_first_number(item, FINIMPULSE_PRICE_TO_BOOK_KEYS),
ev_to_ebit=_first_number(item, FINIMPULSE_EV_TO_EBIT_KEYS),
revenue_eur_m=_eur_m(_first_number(item, FINIMPULSE_REVENUE_KEYS), fx_rate),
book_value_eur_m=_eur_m(_first_number(item, FINIMPULSE_BOOK_VALUE_KEYS), fx_rate),
net_income_eur_m=_eur_m(_first_number(item, FINIMPULSE_NET_INCOME_KEYS), fx_rate),
```

In `_has_meaningful_fields()`, add:

```python
financials.ev_to_ebit,
financials.revenue_eur_m,
financials.book_value_eur_m,
financials.net_income_eur_m,
```

- [ ] **Step 8: Run fundamentals tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py -v
```

Expected: all fundamentals tests pass.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/investmentagent/fundamentals.py tests/test_fundamentals.py
git commit -m "feat: add finimpulse valuation diagnostics"
```

## Task 3: Split Long-Term Performance Accounting

**Files:**
- Modify: `tests/test_performance.py`
- Modify: `src/investmentagent/performance.py`

- [ ] **Step 1: Add performance segmentation tests**

Add these helper functions near `report_payload()`:

```python
def long_term_payload_with_tier(ticker: str, tier: str, price: float = 10.0):
    payload = report_payload(strategy="long-term")
    payload["items"][0]["company"]["ticker"] = ticker
    payload["items"][0]["company"]["name"] = f"{ticker} AB"
    payload["items"][0]["financials"]["price"] = price
    payload["items"][0]["long_term_gate"] = {
        "tier": tier,
        "reasons": [],
        "blockers": [],
        "durable_anchor_count": 0,
        "severe_proof_gap_count": 0,
        "valuation": {
            "has_support": tier != "Insufficient evidence",
            "is_attractive": False,
            "primary_kind": None,
            "primary_value": None,
            "summary": "",
        },
    }
    return payload
```

Add this test near the scorecard rendering tests:

```python
def test_render_scorecard_splits_long_term_gate_tiers():
    ledger = empty_ledger()
    cases = [
        ("QUAL", "High-conviction candidate", 12.0),
        ("WATCH", "Fundamental watchlist", 11.0),
        ("SPEC", "Speculative monitor", 8.0),
        ("AUDIT", "Insufficient evidence", 7.0),
    ]
    for ticker, tier, exit_price in cases:
        ledger = add_report_picks(
            ledger,
            long_term_payload_with_tier(ticker, tier),
            report_date=date(2026, 5, 11),
            report_url="reports/long-term/2026-05-11.html",
        )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={
            (ticker, "SE"): {"price": exit_price, "currency": "SEK"}
            for ticker, _, exit_price in cases
        },
    )

    summary = summarize_ledger(ledger)
    output = render_scorecard_markdown(ledger, generated_at="2026-05-12 09:03 EEST")

    assert summary["long_term_segments"]["research"]["1d"]["completed"] == 2
    assert summary["long_term_segments"]["research"]["1d"]["average_return_pct"] == 15.0
    assert summary["long_term_segments"]["speculative"]["1d"]["average_return_pct"] == -20.0
    assert summary["long_term_segments"]["insufficient"]["1d"]["average_return_pct"] == -30.0
    assert "## Long-Term Research Candidates" in output
    assert "## Speculative Monitors" in output
    assert "## Insufficient Evidence Audit" in output
    research_section = output.split("## Long-Term Research Candidates")[1].split("## Speculative Monitors")[0]
    assert "QUAL AB" in research_section
    assert "WATCH AB" in research_section
    assert "SPEC AB" not in research_section
    monitor_section = output.split("## Speculative Monitors")[1].split("## Insufficient Evidence Audit")[0]
    assert "SPEC AB" in monitor_section
    assert "QUAL AB" not in monitor_section
```

Add this legacy coverage test:

```python
def test_render_scorecard_keeps_legacy_long_term_rows_separate():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(strategy="long-term"),
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    output = render_scorecard_markdown(ledger, generated_at="2026-05-12 09:03 EEST")

    assert "## Legacy Long-Term Rows" in output
    assert "## Long-Term Research Candidates" in output
    research_section = output.split("## Long-Term Research Candidates")[1].split("## Speculative Monitors")[0]
    assert "Stayble Therapeutics" not in research_section
```

- [ ] **Step 2: Run the new performance tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_performance.py::test_render_scorecard_splits_long_term_gate_tiers tests/test_performance.py::test_render_scorecard_keeps_legacy_long_term_rows_separate -v
```

Expected: tests fail because `long_term_segments` and the new rendered sections do not exist yet.

- [ ] **Step 3: Add long-term segment constants**

In `src/investmentagent/performance.py`, add below `STRATEGY_LABELS`:

```python
LONG_TERM_RESEARCH_TIERS = {
    "High-conviction candidate",
    "Fundamental watchlist",
}
LONG_TERM_SEGMENT_ORDER = ("research", "speculative", "insufficient", "legacy")
LONG_TERM_SEGMENTS = {
    "research": {
        "title": "Long-Term Research Candidates",
        "label": "Long-Term Research",
        "description": (
            "Only high-conviction and fundamental watchlist names count here."
        ),
    },
    "speculative": {
        "title": "Speculative Monitors",
        "label": "Speculative Monitor",
        "description": (
            "Tracked separately because the gate did not classify these as research candidates."
        ),
    },
    "insufficient": {
        "title": "Insufficient Evidence Audit",
        "label": "Insufficient Evidence",
        "description": (
            "Tracked as an audit trail for rows with too many proof gaps."
        ),
    },
    "legacy": {
        "title": "Legacy Long-Term Rows",
        "label": "Legacy Long-Term",
        "description": (
            "Older long-term rows without gate metadata are kept out of the candidate headline."
        ),
    },
}
```

- [ ] **Step 4: Add segment classification and predicate helpers**

Add these helpers near `_long_term_quality_signals()`:

```python
def _long_term_segment_key(pick: dict[str, Any]) -> str | None:
    if pick.get("strategy") != "long-term":
        return None
    tier = (pick.get("long_term_gate") or {}).get("tier")
    if tier in LONG_TERM_RESEARCH_TIERS:
        return "research"
    if tier == "Speculative monitor":
        return "speculative"
    if tier == "Insufficient evidence":
        return "insufficient"
    return "legacy"


def _pick_matches_long_term_segment(pick: dict[str, Any], segment: str) -> bool:
    return _long_term_segment_key(pick) == segment
```

Generalize `_strategy_horizon_summary()` into a helper that accepts a predicate:

```python
def _horizon_summary_for_picks(
    ledger: dict[str, Any], horizon: str, pick_filter
) -> dict[str, Any]:
    returns = [
        pick["outcomes"][horizon]["return_pct"]
        for pick in ledger["picks"]
        if pick_filter(pick)
        and pick["outcomes"][horizon]["status"] == "priced"
        and pick["outcomes"][horizon]["return_pct"] is not None
    ]
```

Then make `_strategy_horizon_summary()` call:

```python
return _horizon_summary_for_picks(
    ledger, horizon, lambda pick: pick["strategy"] == strategy
)
```

Move the existing summary body into `_horizon_summary_for_picks()` and reuse the same `pick_filter` for benchmark and excess return lists.

- [ ] **Step 5: Add segment summaries to `summarize_ledger()`**

Extend the returned dictionary with:

```python
"long_term_segments": {
    segment: {
        horizon: _horizon_summary_for_picks(
            ledger,
            horizon,
            lambda pick, segment=segment: _pick_matches_long_term_segment(
                pick, segment
            ),
        )
        for horizon in HORIZONS
    }
    for segment in LONG_TERM_SEGMENT_ORDER
},
"best_picks_by_long_term_segment": {
    segment: _ranked_completed_picks(
        ledger, reverse=True, long_term_segment=segment
    )
    for segment in LONG_TERM_SEGMENT_ORDER
},
"worst_picks_by_long_term_segment": {
    segment: _ranked_completed_picks(
        ledger, reverse=False, long_term_segment=segment
    )
    for segment in LONG_TERM_SEGMENT_ORDER
},
"signals_by_long_term_segment": {
    segment: _signal_summaries(ledger, long_term_segment=segment)
    for segment in LONG_TERM_SEGMENT_ORDER
},
```

- [ ] **Step 6: Let ranking and signal helpers filter by segment**

Change `_ranked_completed_picks(...)` signature to:

```python
def _ranked_completed_picks(
    ledger: dict[str, Any],
    *,
    reverse: bool,
    strategy: str | None = None,
    long_term_segment: str | None = None,
) -> list[dict[str, Any]]:
```

Inside its loop, add:

```python
if long_term_segment is not None and not _pick_matches_long_term_segment(
    pick, long_term_segment
):
    continue
```

Change `_signal_summaries(...)` signature to:

```python
def _signal_summaries(
    ledger: dict[str, Any],
    *,
    strategy: str | None = None,
    long_term_segment: str | None = None,
) -> list[dict[str, Any]]:
```

Inside its loop, add the same segment guard.

- [ ] **Step 7: Render long-term segments instead of the aggregate long-term section**

In `render_scorecard_markdown()`, replace:

```python
for strategy in STRATEGIES:
    lines.extend(_strategy_performance_section(summary, ledger, strategy))
```

with:

```python
lines.extend(_strategy_performance_section(summary, ledger, "trading"))
for segment in LONG_TERM_SEGMENT_ORDER:
    lines.extend(_long_term_segment_performance_section(summary, ledger, segment))
```

Add:

```python
def _long_term_segment_performance_section(
    summary: dict[str, Any], ledger: dict[str, Any], segment: str
) -> list[str]:
    config = LONG_TERM_SEGMENTS[segment]
    label = config["label"]
    best_picks = summary["best_picks_by_long_term_segment"][segment]
    worst_picks = _exclude_pick_rows(
        summary["worst_picks_by_long_term_segment"][segment], best_picks
    )
    return [
        f"## {config['title']}",
        "",
        f"_{config['description']}_",
        "",
        "### Horizon Scorecard",
        "",
        *_long_term_segment_table(summary, segment),
        "",
        "### Risk And Benchmark",
        "",
        *_long_term_segment_risk_benchmark_table(summary, segment),
        "",
        f"### Best {label} Picks",
        "",
        *_pick_lines(best_picks, empty_label=f"No completed {label.lower()} picks yet."),
        "",
        f"### Worst {label} Picks",
        "",
        *_pick_lines(worst_picks, empty_label=f"No completed {label.lower()} picks yet."),
        "",
        f"### {label} Signal Review",
        "",
        *_signal_table(summary["signals_by_long_term_segment"][segment]),
        "",
        f"### {label} Learning Suggestions",
        "",
        *[
            f"- {suggestion}"
            for suggestion in learning_suggestions(
                ledger, strategy="long-term", long_term_segment=segment
            )
        ],
        "",
    ]
```

Add table wrappers that mirror the existing strategy tables but read `summary["long_term_segments"][segment]`.

- [ ] **Step 8: Extend `learning_suggestions()`**

Change the signature to:

```python
def learning_suggestions(
    ledger: dict[str, Any],
    *,
    strategy: str | None = None,
    long_term_segment: str | None = None,
) -> list[str]:
```

Pass `long_term_segment=long_term_segment` into `_signal_summaries(...)`.

- [ ] **Step 9: Update existing scorecard tests for new headings**

In `tests/test_performance.py`, update assertions that split or search for `## Long-Term Investment Ideas` to use `## Long-Term Research Candidates`, and update best-pick headings to `### Best Long-Term Research Picks` where the section is research candidates.

- [ ] **Step 10: Run performance tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_performance.py -v
```

Expected: all performance tests pass.

- [ ] **Step 11: Commit**

Run:

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: split long-term performance sections"
```

## Task 4: Clarify Long-Term Report Wording

**Files:**
- Modify: `tests/test_reports.py`
- Modify: `src/investmentagent/renderers.py`

- [ ] **Step 1: Add report wording coverage**

Find the long-term report tests in `tests/test_reports.py` and add:

```python
def test_long_term_report_marks_monitor_rows_when_no_research_candidates():
    item = watchlist_item(
        financials=FinancialSnapshot(
            price=10.0,
            currency="SEK",
            data_quality=DataQuality.THIN,
        ),
        score=ScoreBreakdown(
            value=0,
            discovery=0,
            catalyst=0,
            risk_penalty=0,
            data_quality_penalty=0,
            total=0,
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        {"strategy": "long-term"},
        [],
    )

    assert "No long-term research candidates passed the gate today." in output
    assert "not long-term candidate recommendations" in output
    assert "## Insufficient Evidence" in output
```

Use the existing local test helpers for constructing `WatchlistItem` if their names differ from `watchlist_item`.

- [ ] **Step 2: Run the new report test to verify it fails**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_reports.py::test_long_term_report_marks_monitor_rows_when_no_research_candidates -v
```

Expected: the new wording assertion fails because the renderer still only says no high-conviction ideas passed.

- [ ] **Step 3: Update long-term markdown gate note**

In `_long_term_markdown_sections()`, replace the current high-conviction-only check with:

```python
research_tiers = {
    LongTermGateTier.HIGH_CONVICTION,
    LongTermGateTier.FUNDAMENTAL_WATCHLIST,
}
if not any(assess_long_term_gate(item.research).tier in research_tiers for item in items):
    lines.extend(
        [
            (
                "_No long-term research candidates passed the gate today. Rows below "
                "are speculative monitors or evidence-audit rows, not long-term "
                "candidate recommendations._"
            ),
            "",
        ]
    )
```

- [ ] **Step 4: Run report tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_reports.py -v
```

Expected: all report tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/investmentagent/renderers.py tests/test_reports.py
git commit -m "feat: clarify long-term gate report wording"
```

## Task 5: Regenerate Scorecard And Verify Everything

**Files:**
- Modify: `docs/performance/index.md`
- Modify: `docs/performance/latest.md`

- [ ] **Step 1: Run the full test suite**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Regenerate the public performance scorecard**

Run:

```bash
PYTHONPATH=src /private/tmp/investmentagent-accounting-venv/bin/python -m investmentagent.cli performance update --ledger docs/data/performance/ledger.json --output docs/performance/index.md --latest docs/performance/latest.md --generated-at "2026-06-07 00:00 Europe/Stockholm"
```

Expected: command exits `0`; `docs/performance/index.md` and `docs/performance/latest.md` contain `## Long-Term Research Candidates`, `## Speculative Monitors`, and `## Insufficient Evidence Audit`.

- [ ] **Step 3: Inspect generated scorecard headings**

Run:

```bash
rg -n "Long-Term Research Candidates|Speculative Monitors|Insufficient Evidence Audit|Legacy Long-Term Rows" docs/performance/index.md docs/performance/latest.md
```

Expected: the new long-term section headings are present.

- [ ] **Step 4: Run git status and review diff**

Run:

```bash
git status --short
git diff -- src/investmentagent/fundamentals.py src/investmentagent/performance.py src/investmentagent/renderers.py tests/test_cli.py tests/test_fundamentals.py tests/test_performance.py tests/test_reports.py docs/performance/index.md docs/performance/latest.md
```

Expected: diff contains only the compatibility fix, valuation diagnostics, long-term section split, report wording, and regenerated scorecard.

- [ ] **Step 5: Commit generated scorecard**

Run:

```bash
git add docs/performance/index.md docs/performance/latest.md
git commit -m "docs: refresh segmented performance scorecard"
```

- [ ] **Step 6: Merge back to main**

Run from `/Users/vernerisirva1/Documents/Investmentagent`:

```bash
git pull --ff-only origin main
git merge --ff-only codex/long-term-accounting-diagnostics
```

Expected: `main` fast-forwards to the implementation commits.

- [ ] **Step 7: Push main**

Run:

```bash
git push origin main
```

Expected: push succeeds.
