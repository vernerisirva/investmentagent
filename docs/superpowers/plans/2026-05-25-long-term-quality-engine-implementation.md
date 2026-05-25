# Long-Term Quality Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the `long-term` watchlist so First North and small-cap companies still surface, but the top ranks favor durable fundamental evidence over discovery alone.

**Architecture:** Add a focused `investmentagent.long_term_quality` module that computes quality signals, proof gaps, penalties, and conviction buckets from a `CompanyResearch` object. Wire that module into the existing long-term scoring path in `reports.py`, the conviction rendering path in `renderers.py`, and the performance signal review in `performance.py`. Keep the existing CLI and daily workflow unchanged.

**Tech Stack:** Python 3.11+, dataclasses, existing Typer CLI, pytest, no new dependencies.

---

## File Structure

- Create `src/investmentagent/long_term_quality.py`: long-term quality assessment, proof-gap detection, scoring adjustments, and bucket/thesis helpers.
- Create `tests/test_long_term_quality.py`: focused unit tests for the new quality assessment module.
- Modify `src/investmentagent/reports.py`: replace the current inline long-term quality adjustments with the new module.
- Modify `src/investmentagent/renderers.py`: use the new bucket names and thesis output from the quality module while keeping existing component tables.
- Modify `src/investmentagent/performance.py`: add long-term quality signals to performance review buckets.
- Modify `tests/test_reports.py`: update long-term ranking and report-rendering expectations.
- Modify `tests/test_performance.py`: verify quality-related long-term signal grouping.

## Task 1: Add Long-Term Quality Assessment Module

**Files:**
- Create: `src/investmentagent/long_term_quality.py`
- Test: `tests/test_long_term_quality.py`

- [ ] **Step 1: Write failing tests for quality assessment**

Create `tests/test_long_term_quality.py`:

```python
from investmentagent.long_term_quality import (
    LongTermQualityBucket,
    assess_long_term_quality,
)
from investmentagent.models import Company, CompanyResearch, DataQuality, FinancialSnapshot, ListingSegment


def make_research(
    *,
    ticker: str = "QUAL",
    segment: ListingSegment = ListingSegment.FIRST_NORTH,
    business_description: str | None = "Quality AB sells workflow software.",
    pe_ratio: float | None = 12.0,
    price_to_book: float | None = 1.4,
    net_cash_eur_m: float | None = 10.0,
    debt_to_equity: float | None = 0.2,
    revenue_growth_pct: float | None = 10.0,
    operating_margin_pct: float | None = 14.0,
    average_daily_value_eur: float | None = 250_000,
    catalysts: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
    data_quality: DataQuality = DataQuality.PARTIAL,
) -> CompanyResearch:
    return CompanyResearch(
        company=Company(
            name=f"{ticker} AB",
            ticker=ticker,
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=segment,
            sector="Software",
            market_cap_eur_m=180,
            currency="SEK",
            business_description=business_description,
        ),
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            price_to_book=price_to_book,
            net_cash_eur_m=net_cash_eur_m,
            debt_to_equity=debt_to_equity,
            revenue_growth_pct=revenue_growth_pct,
            operating_margin_pct=operating_margin_pct,
            average_daily_value_eur=average_daily_value_eur,
            data_quality=data_quality,
        ),
        catalysts=catalysts,
        risks=risks,
        data_quality=data_quality,
    )


def test_quality_assessment_rewards_first_north_with_durable_fundamentals():
    profile = assess_long_term_quality(make_research())

    assert profile.bucket == LongTermQualityBucket.QUALITY_SMALL_CAP
    assert profile.quality_adjustment > 25
    assert profile.proof_penalty == 0
    assert "Quality small-cap candidate" in profile.bucket.value
    assert "Positive operating margin" in profile.reasons
    assert "Revenue growth" in profile.reasons
    assert "Conservative balance sheet" in profile.reasons
    assert "First North discovery opportunity" in profile.reasons


def test_quality_assessment_penalizes_first_north_without_long_term_proof():
    profile = assess_long_term_quality(
        make_research(
            ticker="SPEC",
            business_description=None,
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            debt_to_equity=None,
            revenue_growth_pct=None,
            operating_margin_pct=None,
            average_daily_value_eur=40_000,
            catalysts=("Strong intraday momentum (+18.0%)", "High live turnover"),
            risks=("Sparse live-source data",),
            data_quality=DataQuality.THIN,
        )
    )

    assert profile.bucket == LongTermQualityBucket.INSUFFICIENT_EVIDENCE
    assert profile.proof_penalty >= 30
    assert "Missing valuation data" in profile.proof_gaps
    assert "No profitability signal" in profile.proof_gaps
    assert "No growth signal" in profile.proof_gaps
    assert "Thin liquidity" in profile.proof_gaps
    assert "Only live-market support" in profile.proof_gaps


def test_quality_assessment_labels_speculative_monitor_when_some_proof_exists():
    profile = assess_long_term_quality(
        make_research(
            ticker="MON",
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            debt_to_equity=0.4,
            revenue_growth_pct=4.0,
            operating_margin_pct=None,
            average_daily_value_eur=120_000,
            data_quality=DataQuality.PARTIAL,
        )
    )

    assert profile.bucket == LongTermQualityBucket.SPECULATIVE_MONITOR
    assert "Missing valuation data" in profile.proof_gaps
    assert "No profitability signal" in profile.proof_gaps
    assert profile.quality_adjustment > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_long_term_quality.py -q
```

