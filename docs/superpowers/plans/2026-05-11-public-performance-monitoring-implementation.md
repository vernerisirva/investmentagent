# Public Performance Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public performance scorecard and versioned ledger that track InvestmentAgent's daily trading and long-term ideas over 1d, 5d, 20d, and 60d horizons.

**Architecture:** Add a focused `investmentagent.performance` module for ledger records, outcome updates, aggregate statistics, and Markdown scorecard rendering. Extend saved watchlist JSON so long-term conviction data is machine-readable, add a `performance update` CLI command, then call it from the daily GitHub Actions workflow after report generation.

**Tech Stack:** Python standard library, Typer CLI, existing dataclasses/renderers/provider boundaries, GitHub Actions, GitHub Pages Markdown.

---

## File Structure

- Create `src/investmentagent/performance.py`: pure performance ledger logic, outcome updates, summaries, learning suggestions, scorecard rendering.
- Create `tests/test_performance.py`: deterministic unit tests for ledger and scorecard behavior.
- Modify `src/investmentagent/renderers.py`: include long-term conviction payload in saved JSON reports when metadata strategy is `long-term`.
- Modify `tests/test_reports.py`: cover long-term conviction JSON payload.
- Modify `src/investmentagent/cli.py`: support repeated `--save` paths for one watchlist run and add `investmentagent performance update`.
- Modify `tests/test_cli.py`: cover repeated saves and performance CLI.
- Modify `.github/workflows/daily-public-watchlist.yml`: generate Markdown plus JSON reports, update performance ledger/page, commit `docs/data/performance` and `docs/performance`.
- Modify `README.md`: document the public performance page.

## Task 1: Expose Long-Term Conviction In JSON Reports

**Files:**
- Modify: `src/investmentagent/renderers.py`
- Modify: `tests/test_reports.py`

- [ ] **Step 1: Write the failing JSON payload test**

Add this test near the existing watchlist report JSON tests in `tests/test_reports.py`:

```python
def test_render_watchlist_report_json_includes_long_term_conviction_payload():
    company = Company(
        name="Quality Compounder AB",
        ticker="QUAL",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        sector="Software",
        business_description="Quality Compounder sells workflow software.",
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(
                pe_ratio=11.0,
                price_to_book=1.1,
                net_cash_eur_m=25.0,
                debt_to_equity=0.2,
                revenue_growth_pct=12.0,
                operating_margin_pct=18.0,
                data_quality=DataQuality.PARTIAL,
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=10.0,
            discovery=8.0,
            catalyst=21.0,
            risk_penalty=0.0,
            data_quality_penalty=4.0,
            total=35.0,
        ),
    )

    payload = json.loads(
        render_watchlist_report_json(
            [item],
            metadata={"strategy": "long-term"},
            source_checks=[],
        )
    )

    conviction = payload["items"][0]["long_term_conviction"]
    assert conviction["bucket"] == "High conviction candidate"
    assert "profitable software profile" in conviction["thesis"]
    assert conviction["components"]["Business quality"]["score"] == 5
    assert conviction["components"]["Valuation"]["view"].startswith("Attractive valuation")
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_render_watchlist_report_json_includes_long_term_conviction_payload -v
```

Expected: FAIL with `KeyError: 'long_term_conviction'`.

- [ ] **Step 3: Add strategy-aware JSON payload support**

In `src/investmentagent/renderers.py`, change the report JSON call to pass strategy:

```python
def render_watchlist_report_json(
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks
) -> str:
    strategy = str(metadata.get("strategy") or "").strip().lower()
    payload = {
        "disclaimer": DISCLAIMER,
        "metadata": metadata,
        "source_checks": [_source_check_payload(check) for check in source_checks],
        "items": _watchlist_items_payload(items, strategy=strategy),
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)
```

Change `_watchlist_items_payload` to accept strategy and add the conviction payload:

```python
def _watchlist_items_payload(
    items: list[WatchlistItem], strategy: str = ""
) -> list[dict[str, Any]]:
    payload_items = []
    for item in items:
        payload = {
            "rank": item.rank,
            "company": _company_payload(item.research.company),
            "company_presentation": _company_presentation(item),
            "financials": _financials_payload(item.research.financials),
            "score": _score_payload(item.score),
            "risks": list(item.research.risks),
            "catalysts": list(item.research.catalysts),
            "evidence": [_evidence_payload(evidence) for evidence in item.research.evidence],
            "data_quality": _stringify(item.research.data_quality),
        }
        if strategy == "long-term":
            payload["long_term_conviction"] = _long_term_conviction_payload(item)
        payload_items.append(payload)
    return payload_items
```

Add this helper near `_long_term_conviction`:

