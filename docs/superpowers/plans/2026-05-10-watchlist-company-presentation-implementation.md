# Watchlist Company Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a short deterministic company presentation to each watchlist item in text and JSON output.

**Architecture:** Keep this as renderer-only presentation logic in `src/investmentagent/renderers.py`. Do not add model fields or scoring changes; JSON and text renderers should call the same helper.

**Tech Stack:** Python 3, existing dataclasses, pytest, standard JSON rendering.

---

## File Structure

- Modify `src/investmentagent/renderers.py`: add presentation helper and include it in text and item JSON payloads.
- Modify `tests/test_reports.py`: add renderer tests for text, JSON, saved-report payload shape, missing-value omission, and enriched financial context.
- No CLI, provider, scoring, or model changes.

## Task 1: Renderer Presentation Helper

**Files:**
- Modify: `src/investmentagent/renderers.py`
- Test: `tests/test_reports.py`

- [ ] **Step 1: Write failing renderer tests**

Update the renderer imports in `tests/test_reports.py` to include `render_watchlist_report_json`:

```python
from investmentagent.renderers import (
    render_deep_dive_json,
    render_deep_dive_text,
    render_watchlist_json,
    render_watchlist_report_json,
    render_watchlist_text,
)
```

Add these tests near the existing watchlist renderer tests:

```python
def test_render_watchlist_text_includes_company_presentation():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True
    )

    output = render_watchlist_text(items)

    assert "Presentation:" in output
    assert "listed" in output
    assert "Score:" in output
    assert output.index("Presentation:") < output.index("Score:")


def test_render_watchlist_json_includes_company_presentation():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True
    )

    payload = json.loads(render_watchlist_json(items))

    presentation = payload["items"][0]["company_presentation"]
    assert presentation
    assert "None" not in presentation
    assert payload["items"][0]["company"]["name"].split()[0] in presentation


def test_render_watchlist_report_json_includes_company_presentation():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True
    )

    payload = json.loads(
        render_watchlist_report_json(
            items,
            metadata={"provider": "fixture"},
            source_checks=[],
        )
    )

    assert payload["items"][0]["company_presentation"]


def test_render_watchlist_presentation_omits_missing_values():
    company = Company(
        name="Sparse AB",
        ticker="SPRS",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.THIN),
            data_quality=DataQuality.THIN,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=0.0,
        ),
    )

    payload = json.loads(render_watchlist_json([item]))
    presentation = payload["items"][0]["company_presentation"]

    assert presentation == (
        "Sparse AB is a Sweden-listed First North company on "
        "Nasdaq First North Growth Market Sweden."
    )
    assert "None" not in presentation
    assert "unknown" not in presentation.lower()


def test_render_watchlist_presentation_includes_enriched_financial_context():
    company = Company(
        name="Karnov Group AB",
        ticker="KAR",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        sector="Industrials",
        market_cap_eur_m=702.42,
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(
                revenue_growth_pct=24.64,
                operating_margin_pct=36.76,
                one_year_return_pct=-16.473,
                data_quality=DataQuality.PARTIAL,
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=0.0,
        ),
    )

    payload = json.loads(render_watchlist_json([item]))
    presentation = payload["items"][0]["company_presentation"]

    assert presentation == (
        "Karnov Group AB is a Sweden-listed main market Industrials company on "
        "Nasdaq Stockholm. Market cap is about EUR 702m, revenue growth is 24.6%, "
        "operating margin is 36.8%, and one-year return is -16.5%."
    )
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_render_watchlist_text_includes_company_presentation tests/test_reports.py::test_render_watchlist_json_includes_company_presentation tests/test_reports.py::test_render_watchlist_presentation_includes_enriched_financial_context -v
```

Expected: fail because `company_presentation` and `Presentation:` are not implemented.

- [ ] **Step 3: Implement presentation helper**

In `src/investmentagent/renderers.py`, add `ListingSegment` to imports:

```python
from investmentagent.models import (
    Company,
    DataQuality,
    DeepDiveReport,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)
```

Add a presentation line to `render_watchlist_text` between the listing line and score line:

```python
f"Presentation: {_company_presentation(item)}",
```

Update `_watchlist_items_payload` to include:

```python
"company_presentation": _company_presentation(item),
```

Add helper functions near other renderer helpers:

```python
def _company_presentation(item: WatchlistItem) -> str:
    company = item.research.company
    financials = item.research.financials
    country = _country_name(company.country)
    segment = _segment_label(company.segment)

    sector_part = f" {company.sector}" if company.sector else ""
    base = (
        f"{company.name} is a {country}-listed {segment}{sector_part} company "
        f"on {company.exchange}."
    )

    facts = []
    market_cap = _market_cap_phrase(company.market_cap_eur_m)
    if market_cap is not None:
        facts.append(f"Market cap is about {market_cap}")
    revenue_growth = _percentage_phrase("revenue growth", financials.revenue_growth_pct)
    if revenue_growth is not None:
        facts.append(revenue_growth)
    operating_margin = _percentage_phrase("operating margin", financials.operating_margin_pct)
    if operating_margin is not None:
        facts.append(operating_margin)
    one_year_return = _percentage_phrase("one-year return", financials.one_year_return_pct)
    if one_year_return is not None:
        facts.append(one_year_return)

    if not facts:
        return base
    return f"{base} {_join_sentence_facts(facts)}."
```

Add formatting helpers:

```python
def _country_name(country: str) -> str:
    return {"SE": "Sweden", "FI": "Finland"}.get(country.upper(), country.upper())


def _segment_label(segment) -> str:
    if segment == ListingSegment.FIRST_NORTH:
        return "First North"
    if segment == ListingSegment.MAIN_MARKET:
        return "main market"
    if segment == ListingSegment.SPOTLIGHT:
        return "Spotlight"
    return "public market"


def _market_cap_phrase(value: float | None) -> str | None:
    if value is None:
        return None
    if abs(value) >= 100:
        return f"EUR {value:.0f}m"
    return f"EUR {value:.1f}m"


def _percentage_phrase(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label} is {value:.1f}%"


def _join_sentence_facts(facts: list[str]) -> str:
    if len(facts) == 1:
        return facts[0]
    if len(facts) == 2:
        return f"{facts[0]} and {facts[1]}"
    return f"{', '.join(facts[:-1])}, and {facts[-1]}"
```

- [ ] **Step 4: Run focused renderer tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py::test_render_watchlist_text_includes_company_presentation tests/test_reports.py::test_render_watchlist_json_includes_company_presentation tests/test_reports.py::test_render_watchlist_report_json_includes_company_presentation tests/test_reports.py::test_render_watchlist_presentation_omits_missing_values tests/test_reports.py::test_render_watchlist_presentation_includes_enriched_financial_context -v
```

Expected: all pass.

- [ ] **Step 5: Run full report tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_reports.py -v
```

Expected: all report tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/investmentagent/renderers.py tests/test_reports.py
git commit -m "feat: add watchlist company presentations"
```

## Task 2: Full Verification and Live Smoke

**Files:**
- Verify: full repo

- [ ] **Step 1: Run full test suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run token-safe live smoke if `.env` is available**

Do not print the token. Use:

```bash
set -a
source .env
set +a
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --fundamentals finimpulse --country se,fi --limit 3 --verbose
```

Expected: output includes `Presentation:` lines and Finimpulse source check is ok or warning. The command should not print token values or Authorization headers.

- [ ] **Step 3: Commit if any verification-only docs changed**

If no files changed, skip this commit.

## Self-Review

- Spec coverage: text output, JSON output, saved JSON reports, missing-value omission, deterministic structured data, and no web/profile calls are covered.
- Placeholder scan: no TODO/TBD placeholders remain.
- Type consistency: helper uses existing `WatchlistItem`, `Company`, `FinancialSnapshot`, and `ListingSegment` names.