Expected: fail during collection with `ModuleNotFoundError: No module named 'investmentagent.long_term_quality'`.

- [ ] **Step 3: Implement the long-term quality module**

Create `src/investmentagent/long_term_quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from investmentagent.models import CompanyResearch, DataQuality, ListingSegment


class LongTermQualityBucket(str, Enum):
    QUALITY_SMALL_CAP = "Quality small-cap candidate"
    FUNDAMENTAL_WATCHLIST = "Fundamental watchlist candidate"
    SPECULATIVE_MONITOR = "Speculative small-cap monitor"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


@dataclass(frozen=True)
class LongTermQualityProfile:
    quality_adjustment: float
    proof_penalty: float
    bucket: LongTermQualityBucket
    reasons: tuple[str, ...]
    proof_gaps: tuple[str, ...]
    thesis: str


def assess_long_term_quality(research: CompanyResearch) -> LongTermQualityProfile:
    financials = research.financials
    company = research.company
    reasons: list[str] = []
    proof_gaps: list[str] = []
    quality_adjustment = 0.0
    proof_penalty = 0.0

    if company.segment == ListingSegment.FIRST_NORTH:
        quality_adjustment += 5.0
        reasons.append("First North discovery opportunity")

    if financials.operating_margin_pct is not None and financials.operating_margin_pct > 0:
        quality_adjustment += 10.0
        reasons.append(f"Positive operating margin ({financials.operating_margin_pct:.1f}%)")
    elif financials.operating_margin_pct is not None and financials.operating_margin_pct < 0:
        proof_penalty += 14.0
        proof_gaps.append("Negative operating margin")
    else:
        proof_penalty += 8.0
        proof_gaps.append("No profitability signal")

    if financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0:
        quality_adjustment += 8.0
        reasons.append(f"Revenue growth ({financials.revenue_growth_pct:.1f}%)")
    else:
        proof_penalty += 7.0
        proof_gaps.append("No growth signal")

    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        quality_adjustment += 7.0
        reasons.append("Net cash balance sheet")
    elif financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        quality_adjustment += 5.0
        reasons.append("Conservative balance sheet")
    elif financials.debt_to_equity is not None and financials.debt_to_equity > 1.5:
        proof_penalty += 10.0
        proof_gaps.append("High debt/equity")

    has_valuation = any(
        metric is not None
        for metric in (
            financials.pe_ratio,
            financials.price_to_book,
            financials.ev_to_ebit,
        )
    )
    if _has_attractive_valuation(research):
        quality_adjustment += 8.0
        reasons.append("Attractive valuation support")
    elif has_valuation:
        quality_adjustment += 2.0
        reasons.append("Valuation data available")
    else:
        proof_penalty += 9.0
        proof_gaps.append("Missing valuation data")

    if company.business_description:
        quality_adjustment += 4.0
        reasons.append("Business description available")
    else:
        proof_penalty += 5.0
        proof_gaps.append("Missing business description")

    if financials.average_daily_value_eur is not None:
        if financials.average_daily_value_eur >= 100_000:
            quality_adjustment += 3.0
            reasons.append("Adequate liquidity")
        else:
            proof_penalty += 7.0
            proof_gaps.append("Thin liquidity")

    if _has_live_only_support(research) and not _has_durable_support(research):
        proof_penalty += 12.0
        proof_gaps.append("Only live-market support")

    if research.data_quality == DataQuality.THIN:
        proof_penalty += 8.0
        proof_gaps.append("Thin data quality")
    elif research.data_quality == DataQuality.PARTIAL:
        proof_penalty += 3.0

    bucket = _bucket_for(quality_adjustment, proof_penalty, proof_gaps)
    return LongTermQualityProfile(
        quality_adjustment=round(quality_adjustment, 2),
        proof_penalty=round(proof_penalty, 2),
        bucket=bucket,
        reasons=tuple(reasons),
        proof_gaps=tuple(dict.fromkeys(proof_gaps)),
        thesis=_thesis_for(research, bucket, proof_gaps),
    )


def _has_attractive_valuation(research: CompanyResearch) -> bool:
    financials = research.financials
    return any(
        (
            financials.pe_ratio is not None and 0 < financials.pe_ratio <= 14,
            financials.price_to_book is not None and 0 < financials.price_to_book <= 1.5,
            financials.ev_to_ebit is not None and 0 < financials.ev_to_ebit <= 12,
        )
    )


def _has_durable_support(research: CompanyResearch) -> bool:
    financials = research.financials
    return any(
        (
            financials.operating_margin_pct is not None and financials.operating_margin_pct > 0,
            financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0,
            financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0,
            financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5,
            _has_attractive_valuation(research),
            bool(research.company.business_description),
        )
    )


def _has_live_only_support(research: CompanyResearch) -> bool:
    signals = tuple(item.lower() for item in (*research.catalysts, *research.risks))
    live_terms = (
        "live price available",
        "live turnover",
        "intraday momentum",
        "sparse live-source data",
    )
    return bool(signals) and all(any(term in signal for term in live_terms) for signal in signals)


def _bucket_for(
    quality_adjustment: float, proof_penalty: float, proof_gaps: list[str]
) -> LongTermQualityBucket:
    if proof_penalty >= 35 or len(proof_gaps) >= 5:
        return LongTermQualityBucket.INSUFFICIENT_EVIDENCE
    if quality_adjustment >= 32 and proof_penalty <= 8:
        return LongTermQualityBucket.QUALITY_SMALL_CAP
    if quality_adjustment >= 20 and proof_penalty <= 18:
        return LongTermQualityBucket.FUNDAMENTAL_WATCHLIST
    return LongTermQualityBucket.SPECULATIVE_MONITOR


def _thesis_for(
    research: CompanyResearch, bucket: LongTermQualityBucket, proof_gaps: list[str]
) -> str:
    name = research.company.name
    if bucket == LongTermQualityBucket.QUALITY_SMALL_CAP:
        return (
            f"{name} has multiple long-term quality signals for a small-cap research queue; "
            "verify valuation, reporting cadence, and liquidity before acting."
        )
    if bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST:
        return (
            f"{name} has enough fundamental evidence for manual research, but at least one "
            "proof gap should be checked before it becomes a high-priority idea."
        )
    if bucket == LongTermQualityBucket.SPECULATIVE_MONITOR:
        issue = proof_gaps[0].lower() if proof_gaps else "the evidence is incomplete"
        return (
            f"{name} is an interesting small-cap monitor, but the long-term case needs more "
            f"proof because {issue}."
        )
    return (
        f"{name} lacks enough durable evidence for a strong long-term thesis today; wait "
        "for clearer fundamentals, valuation, liquidity, or business evidence."
    )
```