```python
def _long_term_conviction_payload(item: WatchlistItem) -> dict[str, Any]:
    conviction = _long_term_conviction(item)
    return {
        "bucket": conviction.bucket,
        "thesis": conviction.thesis,
        "components": {
            component.name: {"score": component.score, "view": component.view}
            for component in conviction.components
        },
    }
```

Keep `render_watchlist_json()` calling `_watchlist_items_payload(items)` without a strategy so normal JSON output stays unchanged.

- [ ] **Step 4: Run the focused test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_render_watchlist_report_json_includes_long_term_conviction_payload -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/renderers.py tests/test_reports.py
git commit -m "feat: expose long-term conviction in report json"
```

## Task 2: Allow One Watchlist Run To Save Multiple Formats

**Files:**
- Modify: `src/investmentagent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI test**

Add this test near `test_watchlist_saves_markdown_report` in `tests/test_cli.py`:

```python
def test_watchlist_can_save_markdown_and_json_from_one_run():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.md",
                "--save",
                "reports/watchlist.json",
            ],
        )

        markdown = Path("reports/watchlist.md").read_text()
        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert "# InvestmentAgent Watchlist" in markdown
    assert payload["items"][0]["rank"] == 1
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_can_save_markdown_and_json_from_one_run -v
```

Expected: FAIL because Typer currently treats `--save` as a single value.

- [ ] **Step 3: Update the CLI save option**

In `src/investmentagent/cli.py`, change the save option type:

```python
save_paths: list[str] | None = typer.Option(
    None, "--save", help="Save report to .json, .md, or .markdown. Can be repeated."
),
```

Change the save block in `watchlist()`:

```python
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": normalized_provider_name,
        "fundamentals": effective_fundamentals,
        "countries": list(countries),
        "limit": limit,
        "include_first_north": include_first_north,
        "min_market_cap": min_market_cap,
        "max_market_cap": max_market_cap,
        "sector": sector,
        "strategy": normalized_strategy,
        "min_country_counts": min_country_counts,
    }
    for save_path in save_paths or ():
        _save_watchlist_report(save_path, items, metadata, source_checks)
```

Remove the old `if save_path is not None:` block.

- [ ] **Step 4: Run focused CLI save tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_saves_json_report tests/test_cli.py::test_watchlist_saves_markdown_report tests/test_cli.py::test_watchlist_can_save_markdown_and_json_from_one_run -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/cli.py tests/test_cli.py
git commit -m "feat: save watchlist reports in multiple formats"
```

## Task 3: Add Performance Ledger Core

**Files:**
- Create: `src/investmentagent/performance.py`
- Create: `tests/test_performance.py`

- [ ] **Step 1: Write ledger creation and dedupe tests**

Create `tests/test_performance.py`:

```python
from datetime import date

from investmentagent.performance import (
    HORIZONS,
    add_report_picks,
    empty_ledger,
)


def report_payload(strategy="trading"):
    return {
        "metadata": {
            "generated_at": "2026-05-11T07:36:10+00:00",
            "strategy": strategy,
        },
        "items": [
            {
                "rank": 1,
                "company": {
                    "ticker": "STABL",
                    "name": "Stayble Therapeutics",
                    "country": "SE",
                    "exchange": "Nasdaq First North Growth Market Sweden",
                    "segment": "first_north",
                    "sector": "Health Care",
                },
                "financials": {"price": 0.85, "currency": "SEK"},
                "score": {"total": 37, "reasons": ["High live turnover"], "warnings": []},
                "risks": ["Speculative low-price share"],
                "data_quality": "partial",
            }
        ],
    }


def test_add_report_picks_creates_ledger_record_with_outcome_horizons():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    pick = ledger["picks"][0]
    assert pick["pick_id"] == "2026-05-11|trading|STABL|1"
    assert pick["entry_price"] == 0.85
    assert pick["entry_currency"] == "SEK"
    assert pick["outcomes"] == {
        horizon: {
            "as_of_date": None,
            "price": None,
            "currency": None,
            "return_pct": None,
            "status": "not_due",
        }
        for horizon in HORIZONS
    }


def test_add_report_picks_is_idempotent_for_same_report():
    ledger = empty_ledger()
    ledger = add_report_picks(
        ledger,
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = add_report_picks(
        ledger,
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    assert len(ledger["picks"]) == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py::test_add_report_picks_creates_ledger_record_with_outcome_horizons tests/test_performance.py::test_add_report_picks_is_idempotent_for_same_report -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'investmentagent.performance'`.

- [ ] **Step 3: Create the minimal ledger implementation**

Create `src/investmentagent/performance.py`:

```python
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LEDGER_SCHEMA_VERSION = 1
HORIZONS = ("1d", "5d", "20d", "60d")
HORIZON_DAYS = {"1d": 1, "5d": 5, "20d": 20, "60d": 60}
DISCLAIMER = "Research triage only. Not financial advice."


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA_VERSION, "picks": []}


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_ledger()
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported performance ledger schema: {ledger.get('schema_version')}"
        )
    if not isinstance(ledger.get("picks"), list):
        raise ValueError("performance ledger is missing picks list")
    return ledger


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_report_picks(
    ledger: dict[str, Any],
    report_payload: dict[str, Any],
    *,
    report_date: date,
    report_url: str,
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    existing_ids = {pick["pick_id"] for pick in updated["picks"]}
    strategy = str(report_payload.get("metadata", {}).get("strategy") or "").strip()
    generated_at = report_payload.get("metadata", {}).get("generated_at")
    for item in report_payload.get("items", []):
        pick = _pick_from_report_item(
            item,
            strategy=strategy,
            report_date=report_date,
            report_url=report_url,
            generated_at=generated_at,
        )
        if pick["pick_id"] not in existing_ids:
            updated["picks"].append(pick)
            existing_ids.add(pick["pick_id"])
    updated["picks"].sort(key=lambda pick: pick["pick_id"])
    return updated


def _pick_from_report_item(
    item: dict[str, Any],
    *,
    strategy: str,
    report_date: date,
    report_url: str,
    generated_at: str | None,
) -> dict[str, Any]:
    company = item.get("company", {})
    financials = item.get("financials", {})
    score = item.get("score", {})
    rank = int(item["rank"])
    ticker = str(company["ticker"]).upper()
    pick = {
        "pick_id": f"{report_date.isoformat()}|{strategy}|{ticker}|{rank}",
        "report_date": report_date.isoformat(),
        "strategy": strategy,
        "rank": rank,
        "ticker": ticker,
        "name": company.get("name"),
        "country": company.get("country"),
        "exchange": company.get("exchange"),
        "segment": company.get("segment"),
        "sector": company.get("sector"),
        "report_url": report_url,
        "entry_price": financials.get("price"),
        "entry_currency": financials.get("currency"),
        "entry_timestamp": generated_at,
        "score_total": score.get("total"),
        "reasons": list(score.get("reasons") or ()),
        "risks": list(item.get("risks") or ()),
        "data_quality": item.get("data_quality"),
        "outcomes": _empty_outcomes(),
    }
    conviction = item.get("long_term_conviction")
    if conviction:
        pick["long_term_conviction"] = conviction
    return pick


def _empty_outcomes() -> dict[str, dict[str, Any]]:
    return {
        horizon: {
            "as_of_date": None,
            "price": None,
            "currency": None,
            "return_pct": None,
            "status": "not_due",
        }
        for horizon in HORIZONS
    }


def parse_report_date(value: str) -> date:
    return date.fromisoformat(value)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py::test_add_report_picks_creates_ledger_record_with_outcome_horizons tests/test_performance.py::test_add_report_picks_is_idempotent_for_same_report -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: add performance ledger core"
```

## Task 4: Update Outcomes And Calculate Summaries

**Files:**
- Modify: `src/investmentagent/performance.py`
- Modify: `tests/test_performance.py`

- [ ] **Step 1: Add outcome and aggregate tests**

Append these tests to `tests/test_performance.py`:

```python
from investmentagent.performance import summarize_ledger, update_due_outcomes


def test_update_due_outcomes_prices_due_horizons_and_leaves_future_horizons_open():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 16),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    outcomes = updated["picks"][0]["outcomes"]
    assert outcomes["1d"]["status"] == "priced"
    assert outcomes["1d"]["return_pct"] == 20.0
    assert outcomes["5d"]["status"] == "priced"
    assert outcomes["20d"]["status"] == "not_due"


def test_update_due_outcomes_marks_missing_price_without_overwriting_later():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={},
    )

    assert updated["picks"][0]["outcomes"]["1d"]["status"] == "missing_price"
    assert updated["picks"][0]["outcomes"]["1d"]["return_pct"] is None


def test_summarize_ledger_separates_trading_and_long_term_results():
    trading = report_payload(strategy="trading")
    long_term = report_payload(strategy="long-term")
    long_term["items"][0]["company"]["ticker"] = "ADMCM"
    long_term["items"][0]["company"]["country"] = "FI"
    long_term["items"][0]["financials"]["price"] = 10.0
    long_term["items"][0]["financials"]["currency"] = "EUR"
    ledger = empty_ledger()
    ledger = add_report_picks(
        ledger,
        trading,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = add_report_picks(
        ledger,
        long_term,
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 16),
        price_lookup={
            ("STABL", "SE"): {"price": 1.02, "currency": "SEK"},
            ("ADMCM", "FI"): {"price": 11.0, "currency": "EUR"},
        },
    )

    summary = summarize_ledger(ledger)

    assert summary["strategies"]["trading"]["5d"]["completed"] == 1
    assert summary["strategies"]["trading"]["5d"]["average_return_pct"] == 20.0
    assert summary["strategies"]["long-term"]["5d"]["completed"] == 1
    assert summary["strategies"]["long-term"]["5d"]["average_return_pct"] == 10.0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py -v