- [ ] **Step 4: Run tests to verify the module passes**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_long_term_quality.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/investmentagent/long_term_quality.py tests/test_long_term_quality.py
git commit -m "feat: assess long-term small-cap quality"
```

## Task 2: Wire Quality Assessment Into Long-Term Ranking

**Files:**
- Modify: `src/investmentagent/reports.py:291-370`
- Test: `tests/test_reports.py`

- [ ] **Step 1: Write failing ranking tests**

Add these tests after `test_long_term_strategy_downweights_discovery_without_fundamentals` in `tests/test_reports.py`:

```python
def test_long_term_strategy_keeps_first_north_but_requires_quality_evidence():
    quality_first_north = CompanyResearch(
        company=Company(
            name="Quality First North AB",
            ticker="QFN",
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=ListingSegment.FIRST_NORTH,
            sector="Software",
            market_cap_eur_m=180,
            currency="SEK",
            business_description="Quality First North sells profitable workflow software.",
        ),
        financials=FinancialSnapshot(
            pe_ratio=13.0,
            price_to_book=1.4,
            net_cash_eur_m=15.0,
            debt_to_equity=0.2,
            revenue_growth_pct=11.0,
            operating_margin_pct=16.0,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )
    speculative_first_north = CompanyResearch(
        company=Company(
            name="Speculative First North AB",
            ticker="SFN",
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=ListingSegment.FIRST_NORTH,
            sector="Technology",
            market_cap_eur_m=80,
            currency="SEK",
        ),
        financials=FinancialSnapshot(
            average_daily_value_eur=35_000,
            data_quality=DataQuality.THIN,
        ),
        catalysts=("Strong intraday momentum (+18.0%)", "High live turnover"),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )

    items = build_watchlist(
        FakeResearchProvider((speculative_first_north, quality_first_north)),
        countries=("SE",),
        limit=2,
        include_first_north=True,
        strategy="long-term",
    )

    assert [item.research.company.ticker for item in items] == ["QFN", "SFN"]
    assert "Quality small-cap candidate" in items[0].score.reasons
    assert "Missing valuation data" in items[1].score.warnings
    assert "Only live-market support" in items[1].score.warnings


def test_long_term_strategy_penalizes_missing_valuation_profitability_and_growth():
    weak = CompanyResearch(
        company=Company(
            name="Weak Evidence AB",
            ticker="WEAK",
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=ListingSegment.FIRST_NORTH,
            sector="Technology",
            market_cap_eur_m=90,
            currency="SEK",
            business_description="Weak Evidence has an understandable business.",
        ),
        financials=FinancialSnapshot(
            debt_to_equity=0.3,
            average_daily_value_eur=160_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    items = build_watchlist(
        FakeResearchProvider((weak,)),
        countries=("SE",),
        limit=1,
        include_first_north=True,
        strategy="long-term",
    )

    assert items[0].score.total < 0
    assert "Missing valuation data" in items[0].score.warnings
    assert "No profitability signal" in items[0].score.warnings
    assert "No growth signal" in items[0].score.warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py::test_long_term_strategy_keeps_first_north_but_requires_quality_evidence tests/test_reports.py::test_long_term_strategy_penalizes_missing_valuation_profitability_and_growth -q
```

Expected: fail because `_long_term_score()` does not yet include the new quality profile bucket and proof-gap warnings.

- [ ] **Step 3: Modify `reports.py` imports**

Add this import near the existing imports in `src/investmentagent/reports.py`:

```python
from investmentagent.long_term_quality import assess_long_term_quality
```

- [ ] **Step 4: Replace `_long_term_score()` implementation**

In `src/investmentagent/reports.py`, replace the body of `_long_term_score()` with:

```python
def _long_term_score(research: CompanyResearch, score: ScoreBreakdown) -> ScoreBreakdown:
    quality = assess_long_term_quality(research)
    reasons = tuple(
        reason for reason in score.reasons if not _is_trading_only_signal(reason)
    )
    discovery = round(score.discovery * 0.35, 2)
    catalyst = round(
        min(
            sum(
                8.0
                for catalyst_reason in research.catalysts
                if not _is_trading_only_signal(catalyst_reason)
            ),
            16.0,
        ),
        2,
    )

    trading_penalty = 0.0
    has_intraday_signal = any(
        _is_intraday_signal(signal)
        for signal in (*research.catalysts, *research.risks)
    )
    if has_intraday_signal:
        trading_penalty += 18.0
    if any(
        _has_signal((signal.lower(),), "Extreme intraday spike")
        for signal in research.risks
    ):
        trading_penalty += 18.0
    missing_anchor_penalty = (
        12.0
        if has_intraday_signal and not _has_long_term_fundamental_anchor(research.financials)
        else 0.0
    )

    risk_penalty = round(
        score.risk_penalty
        + trading_penalty
        + missing_anchor_penalty
        + quality.proof_penalty,
        2,
    )
    total = (
        score.value
        + discovery
        + catalyst
        + quality.quality_adjustment
        - risk_penalty
        - score.data_quality_penalty
    )
    warnings = score.warnings
    if trading_penalty:
        warnings = (*warnings, "long-term strategy penalty applied")
    if missing_anchor_penalty:
        warnings = (*warnings, "missing long-term fundamental support")
    warnings = (*warnings, *quality.proof_gaps)

    return ScoreBreakdown(
        value=score.value,
        discovery=discovery,
        catalyst=round(catalyst + quality.quality_adjustment, 2),
        risk_penalty=risk_penalty,
        data_quality_penalty=score.data_quality_penalty,
        total=round(total, 2),
        reasons=(*reasons, quality.bucket.value, *quality.reasons),
        warnings=warnings,
    )
```

- [ ] **Step 5: Remove obsolete inline quality block if needed**

After replacing `_long_term_score()`, make sure the old local variables `financials`, `quality_adjustment`, and `quality_reasons` from the previous implementation are gone from that function. Do not remove `_has_long_term_fundamental_anchor()` because the new function still uses it.

- [ ] **Step 6: Run ranking tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py::test_long_term_strategy_keeps_first_north_but_requires_quality_evidence tests/test_reports.py::test_long_term_strategy_penalizes_missing_valuation_profitability_and_growth -q
```

Expected: `2 passed`.

- [ ] **Step 7: Run existing strategy tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py -q
```

Expected: tests pass after updating any assertions that depended on the old bucket wording or exact long-term totals.

- [ ] **Step 8: Commit**

```bash
git add src/investmentagent/reports.py tests/test_reports.py
git commit -m "feat: rank long-term ideas by quality evidence"
```

## Task 3: Update Long-Term Report Buckets And Thesis Text

**Files:**
- Modify: `src/investmentagent/renderers.py:335-617`
- Test: `tests/test_reports.py`

- [ ] **Step 1: Write failing renderer tests for new bucket names**

Update the existing long-term conviction tests in `tests/test_reports.py`:

```python
def test_render_long_term_report_markdown_includes_quality_small_cap_bucket():
    company = Company(
        name="Quality Compounder AB",
        ticker="QUAL",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Software",
        market_cap_eur_m=240,
        business_description=(
            "Quality Compounder sells mission-critical workflow software to "
            "industrial customers with recurring revenue."
        ),
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
                average_daily_value_eur=250_000,
                data_quality=DataQuality.PARTIAL,
            ),
            risks=(),
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

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "**Bucket:** Quality small-cap candidate" in output
    assert "multiple long-term quality signals" in output
    assert "| Business quality | 5/5 | Strong - profitable business with a clear profile. |" in output
    assert "| Valuation | 5/5 | Attractive valuation on available P/E or P/B metrics. |" in output
```

Add a JSON payload assertion:

```python
def test_render_watchlist_report_json_uses_new_long_term_bucket_names():
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=Company(
                name="Monitor AB",
                ticker="MON",
                country="SE",
                exchange="Nasdaq First North Growth Market Sweden",
                segment=ListingSegment.FIRST_NORTH,
                sector="Technology",
                market_cap_eur_m=80,
                currency="SEK",
                business_description="Monitor AB has an understandable business.",
            ),
            financials=FinancialSnapshot(
                debt_to_equity=0.4,
                revenue_growth_pct=4.0,
                average_daily_value_eur=120_000,
                data_quality=DataQuality.PARTIAL,
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=5.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=4.0,
            total=1.0,
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
    assert conviction["bucket"] == "Speculative small-cap monitor"
    assert "needs more proof" in conviction["thesis"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py::test_render_long_term_report_markdown_includes_quality_small_cap_bucket tests/test_reports.py::test_render_watchlist_report_json_uses_new_long_term_bucket_names -q
```

Expected: fail because `renderers.py` still emits old bucket labels such as `High conviction candidate` and `Speculative / needs more proof`.

- [ ] **Step 3: Modify `renderers.py` imports**

Add this import near the top of `src/investmentagent/renderers.py`:

```python
from investmentagent.long_term_quality import LongTermQualityBucket, assess_long_term_quality
```

- [ ] **Step 4: Update `_long_term_conviction()` to use quality profile bucket and thesis**

Replace `_long_term_conviction()` in `src/investmentagent/renderers.py` with:

```python
def _long_term_conviction(item: WatchlistItem) -> _LongTermConviction:
    components = (
        _business_quality_component(item),
        _valuation_component(item),
        _growth_component(item),
        _balance_sheet_component(item),
        _momentum_component(item),
        _risk_component(item),
        _data_confidence_component(item),
    )
    quality = assess_long_term_quality(item.research)
    return _LongTermConviction(
        bucket=quality.bucket.value,
        thesis=quality.thesis,
        components=components,
    )
```

- [ ] **Step 5: Remove or leave old bucket helpers safely**

After Step 4, `_long_term_bucket()` and `_long_term_thesis()` will no longer be called. Remove these functions if no other references remain:

```bash
rg "_long_term_bucket|_long_term_thesis" src/investmentagent/renderers.py
```

Expected after cleanup: no matches except deleted diff context.

- [ ] **Step 6: Update old renderer tests**

Replace old expected bucket strings in `tests/test_reports.py`:

- `High conviction candidate` -> `Quality small-cap candidate`
- `Trading-only mover` -> `Insufficient evidence`
- `Excluded due to weak data` -> `Insufficient evidence`
- `Speculative / needs more proof` -> `Speculative small-cap monitor`

Where old tests asserted trading-only wording, update them to assert:

```python
assert "lacks enough durable evidence" in output
```

- [ ] **Step 7: Run renderer tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py -q
```

Expected: tests pass after all bucket expectations are updated.

- [ ] **Step 8: Commit**

```bash
git add src/investmentagent/renderers.py tests/test_reports.py
git commit -m "feat: explain long-term quality buckets"
```

## Task 4: Add Long-Term Quality Signals To Performance Review

**Files:**
- Modify: `src/investmentagent/performance.py:581-615`
- Test: `tests/test_performance.py`

- [ ] **Step 1: Write failing performance signal test**

Add this test near existing signal-summary tests in `tests/test_performance.py`:

```python
def test_long_term_performance_review_includes_quality_bucket_signals():
    ledger = {
        "schema_version": 1,
        "picks": [
            {
                "pick_id": "long-term:2026-05-01:QUAL:SE",
                "strategy": "long-term",
                "report_date": "2026-05-01",
                "ticker": "QUAL",
                "name": "Quality AB",
                "country": "SE",
                "segment": "first_north",
                "score": 25.0,
                "entry": {"price": 10.0, "currency": "SEK"},
                "reasons": ["Quality small-cap candidate", "Positive operating margin (16.0%)"],
                "risks": [],
                "data_quality": "partial",
                "long_term_conviction": {"bucket": "Quality small-cap candidate"},
                "report_url": "../reports/long-term/2026-05-01.html",
                "outcomes": {
                    "1d": {"status": "priced", "return_pct": 4.0},
                    "5d": {"status": "not_due", "return_pct": None},
                    "20d": {"status": "not_due", "return_pct": None},
                    "60d": {"status": "not_due", "return_pct": None},
                },
            },
            {
                "pick_id": "long-term:2026-05-01:SPEC:SE",
                "strategy": "long-term",
                "report_date": "2026-05-01",
                "ticker": "SPEC",
                "name": "Speculative AB",
                "country": "SE",
                "segment": "first_north",
                "score": -5.0,
                "entry": {"price": 5.0, "currency": "SEK"},
                "reasons": ["Speculative small-cap monitor"],
                "risks": ["Missing valuation data", "No profitability signal"],
                "data_quality": "thin",
                "long_term_conviction": {"bucket": "Speculative small-cap monitor"},
                "report_url": "../reports/long-term/2026-05-01.html",
                "outcomes": {
                    "1d": {"status": "priced", "return_pct": -3.0},
                    "5d": {"status": "not_due", "return_pct": None},
                    "20d": {"status": "not_due", "return_pct": None},
                    "60d": {"status": "not_due", "return_pct": None},
                },
            },
        ],
        "market_snapshots": {},
    }

    rendered = render_scorecard_markdown(ledger, generated_at="2026-05-02 08:00 EEST")

    assert "Bucket: Quality small-cap candidate" in rendered
    assert "Bucket: Speculative small-cap monitor" in rendered
    assert "Quality: Positive operating margin" in rendered
    assert "Proof gap: Missing valuation data" in rendered
    assert "Proof gap: No profitability signal" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_performance.py::test_long_term_performance_review_includes_quality_bucket_signals -q
```

Expected: fail because `_signal_summaries()` does not classify quality and proof-gap signals separately.

- [ ] **Step 3: Add helper functions in `performance.py`**

Add below `_signal_summaries()` in `src/investmentagent/performance.py`:

```python
def _long_term_quality_signals(pick: dict[str, Any]) -> list[str]:
    if pick.get("strategy") != "long-term":
        return []
    signals: list[str] = []
    conviction = pick.get("long_term_conviction")
    if conviction and conviction.get("bucket"):
        signals.append(f"quality_bucket:{conviction['bucket']}")
    for reason in pick.get("reasons", []):
        normalized = str(reason)
        if normalized.startswith("Positive operating margin"):
            signals.append("quality:positive operating margin")
        elif normalized.startswith("Revenue growth"):
            signals.append("quality:revenue growth")
        elif normalized in {
            "Conservative balance sheet",
            "Conservative debt/equity",
            "Net cash balance sheet",
        }:
            signals.append("quality:conservative balance sheet")
        elif normalized == "Attractive valuation support":
            signals.append("quality:attractive valuation")
        elif normalized == "Business description available":
            signals.append("quality:business description available")
    for risk in pick.get("risks", []):
        normalized = str(risk)
        if normalized in {
            "Missing valuation data",
            "No profitability signal",
            "No growth signal",
            "Negative operating margin",
            "High debt/equity",
            "Thin liquidity",
            "Only live-market support",
            "Thin data quality",
        }:
            signals.append(f"proof_gap:{normalized.lower()}")
    return signals
```

- [ ] **Step 4: Add quality signals to `_signal_summaries()`**

Inside `_signal_summaries()`, after the existing conviction bucket append, add:

```python
        signals.extend(_long_term_quality_signals(pick))
```

- [ ] **Step 5: Update `_humanize_signal()`**

In `src/investmentagent/performance.py`, update `_humanize_signal()` so it handles the new prefixes:

```python
    if prefix == "quality_bucket":
        return f"Bucket: {value}"
    if prefix == "quality":
        return f"Quality: {value.title()}"
    if prefix == "proof_gap":
        return f"Proof gap: {value.title()}"
```

Keep the existing prefix cases for `country`, `segment`, `strategy`, `reason`, and `bucket`.

- [ ] **Step 6: Run performance test**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_performance.py::test_long_term_performance_review_includes_quality_bucket_signals -q
```

Expected: `1 passed`.

- [ ] **Step 7: Run full performance tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_performance.py -q
```

Expected: all performance tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: review long-term quality signals"
```

## Task 5: End-To-End Verification And Report Comparison

**Files:**
- Modify only if tests expose required fixes.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Generate a fixture long-term report smoke sample**

Run:

```bash
mkdir -p /private/tmp/investmentagent-long-term-quality-smoke
/private/tmp/investmentagent-venv/bin/investmentagent watchlist \
  --provider fixture \
  --strategy long-term \
  --limit 3 \
  --save /private/tmp/investmentagent-long-term-quality-smoke/long-term.md \
  --save /private/tmp/investmentagent-long-term-quality-smoke/long-term.json
```

Expected: command exits `0` and both files are created.

- [ ] **Step 3: Inspect report buckets**

Run:

```bash
rg "Bucket:|Thesis:|Proof gap|Quality small-cap|Speculative small-cap|Insufficient evidence" /private/tmp/investmentagent-long-term-quality-smoke/long-term.md
```

Expected: output includes at least one `Bucket:` line using one of the new bucket names.

- [ ] **Step 4: Verify JSON payload includes long-term conviction**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m json.tool /private/tmp/investmentagent-long-term-quality-smoke/long-term.json >/private/tmp/investmentagent-long-term-quality-smoke/pretty.json
rg '"long_term_conviction"|"bucket"|"thesis"' /private/tmp/investmentagent-long-term-quality-smoke/pretty.json
```

Expected: JSON contains `long_term_conviction`, `bucket`, and `thesis`.

- [ ] **Step 5: Check workflow tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_daily_public_workflow.py -q
```

Expected: all workflow tests pass.

- [ ] **Step 6: Commit any smoke-test-driven fixes**

If Steps 1-5 required code changes, commit them:

```bash
git add src/investmentagent tests
git commit -m "fix: stabilize long-term quality report output"
```

If no changes were needed, do not create an empty commit.

- [ ] **Step 7: Final status check**

Run:

```bash
git status --short --branch
git log --oneline -5
```

Expected: branch contains the implementation commits and the worktree is clean.

## Self-Review

Spec coverage:

- Long-term quality layer: Task 1 and Task 2.
- First North remains interesting: Task 1 and Task 2 tests explicitly use First North quality and speculative cases.
- Durable evidence boosts: Task 1 implements profitability, growth, balance sheet, valuation, profile, and liquidity signals.
- Proof penalties: Task 1 implements missing valuation, no profitability, no growth, negative margin, high debt, thin liquidity, live-only support, and thin data quality.
- Report buckets and thesis text: Task 3.
- Performance-led learning: Task 4.
- No new paid data sources, CLI flags, or workflow replacement: preserved by file structure and Task 5 workflow verification.

Placeholder scan:

- No placeholder markers or open-ended deferred-work instructions.
- Code snippets define the functions and tests they reference.
- Every command has an expected result.

Type consistency:

- `LongTermQualityBucket` values are strings used by reports and performance.
- `LongTermQualityProfile` fields are used consistently by `reports.py` and `renderers.py`.
- Performance signal prefixes are defined and humanized in the same task.