```

Expected: FAIL because `update_due_outcomes` and `summarize_ledger` do not exist yet.

- [ ] **Step 3: Implement outcome updates and summaries**

Add these functions to `src/investmentagent/performance.py`:

```python
def update_due_outcomes(
    ledger: dict[str, Any],
    *,
    as_of_date: date,
    price_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    for pick in updated["picks"]:
        report_date = date.fromisoformat(pick["report_date"])
        entry_price = pick.get("entry_price")
        entry_currency = pick.get("entry_currency")
        for horizon, days in HORIZON_DAYS.items():
            outcome = pick["outcomes"][horizon]
            if outcome["status"] == "priced":
                continue
            if as_of_date < report_date + timedelta(days=days):
                continue
            quote = price_lookup.get((pick["ticker"], pick["country"]))
            if not quote or quote.get("price") is None:
                outcome.update(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "price": None,
                        "currency": None,
                        "return_pct": None,
                        "status": "missing_price",
                    }
                )
                continue
            quote_currency = quote.get("currency")
            if entry_price is None or entry_currency is None or quote_currency != entry_currency:
                outcome.update(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "price": quote.get("price"),
                        "currency": quote_currency,
                        "return_pct": None,
                        "status": "missing_price",
                    }
                )
                continue
            return_pct = ((quote["price"] - entry_price) / entry_price) * 100
            outcome.update(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "price": quote["price"],
                    "currency": quote_currency,
                    "return_pct": round(return_pct, 2),
                    "status": "priced",
                }
            )
    return updated


def summarize_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategies": {
            strategy: {
                horizon: _strategy_horizon_summary(ledger, strategy, horizon)
                for horizon in HORIZONS
            }
            for strategy in ("trading", "long-term")
        },
        "best_picks": _ranked_completed_picks(ledger, reverse=True),
        "worst_picks": _ranked_completed_picks(ledger, reverse=False),
        "signals": _signal_summaries(ledger),
    }


def _strategy_horizon_summary(
    ledger: dict[str, Any], strategy: str, horizon: str
) -> dict[str, Any]:
    returns = [
        pick["outcomes"][horizon]["return_pct"]
        for pick in ledger["picks"]
        if pick["strategy"] == strategy
        and pick["outcomes"][horizon]["status"] == "priced"
        and pick["outcomes"][horizon]["return_pct"] is not None
    ]
    if not returns:
        return {
            "completed": 0,
            "hit_rate_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
        }
    sorted_returns = sorted(returns)
    midpoint = len(sorted_returns) // 2
    if len(sorted_returns) % 2:
        median = sorted_returns[midpoint]
    else:
        median = (sorted_returns[midpoint - 1] + sorted_returns[midpoint]) / 2
    hits = sum(value > 0 for value in returns)
    return {
        "completed": len(returns),
        "hit_rate_pct": round((hits / len(returns)) * 100, 1),
        "average_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(median, 2),
    }


def _ranked_completed_picks(ledger: dict[str, Any], *, reverse: bool) -> list[dict[str, Any]]:
    completed = []
    for pick in ledger["picks"]:
        for horizon, outcome in pick["outcomes"].items():
            if outcome["status"] == "priced" and outcome["return_pct"] is not None:
                completed.append(
                    {
                        "name": pick["name"],
                        "ticker": pick["ticker"],
                        "strategy": pick["strategy"],
                        "horizon": horizon,
                        "return_pct": outcome["return_pct"],
                        "report_url": pick["report_url"],
                    }
                )
    return sorted(completed, key=lambda item: item["return_pct"], reverse=reverse)[:5]


def _signal_summaries(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for pick in ledger["picks"]:
        signals = [
            f"country:{pick.get('country')}",
            f"segment:{pick.get('segment')}",
            f"strategy:{pick.get('strategy')}",
        ]
        signals.extend(f"reason:{reason}" for reason in pick.get("reasons", []))
        conviction = pick.get("long_term_conviction")
        if conviction:
            signals.append(f"bucket:{conviction.get('bucket')}")
        for outcome in pick["outcomes"].values():
            if outcome["status"] != "priced" or outcome["return_pct"] is None:
                continue
            for signal in signals:
                buckets.setdefault(signal, []).append(outcome["return_pct"])
    summaries = []
    for signal, returns in buckets.items():
        summaries.append(
            {
                "signal": signal,
                "observations": len(returns),
                "average_return_pct": round(sum(returns) / len(returns), 2),
                "hit_rate_pct": round((sum(value > 0 for value in returns) / len(returns)) * 100, 1),
            }
        )
    return sorted(summaries, key=lambda item: (-item["observations"], item["signal"]))
```

- [ ] **Step 4: Run performance tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: update performance outcomes"
```

## Task 5: Render Public Performance Scorecard And Learning Suggestions

**Files:**
- Modify: `src/investmentagent/performance.py`
- Modify: `tests/test_performance.py`

- [ ] **Step 1: Add scorecard tests**

Append these tests to `tests/test_performance.py`:

```python
from investmentagent.performance import learning_suggestions, render_scorecard_markdown


def test_render_scorecard_markdown_includes_strategy_sections_and_disclaimer():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 16),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    output = render_scorecard_markdown(
        ledger,
        generated_at="2026-05-16 08:48 EEST",
    )

    assert "# InvestmentAgent Performance" in output
    assert "Research triage only. Not financial advice." in output
    assert "## Trading Ideas" in output
    assert "| 5d | 1 | 100.0% | 20.0% | 20.0% |" in output
    assert "## Long-Term Ideas" in output
    assert "## Learning Suggestions" in output


def test_learning_suggestions_require_minimum_sample_size():
    ledger = empty_ledger()
    for index in range(9):
        payload = report_payload()
        payload["items"][0]["rank"] = index + 1
        payload["items"][0]["company"]["ticker"] = f"AAA{index}"
        payload["items"][0]["score"]["reasons"] = ["High live turnover"]
        payload["items"][0]["financials"]["price"] = 10.0
        ledger = add_report_picks(
            ledger,
            payload,
            report_date=date(2026, 5, 11),
            report_url="reports/trading/2026-05-11.html",
        )
    lookup = {
        (f"AAA{index}", "SE"): {"price": 11.0, "currency": "SEK"}
        for index in range(9)
    }
    ledger = update_due_outcomes(ledger, as_of_date=date(2026, 5, 16), price_lookup=lookup)

    assert learning_suggestions(ledger) == [
        "No learning suggestions yet. At least 10 completed observations are needed for a signal."
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py::test_render_scorecard_markdown_includes_strategy_sections_and_disclaimer tests/test_performance.py::test_learning_suggestions_require_minimum_sample_size -v
```

Expected: FAIL because rendering helpers do not exist yet.

- [ ] **Step 3: Implement scorecard rendering**

Add these functions to `src/investmentagent/performance.py`:

```python
def render_scorecard_markdown(
    ledger: dict[str, Any], *, generated_at: str
) -> str:
    summary = summarize_ledger(ledger)
    lines = [
        "# InvestmentAgent Performance",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Generated: {generated_at}",
        "",
        "## Trading Ideas",
        *_strategy_table(summary, "trading"),
        "",
        "## Long-Term Ideas",
        *_strategy_table(summary, "long-term"),
        "",
        "## Best Completed Picks",
        *_pick_lines(summary["best_picks"]),
        "",
        "## Worst Completed Picks",
        *_pick_lines(summary["worst_picks"]),
        "",
        "## Signal Review",
        *_signal_lines(summary["signals"]),
        "",
        "## Learning Suggestions",
        *[f"- {suggestion}" for suggestion in learning_suggestions(ledger)],
    ]
    return "\n".join(lines)


def learning_suggestions(ledger: dict[str, Any]) -> list[str]:
    eligible = [
        signal
        for signal in _signal_summaries(ledger)
        if signal["observations"] >= 10
    ]
    if not eligible:
        return [
            "No learning suggestions yet. At least 10 completed observations are needed for a signal."
        ]
    suggestions = []
    for signal in eligible[:5]:
        direction = "positive" if signal["average_return_pct"] > 0 else "negative"
        suggestions.append(
            f"{signal['signal']} has produced a {direction} average return "
            f"of {signal['average_return_pct']}% across {signal['observations']} "
            "completed observations. Review whether its scoring weight should change."
        )
    return suggestions


def _strategy_table(summary: dict[str, Any], strategy: str) -> list[str]:
    lines = [
        "| Horizon | Completed | Hit Rate | Average Return | Median Return |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        row = summary["strategies"][strategy][horizon]
        lines.append(
            "| "
            f"{horizon} | "
            f"{row['completed']} | "
            f"{_percent_cell(row['hit_rate_pct'])} | "
            f"{_percent_cell(row['average_return_pct'])} | "
            f"{_percent_cell(row['median_return_pct'])} |"
        )
    return lines


def _pick_lines(picks: list[dict[str, Any]]) -> list[str]:
    if not picks:
        return ["- No completed picks yet."]
    return [
        f"- {pick['name']} ({pick['ticker']}), {pick['strategy']} {pick['horizon']}: "
        f"{pick['return_pct']}% - [{pick['report_url']}]({pick['report_url']})"
        for pick in picks
    ]


def _signal_lines(signals: list[dict[str, Any]]) -> list[str]:
    if not signals:
        return ["- No completed signal observations yet."]
    return [
        f"- {signal['signal']}: {signal['observations']} observations, "
        f"{signal['average_return_pct']}% average return, "
        f"{signal['hit_rate_pct']}% hit rate"
        for signal in signals[:12]
    ]


def _percent_cell(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value}%"
```

- [ ] **Step 4: Run performance tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_performance.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: render performance scorecard"
```

## Task 6: Add `performance update` CLI

**Files:**
- Modify: `src/investmentagent/cli.py`
- Modify: `src/investmentagent/performance.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add CLI tests**

Add this test near the source command tests in `tests/test_cli.py`:

```python
def test_performance_update_creates_ledger_and_scorecard():
    report = {
        "metadata": {
            "generated_at": "2026-05-11T07:36:10+00:00",
            "strategy": "trading",
        },
        "items": [
            {
                "rank": 1,
                "company": {
                    "ticker": "KAR",
                    "name": "Karnov Group AB",
                    "country": "SE",
                    "exchange": "Nasdaq Stockholm",
                    "segment": "main_market",
                    "sector": "Industrials",
                },
                "financials": {"price": 100.0, "currency": "SEK"},
                "score": {"total": 20, "reasons": ["High live turnover"], "warnings": []},
                "risks": [],
                "data_quality": "partial",
            }
        ],
    }
    with runner.isolated_filesystem():
        Path("reports").mkdir()
        Path("reports/trading.json").write_text(json.dumps(report))

        result = runner.invoke(
            app,
            [
                "performance",
                "update",
                "--report-json",
                "reports/trading.json",
                "--report-date",
                "2026-05-11",
                "--ledger",
                "docs/data/performance/ledger.json",
                "--output",
                "docs/performance/index.md",
                "--latest",
                "docs/performance/latest.md",
                "--price-provider",
                "off",
                "--generated-at",
                "2026-05-11 08:48 EEST",
            ],
        )

        ledger = json.loads(Path("docs/data/performance/ledger.json").read_text())
        scorecard = Path("docs/performance/index.md").read_text()
        latest = Path("docs/performance/latest.md").read_text()

    assert result.exit_code == 0
    assert ledger["picks"][0]["ticker"] == "KAR"
    assert "# InvestmentAgent Performance" in scorecard
    assert latest == scorecard
```

- [ ] **Step 2: Run the failing CLI test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_performance_update_creates_ledger_and_scorecard -v
```

Expected: FAIL because no `performance` command exists.

- [ ] **Step 3: Add provider price lookup helper**

Add to `src/investmentagent/performance.py`:

```python
def price_lookup_from_provider(provider, *, countries: tuple[str, ...] = ("SE", "FI")):
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for company in provider.list_companies(countries=countries, include_first_north=True):
        get_company_research = getattr(provider, "get_company_research", None)
        if callable(get_company_research):
            research = get_company_research(company)
        else:
            research = provider.get_research(company.ticker)
        lookup[(company.ticker, company.country)] = {
            "price": research.financials.price,
            "currency": research.financials.currency,
        }
    return lookup
```

- [ ] **Step 4: Add the Typer subapp and command**

In `src/investmentagent/cli.py`, add imports:

```python
import json
from datetime import date
```

Extend the performance imports:

```python
from investmentagent.performance import (
    add_report_picks,
    load_ledger,
    parse_report_date,
    price_lookup_from_provider,
    render_scorecard_markdown,
    save_ledger,
    update_due_outcomes,
)
```

Add the subapp near `sources_app`:

```python
performance_app = typer.Typer(help="Track and publish watchlist performance.")
app.add_typer(performance_app, name="performance")
```

Add this command before `if __name__ == "__main__":`:

```python
@performance_app.command("update")
def performance_update(
    report_json_paths: list[str] = typer.Option(
        ..., "--report-json", help="Saved watchlist report JSON file. Can be repeated."
    ),
    report_date_raw: str = typer.Option(..., "--report-date", help="Report date YYYY-MM-DD."),
    ledger_path: str = typer.Option(
        "docs/data/performance/ledger.json", "--ledger", help="Performance ledger path."
    ),
    output_path: str = typer.Option(
        "docs/performance/index.md", "--output", help="Performance scorecard Markdown path."
    ),
    latest_path: str | None = typer.Option(
        None, "--latest", help="Optional latest scorecard copy path."
    ),
    price_provider_name: str = typer.Option(
        "live", "--price-provider", help="Price provider: live, fixture, or off."
    ),
    generated_at: str | None = typer.Option(
        None, "--generated-at", help="Display timestamp for the scorecard."
    ),
) -> None:
    report_date = parse_report_date(report_date_raw)
    ledger_file = Path(ledger_path)
    ledger = load_ledger(ledger_file)
    for report_json_path in report_json_paths:
        report_path = Path(report_json_path)
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        strategy = report_payload.get("metadata", {}).get("strategy")
        if strategy not in {"trading", "long-term"}:
            raise typer.BadParameter("report-json metadata strategy must be trading or long-term")
        report_url = f"reports/{strategy}/{report_date.isoformat()}.html"
        ledger = add_report_picks(
            ledger,
            report_payload,
            report_date=report_date,
            report_url=report_url,
        )
    normalized_price_provider = price_provider_name.strip().lower()
    if normalized_price_provider == "off":
        price_lookup = {}
    else:
        provider = _provider_from_option(normalized_price_provider)
        if normalized_price_provider == "live":
            _raise_for_source_errors(provider)
        price_lookup = price_lookup_from_provider(provider)
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date.today(),
        price_lookup=price_lookup,
    )
    save_ledger(ledger_file, ledger)
    display_timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    scorecard = render_scorecard_markdown(ledger, generated_at=display_timestamp)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(scorecard + "\n", encoding="utf-8")
    if latest_path is not None:
        latest_file = Path(latest_path)
        latest_file.parent.mkdir(parents=True, exist_ok=True)
        latest_file.write_text(scorecard + "\n", encoding="utf-8")
```

- [ ] **Step 5: Run focused CLI test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_performance_update_creates_ledger_and_scorecard -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/investmentagent/cli.py src/investmentagent/performance.py tests/test_cli.py
git commit -m "feat: add performance update cli"
```

## Task 7: Wire Performance Into Daily Public Workflow

**Files:**
- Modify: `.github/workflows/daily-public-watchlist.yml`
- Modify: `README.md`

- [ ] **Step 1: Update workflow report generation**

In `.github/workflows/daily-public-watchlist.yml`, inside `generate_report()`, add a JSON path and repeated save:

```bash
            json_path="$RUNNER_TEMP/${report_name}-${report_date}.json"

            mkdir -p "$report_dir"
            investmentagent watchlist \
              --provider live \
              --fundamentals finimpulse \
              --country se,fi \
              --limit 10 \
              --min-country FI:3 \
              --strategy "$strategy" \
              --verbose \
              --save "$report_path" \
              --save "$json_path" \
              > "$RUNNER_TEMP/${report_name}-watchlist-output.txt"
```

After both `generate_report` calls, add:

```bash
          mkdir -p docs/performance docs/data/performance
          investmentagent performance update \
            --report-json "$RUNNER_TEMP/trading-${report_date}.json" \
            --report-json "$RUNNER_TEMP/long-term-${report_date}.json" \
            --report-date "$report_date" \
            --ledger docs/data/performance/ledger.json \
            --output docs/performance/index.md \
            --latest docs/performance/latest.md \
            --price-provider live \
            --generated-at "$generated_at"
```

In the generated `docs/index.md` block, add:

```bash
            echo "- [Performance Scorecard](performance/index.html)"
```

In the commit step, change:

```bash
          git add docs/index.md "$REPORT_ROOT"
```

to:

```bash
          git add docs/index.md "$REPORT_ROOT" docs/performance docs/data/performance
```

- [ ] **Step 2: Update README public pages**

In `README.md`, add the public performance URL under "Public pages":

```markdown
- Performance scorecard: `https://vernerisirva.github.io/investmentagent/performance/`
```

Add a short paragraph after the long-term report sentence:

```markdown
The performance page tracks published picks over 1d, 5d, 20d, and 60d horizons. It summarizes results publicly and may suggest scoring ideas after enough observations, but it does not change ranking weights automatically.
```

- [ ] **Step 3: Run full tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/daily-public-watchlist.yml README.md
git commit -m "feat: publish performance scorecard"
```

## Task 8: Local Fixture Smoke Test

**Files:**
- Generated locally: `/private/tmp/investmentagent-performance-smoke`

- [ ] **Step 1: Create fixture reports in a temporary directory**

Run:

```bash
mkdir -p /private/tmp/investmentagent-performance-smoke/reports/trading /private/tmp/investmentagent-performance-smoke/reports/long-term
PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli watchlist --provider fixture --strategy trading --limit 3 --save /private/tmp/investmentagent-performance-smoke/reports/trading/2026-05-11.md --save /private/tmp/investmentagent-performance-smoke/trading.json
PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli watchlist --provider fixture --strategy long-term --limit 3 --save /private/tmp/investmentagent-performance-smoke/reports/long-term/2026-05-11.md --save /private/tmp/investmentagent-performance-smoke/long-term.json
```

Expected: both commands exit `0` and create Markdown plus JSON files.

- [ ] **Step 2: Build a scorecard from fixture reports**

Run:

```bash
PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli performance update --report-json /private/tmp/investmentagent-performance-smoke/trading.json --report-json /private/tmp/investmentagent-performance-smoke/long-term.json --report-date 2026-05-11 --ledger /private/tmp/investmentagent-performance-smoke/ledger.json --output /private/tmp/investmentagent-performance-smoke/performance.md --latest /private/tmp/investmentagent-performance-smoke/latest.md --price-provider fixture --generated-at "2026-05-11 08:48 EEST"
```

Expected: command exits `0`, `ledger.json` contains six picks, and `performance.md` contains `# InvestmentAgent Performance`.

- [ ] **Step 3: Inspect generated files**

Run:

```bash
sed -n '1,160p' /private/tmp/investmentagent-performance-smoke/performance.md
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m json.tool /private/tmp/investmentagent-performance-smoke/ledger.json >/private/tmp/investmentagent-performance-smoke/ledger.pretty.json
```

Expected: the scorecard has Trading Ideas and Long-Term Ideas sections, and JSON formatting succeeds.

## Task 9: Live Workflow-Equivalent Smoke Test

**Files:**
- Generated locally under `/private/tmp/investmentagent-performance-live-smoke`

- [ ] **Step 1: Run live report generation with local `.env` token**

Run from the repo root:

```bash
/bin/zsh -lc 'set -a; source .env; set +a; export FINIMPULSE_API_KEY="${FINIMPULSE_API_KEY:-$FINNHUB_API_KEY}"; mkdir -p /private/tmp/investmentagent-performance-live-smoke/reports/trading /private/tmp/investmentagent-performance-live-smoke/reports/long-term; PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli watchlist --provider live --fundamentals finimpulse --country se,fi --limit 10 --min-country FI:3 --strategy trading --save /private/tmp/investmentagent-performance-live-smoke/reports/trading/$(date +%F).md --save /private/tmp/investmentagent-performance-live-smoke/trading.json --verbose; PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli watchlist --provider live --fundamentals finimpulse --country se,fi --limit 10 --min-country FI:3 --strategy long-term --save /private/tmp/investmentagent-performance-live-smoke/reports/long-term/$(date +%F).md --save /private/tmp/investmentagent-performance-live-smoke/long-term.json --verbose'
```

Expected: Nasdaq source check is `ok`, Finimpulse lookup count is reported, no API token text appears in output.

- [ ] **Step 2: Run live performance update**

Run:

```bash
/bin/zsh -lc 'set -a; source .env; set +a; PYTHONPATH=src /Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m investmentagent.cli performance update --report-json /private/tmp/investmentagent-performance-live-smoke/trading.json --report-json /private/tmp/investmentagent-performance-live-smoke/long-term.json --report-date $(date +%F) --ledger /private/tmp/investmentagent-performance-live-smoke/ledger.json --output /private/tmp/investmentagent-performance-live-smoke/performance.md --latest /private/tmp/investmentagent-performance-live-smoke/latest.md --price-provider live --generated-at "$(date "+%Y-%m-%d %H:%M %Z")"'
```

Expected: command exits `0`, scorecard is generated, ledger contains 20 picks when both reports contain 10 items.

## Task 10: Final Verification And Push

**Files:**
- All modified source, tests, workflow, README.

- [ ] **Step 1: Run full test suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Check git status and diff**

Run:

```bash
git status --short
git diff --check
git diff --stat
```

Expected: only intended files changed; no whitespace errors. Existing untracked local `reports/` and `scripts/` may remain untouched.

- [ ] **Step 3: Commit final verification updates if needed**

If Task 8 or Task 9 revealed small fixes, commit them:

```bash
git add src/investmentagent tests .github/workflows/daily-public-watchlist.yml README.md
git commit -m "feat: track public watchlist performance"
```

If no additional fixes exist after Task 7's commit, do not create an empty commit.

- [ ] **Step 4: Push**

Run:

```bash
git push origin main
```

Expected: push succeeds. If remote `main` moved because the workflow published reports, run `git fetch origin main`, `git rebase origin/main`, re-run the full tests, and push again.

## Self-Review

Spec coverage:

- Public scorecard: Task 5 and Task 7.
- Versioned ledger: Task 3 and Task 6.
- Trading and long-term separation: Task 4 and Task 5.
- 1d, 5d, 20d, 60d outcomes: Task 3 and Task 4.
- Learning suggestions with minimum sample size: Task 5.
- Daily workflow integration: Task 7.
- Deterministic tests without internet: Tasks 1-6.
- Live smoke: Task 9.

Placeholder scan: no TBD, TODO, or incomplete implementation steps remain.

Type consistency: report payload keys, ledger keys, function names, and CLI option names are consistent across tasks.
