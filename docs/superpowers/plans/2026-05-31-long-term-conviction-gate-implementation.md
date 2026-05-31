# Long-Term Conviction Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the long-term watchlist selective by gating high-conviction ideas, deriving conservative valuation proxies from existing data, and reporting lower-conviction names separately.

**Architecture:** Extend the existing long-term quality module with valuation proxy and gate-tier assessment, then consume those results in scoring, rendering, and performance review. Keep the public CLI and daily workflow unchanged; `--strategy long-term` remains the rollout path.

**Tech Stack:** Python 3.12+, dataclasses, Typer CLI, pytest, existing InvestmentAgent report/render/performance modules.

---

## File Structure

- Modify `src/investmentagent/models.py`
  - Add optional financial fields needed for valuation proxies: `revenue_eur_m`, `book_value_eur_m`, and `net_income_eur_m`.
- Modify `src/investmentagent/fundamentals.py`
  - Preserve these fields when merging enriched financial snapshots.
- Modify `src/investmentagent/long_term_quality.py`
  - Add `ValuationSupport`, `LongTermGateTier`, `LongTermGateDecision`, valuation proxy helpers, durable-anchor counting, severe proof-gap detection, and `assess_long_term_gate()`.
- Modify `src/investmentagent/reports.py`
  - Add gate tier/reason signals to long-term scores and apply the conviction gate after ranking for long-term reports.
- Modify `src/investmentagent/renderers.py`
  - Include gate decision in JSON payload.
  - Render long-term markdown by tier, including a "No high-conviction ideas today" message when needed.
  - Use valuation support details in the valuation component.
- Modify `src/investmentagent/performance.py`
  - Persist gate decision fields and summarize performance by gate tier, durable anchor count, severe proof-gap count, and valuation proxy type.
- Modify tests:
  - `tests/test_models.py`
  - `tests/test_fundamentals.py`
  - `tests/test_long_term_quality.py`
  - `tests/test_reports.py`
  - `tests/test_performance.py`
  - `tests/test_daily_public_workflow.py`

## Task 1: Add Financial Fields For Valuation Proxies

**Files:**
- Modify: `src/investmentagent/models.py`
- Modify: `src/investmentagent/fundamentals.py`
- Test: `tests/test_models.py`
- Test: `tests/test_fundamentals.py`

- [ ] **Step 1: Write failing model test**

Append this test to `tests/test_models.py`:

```python
def test_financial_snapshot_accepts_valuation_proxy_inputs():
    snapshot = FinancialSnapshot(
        revenue_eur_m=120.0,
        book_value_eur_m=80.0,
        net_income_eur_m=12.0,
    )

    assert snapshot.revenue_eur_m == 120.0
    assert snapshot.book_value_eur_m == 80.0
    assert snapshot.net_income_eur_m == 12.0
```

- [ ] **Step 2: Run model test to verify it fails**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_models.py::test_financial_snapshot_accepts_valuation_proxy_inputs -q
```

Expected: fails with `TypeError: FinancialSnapshot.__init__() got an unexpected keyword argument`.

- [ ] **Step 3: Add optional fields to `FinancialSnapshot`**

In `src/investmentagent/models.py`, update `FinancialSnapshot` to include:

```python
    revenue_eur_m: float | None = None
    book_value_eur_m: float | None = None
    net_income_eur_m: float | None = None
```

Place them after `ev_to_ebit` and before `net_cash_eur_m`, so valuation inputs stay grouped.

- [ ] **Step 4: Run model test to verify it passes**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_models.py::test_financial_snapshot_accepts_valuation_proxy_inputs -q
```

Expected: 1 passed.

- [ ] **Step 5: Write failing fundamentals merge test**

Add this test near `test_enriched_provider_merges_fundamentals_into_research()` in `tests/test_fundamentals.py`:

```python
def test_enriched_provider_merges_valuation_proxy_inputs():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            book_value_eur_m=80.0,
            net_income_eur_m=12.0,
            data_quality=DataQuality.PARTIAL,
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.financials.revenue_eur_m == 120.0
    assert research.financials.book_value_eur_m == 80.0
    assert research.financials.net_income_eur_m == 12.0
```

- [ ] **Step 6: Run fundamentals test to verify it fails**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_fundamentals.py::test_enriched_research_preserves_valuation_proxy_inputs -q
```

Expected: fails because merge code does not preserve the new fields.

- [ ] **Step 7: Update financial merge code**

No custom merge code should be needed beyond Task 1 because `_merge_financials()` iterates over `FinancialSnapshot.__dataclass_fields__` and already merges every non-preserved field from enrichment into missing base fields. If the test still fails, inspect `_merge_financials()` and confirm that `revenue_eur_m`, `book_value_eur_m`, and `net_income_eur_m` are not accidentally added to `preserved_fields`.

- [ ] **Step 8: Run task tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_models.py tests/test_fundamentals.py -q
```

Expected: all tests in both files pass.

- [ ] **Step 9: Commit Task 1**

Run:

```bash
git add src/investmentagent/models.py src/investmentagent/fundamentals.py tests/test_models.py tests/test_fundamentals.py
git commit -m "feat: add valuation proxy financial fields"
```

## Task 2: Add Valuation Support And Conviction Gate Assessment

**Files:**
- Modify: `src/investmentagent/long_term_quality.py`
- Test: `tests/test_long_term_quality.py`

- [ ] **Step 1: Write failing valuation proxy tests**

Append these tests to `tests/test_long_term_quality.py`:

```python
from investmentagent.long_term_quality import (
    LongTermGateTier,
    assess_long_term_gate,
    assess_valuation_support,
)


def test_valuation_support_uses_market_cap_to_sales_proxy():
    research = make_research(
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
    )
    research = CompanyResearch(
        company=Company(
            name=research.company.name,
            ticker=research.company.ticker,
            country=research.company.country,
            exchange=research.company.exchange,
            segment=research.company.segment,
            sector=research.company.sector,
            market_cap_eur_m=180.0,
            currency=research.company.currency,
            business_description=research.company.business_description,
        ),
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            debt_to_equity=0.2,
            revenue_growth_pct=10.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    support = assess_valuation_support(research)

    assert support.has_support is True
    assert support.is_attractive is True
    assert support.primary_kind == "market_cap_to_sales"
    assert support.primary_value == 1.5
    assert "Market cap/sales is 1.5x" in support.summary


def test_high_quality_company_with_proxy_passes_high_conviction_gate():
    research = make_research(
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=12.0,
    )
    research = CompanyResearch(
        company=Company(
            name=research.company.name,
            ticker=research.company.ticker,
            country=research.company.country,
            exchange=research.company.exchange,
            segment=research.company.segment,
            sector=research.company.sector,
            market_cap_eur_m=180.0,
            currency=research.company.currency,
            business_description=research.company.business_description,
        ),
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            net_cash_eur_m=12.0,
            debt_to_equity=0.2,
            revenue_growth_pct=10.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    decision = assess_long_term_gate(research)

    assert decision.tier == LongTermGateTier.HIGH_CONVICTION
    assert decision.durable_anchor_count >= 4
    assert decision.severe_proof_gap_count == 0
    assert "valuation support available" in decision.reasons


def test_negative_margin_company_is_demoted_by_gate():
    decision = assess_long_term_gate(
        make_research(
            operating_margin_pct=-8.0,
            revenue_growth_pct=20.0,
            pe_ratio=8.0,
            price_to_book=1.0,
            average_daily_value_eur=250_000,
        )
    )

    assert decision.tier != LongTermGateTier.HIGH_CONVICTION
    assert "negative operating margin" in decision.blockers
```

- [ ] **Step 2: Run valuation/gate tests to verify they fail**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_long_term_quality.py::test_valuation_support_uses_market_cap_to_sales_proxy tests/test_long_term_quality.py::test_high_quality_company_with_proxy_passes_high_conviction_gate tests/test_long_term_quality.py::test_negative_margin_company_is_demoted_by_gate -q
```

Expected: import failures for missing `LongTermGateTier`, `assess_long_term_gate`, and `assess_valuation_support`.

- [ ] **Step 3: Add dataclasses/enums to `long_term_quality.py`**

Add these definitions after `LongTermQualityProfile`:

```python
class LongTermGateTier(str, Enum):
    HIGH_CONVICTION = "High-conviction candidate"
    FUNDAMENTAL_WATCHLIST = "Fundamental watchlist"
    SPECULATIVE_MONITOR = "Speculative monitor"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


@dataclass(frozen=True)
class ValuationSupport:
    has_support: bool
    is_attractive: bool
    primary_kind: str | None
    primary_value: float | None
    summary: str


@dataclass(frozen=True)
class LongTermGateDecision:
    tier: LongTermGateTier
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    durable_anchor_count: int
    severe_proof_gap_count: int
    valuation: ValuationSupport
```

- [ ] **Step 4: Implement valuation proxy helpers**

Add these helpers in `long_term_quality.py` near `_has_attractive_valuation()`:

```python
def assess_valuation_support(research: CompanyResearch) -> ValuationSupport:
    financials = research.financials
    direct_metrics = (
        ("pe_ratio", financials.pe_ratio, 14.0, "P/E"),
        ("price_to_book", financials.price_to_book, 1.5, "Price/book"),
        ("ev_to_ebit", financials.ev_to_ebit, 12.0, "EV/EBIT"),
    )
    for kind, value, threshold, label in direct_metrics:
        if value is not None and value > 0:
            attractive = value <= threshold
            return ValuationSupport(
                has_support=True,
                is_attractive=attractive,
                primary_kind=kind,
                primary_value=round(value, 2),
                summary=f"{label} is {value:g}.",
            )

    proxy = _valuation_proxy(research)
    if proxy is not None:
        return proxy

    return ValuationSupport(
        has_support=False,
        is_attractive=False,
        primary_kind=None,
        primary_value=None,
        summary="No valuation metric or proxy is available.",
    )


def _valuation_proxy(research: CompanyResearch) -> ValuationSupport | None:
    company = research.company
    financials = research.financials
    market_cap = company.market_cap_eur_m
    if market_cap is None or market_cap <= 0:
        return None

    if financials.revenue_eur_m is not None and financials.revenue_eur_m > 0:
        value = round(market_cap / financials.revenue_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value <= 2.0,
            primary_kind="market_cap_to_sales",
            primary_value=value,
            summary=f"Market cap/sales is {value:g}x.",
        )
    if financials.book_value_eur_m is not None and financials.book_value_eur_m > 0:
        value = round(market_cap / financials.book_value_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value <= 1.5,
            primary_kind="market_cap_to_book",
            primary_value=value,
            summary=f"Market cap/book value is {value:g}x.",
        )
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        value = round((financials.net_cash_eur_m / market_cap) * 100, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value >= 20.0,
            primary_kind="net_cash_to_market_cap",
            primary_value=value,
            summary=f"Net cash equals {value:g}% of market cap.",
        )
    if financials.net_income_eur_m is not None and financials.net_income_eur_m > 0:
        pe_ratio = round(market_cap / financials.net_income_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=pe_ratio <= 14.0,
            primary_kind="earnings_yield_pe",
            primary_value=pe_ratio,
            summary=f"Implied P/E is {pe_ratio:g}.",
        )
    return None
```

- [ ] **Step 5: Update `_has_attractive_valuation()`**

Replace the body with:

```python
def _has_attractive_valuation(research: CompanyResearch) -> bool:
    return assess_valuation_support(research).is_attractive
```

- [ ] **Step 6: Add gate assessment helpers**

Add these functions to `long_term_quality.py`:

```python
SEVERE_PROOF_GAPS = {
    "No profitability signal",
    "Negative operating margin",
    "High debt/equity",
    "Thin data quality",
    "Missing business description",
    "Missing liquidity data",
}


def assess_long_term_gate(research: CompanyResearch) -> LongTermGateDecision:
    quality = assess_long_term_quality(research)
    valuation = assess_valuation_support(research)
    durable_anchors = _durable_anchors(research, valuation)
    severe_blockers = tuple(
        gap for gap in quality.proof_gaps if gap in SEVERE_PROOF_GAPS
    )
    blockers = list(severe_blockers)
    reasons = list(durable_anchors)

    if valuation.has_support:
        reasons.append("valuation support available")
    else:
        blockers.append("missing valuation support")

    if quality.bucket == LongTermQualityBucket.QUALITY_SMALL_CAP:
        tier = LongTermGateTier.HIGH_CONVICTION
    elif (
        quality.bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST
        and len(durable_anchors) >= 3
    ):
        tier = LongTermGateTier.HIGH_CONVICTION
    elif quality.bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST:
        tier = LongTermGateTier.FUNDAMENTAL_WATCHLIST
    elif quality.bucket == LongTermQualityBucket.SPECULATIVE_MONITOR:
        tier = LongTermGateTier.SPECULATIVE_MONITOR
    else:
        tier = LongTermGateTier.INSUFFICIENT_EVIDENCE

    if tier == LongTermGateTier.HIGH_CONVICTION and (
        blockers or len(durable_anchors) < 2 or not valuation.has_support
    ):
        tier = LongTermGateTier.FUNDAMENTAL_WATCHLIST

    return LongTermGateDecision(
        tier=tier,
        reasons=tuple(dict.fromkeys(reasons)),
        blockers=tuple(dict.fromkeys(blockers)),
        durable_anchor_count=len(durable_anchors),
        severe_proof_gap_count=len(severe_blockers),
        valuation=valuation,
    )


def _durable_anchors(
    research: CompanyResearch, valuation: ValuationSupport
) -> tuple[str, ...]:
    financials = research.financials
    anchors: list[str] = []
    if financials.operating_margin_pct is not None and financials.operating_margin_pct > 0:
        anchors.append("positive operating margin")
    if financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0:
        anchors.append("revenue growth")
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        anchors.append("net cash balance sheet")
    if financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        anchors.append("conservative balance sheet")
    if financials.average_daily_value_eur is not None and financials.average_daily_value_eur >= 100_000:
        anchors.append("adequate liquidity")
    if valuation.is_attractive:
        anchors.append("attractive valuation support")
    elif valuation.has_support:
        anchors.append("valuation data available")
    return tuple(dict.fromkeys(anchors))
```

- [ ] **Step 7: Run long-term quality tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_long_term_quality.py -q
```

Expected: all long-term quality tests pass.

- [ ] **Step 8: Commit Task 2**

Run:

```bash
git add src/investmentagent/long_term_quality.py tests/test_long_term_quality.py
git commit -m "feat: assess long-term conviction gate"
```

## Task 3: Apply Gate To Long-Term Ranking And Report Payloads

**Files:**
- Modify: `src/investmentagent/reports.py`
- Modify: `src/investmentagent/renderers.py`
- Test: `tests/test_reports.py`

- [ ] **Step 1: Write failing ranking gate test**

Add this test to `tests/test_reports.py` near the existing long-term strategy tests:

```python
def test_long_term_watchlist_demotes_insufficient_evidence_below_limit():
    quality = CompanyResearch(
        company=Company(
            name="Quality Gate AB",
            ticker="QGATE",
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=ListingSegment.FIRST_NORTH,
            sector="Software",
            market_cap_eur_m=180,
            currency="SEK",
            business_description="Quality Gate sells profitable workflow software.",
        ),
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            net_cash_eur_m=12.0,
            debt_to_equity=0.2,
            revenue_growth_pct=10.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=250000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )
    weak = CompanyResearch(
        company=Company(
            name="Weak Gate AB",
            ticker="WGATE",
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=ListingSegment.FIRST_NORTH,
            sector="Technology",
            market_cap_eur_m=80,
            currency="SEK",
        ),
        financials=FinancialSnapshot(data_quality=DataQuality.THIN),
        catalysts=("Strong intraday momentum (+18.0%)", "High live turnover"),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )

    items = build_watchlist(
        FakeResearchProvider((weak, quality)),
        countries=("SE",),
        limit=10,
        include_first_north=True,
        strategy="long-term",
    )

    assert [item.research.company.ticker for item in items] == ["QGATE", "WGATE"]
    assert "Gate tier: High-conviction candidate" in items[0].score.reasons
    assert "Gate tier: Insufficient evidence" in items[1].score.warnings
```

- [ ] **Step 2: Write failing JSON gate payload test**

Add this test near the long-term conviction JSON tests:

```python
def test_render_watchlist_report_json_includes_long_term_gate_payload():
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=Company(
                name="Gate Payload AB",
                ticker="GATE",
                country="SE",
                exchange="Nasdaq First North Growth Market Sweden",
                segment=ListingSegment.FIRST_NORTH,
                sector="Software",
                market_cap_eur_m=180,
                business_description="Gate Payload sells profitable workflow software.",
            ),
            financials=FinancialSnapshot(
                revenue_eur_m=120.0,
                net_cash_eur_m=12.0,
                debt_to_equity=0.2,
                revenue_growth_pct=10.0,
                operating_margin_pct=14.0,
                average_daily_value_eur=250000,
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

    gate = payload["items"][0]["long_term_gate"]
    assert gate["tier"] == "High-conviction candidate"
    assert gate["durable_anchor_count"] >= 4
    assert gate["severe_proof_gap_count"] == 0
    assert gate["valuation"]["primary_kind"] == "market_cap_to_sales"
```

- [ ] **Step 3: Write failing tiered markdown test**

Add this test near the markdown report tests:

```python
def test_render_long_term_report_markdown_groups_by_gate_tier():
    high = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=Company(
                name="High Conviction AB",
                ticker="HIGH",
                country="SE",
                exchange="Nasdaq First North Growth Market Sweden",
                segment=ListingSegment.FIRST_NORTH,
                sector="Software",
                market_cap_eur_m=180,
                business_description="High Conviction sells profitable workflow software.",
            ),
            financials=FinancialSnapshot(
                revenue_eur_m=120.0,
                debt_to_equity=0.2,
                revenue_growth_pct=10.0,
                operating_margin_pct=14.0,
                average_daily_value_eur=250000,
                data_quality=DataQuality.PARTIAL,
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(10, 5, 10, 0, 0, 25),
    )
    monitor = WatchlistItem(
        rank=2,
        research=CompanyResearch(
            company=Company(
                name="Monitor Only AB",
                ticker="MON",
                country="SE",
                exchange="Nasdaq First North Growth Market Sweden",
                segment=ListingSegment.FIRST_NORTH,
                sector="Technology",
                market_cap_eur_m=80,
                business_description="Monitor Only has a readable profile.",
            ),
            financials=FinancialSnapshot(
                debt_to_equity=0.4,
                revenue_growth_pct=4.0,
                average_daily_value_eur=120000,
                data_quality=DataQuality.PARTIAL,
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(0, 5, 0, 0, 4, 1),
    )

    output = render_watchlist_report_markdown(
        [high, monitor],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "## High-Conviction Candidates" in output
    assert "## Fundamental Watchlist" in output or "## Speculative Monitors" in output
    assert output.index("High Conviction AB") < output.index("Monitor Only AB")
```

- [ ] **Step 4: Run report tests to verify failures**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py::test_long_term_watchlist_demotes_insufficient_evidence_below_limit tests/test_reports.py::test_render_watchlist_report_json_includes_long_term_gate_payload tests/test_reports.py::test_render_long_term_report_markdown_groups_by_gate_tier -q
```

Expected: failures because gate tier signals, JSON payload, and tiered markdown are not implemented.

- [ ] **Step 5: Add gate signals to `_long_term_score()`**

In `src/investmentagent/reports.py`, import `assess_long_term_gate` and update `_long_term_score()`:

```python
    gate = assess_long_term_gate(research)
```

Add positive gate reason for high-conviction or watchlist names:

```python
    gate_reasons = (f"Gate tier: {gate.tier.value}",)
```

For `HIGH_CONVICTION` and `FUNDAMENTAL_WATCHLIST`, append `gate_reasons` to reasons. For `SPECULATIVE_MONITOR` and `INSUFFICIENT_EVIDENCE`, append `gate_reasons` to warnings. Keep existing quality reasons and warnings.

- [ ] **Step 6: Apply gate-aware long-term final ordering**

In `src/investmentagent/reports.py`, add a helper:

```python
def _long_term_gate_rank(item: WatchlistItem) -> tuple[int, float, str]:
    gate = assess_long_term_gate(item.research)
    order = {
        "High-conviction candidate": 0,
        "Fundamental watchlist": 1,
        "Speculative monitor": 2,
        "Insufficient evidence": 3,
    }
    return (order[gate.tier.value], -item.score.total, item.research.company.ticker)
```

In `build_watchlist()`, after `_deduplicate_company_ideas(scored_items)`, use normal ranking for all strategies except long-term. For long-term, sort by `_long_term_gate_rank()` before applying `limit` and `min_country_counts`.

- [ ] **Step 7: Add gate payload to renderer JSON**

In `src/investmentagent/renderers.py`, import `assess_long_term_gate`. Add:

```python
def _long_term_gate_payload(item: WatchlistItem) -> dict[str, Any]:
    decision = assess_long_term_gate(item.research)
    return {
        "tier": decision.tier.value,
        "reasons": list(decision.reasons),
        "blockers": list(decision.blockers),
        "durable_anchor_count": decision.durable_anchor_count,
        "severe_proof_gap_count": decision.severe_proof_gap_count,
        "valuation": {
            "has_support": decision.valuation.has_support,
            "is_attractive": decision.valuation.is_attractive,
            "primary_kind": decision.valuation.primary_kind,
            "primary_value": decision.valuation.primary_value,
            "summary": decision.valuation.summary,
        },
    }
```

In `_watchlist_items_payload()`, when `strategy == "long-term"`, add:

```python
            payload["long_term_gate"] = _long_term_gate_payload(item)
```

- [ ] **Step 8: Render tiered long-term markdown**

In `src/investmentagent/renderers.py`, update `_watchlist_markdown_sections()` so long-term reports call a new `_long_term_markdown_sections(items)` helper. That helper should group items by `assess_long_term_gate(item.research).tier` and render headings:

```python
LONG_TERM_TIER_HEADINGS = {
    LongTermGateTier.HIGH_CONVICTION: "High-Conviction Candidates",
    LongTermGateTier.FUNDAMENTAL_WATCHLIST: "Fundamental Watchlist",
    LongTermGateTier.SPECULATIVE_MONITOR: "Speculative Monitors",
    LongTermGateTier.INSUFFICIENT_EVIDENCE: "Insufficient Evidence",
}
```

If no item has `HIGH_CONVICTION`, include:

```markdown
_No high-conviction long-term ideas passed the gate today._
```

Then render each item with the existing item section body.

- [ ] **Step 9: Run report tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_reports.py -q
```

Expected: all report tests pass.

- [ ] **Step 10: Commit Task 3**

Run:

```bash
git add src/investmentagent/reports.py src/investmentagent/renderers.py tests/test_reports.py
git commit -m "feat: gate long-term report candidates"
```

## Task 4: Track Gate Outcomes In Performance

**Files:**
- Modify: `src/investmentagent/performance.py`
- Test: `tests/test_performance.py`

- [ ] **Step 1: Write failing persistence test**

Add this test near the existing long-term performance tests:

```python
def test_performance_ledger_preserves_long_term_gate_payload():
    payload = report_payload(strategy="long-term")
    payload["items"][0]["company"]["ticker"] = "GATE"
    payload["items"][0]["company"]["name"] = "Gate Result AB"
    payload["items"][0]["long_term_gate"] = {
        "tier": "High-conviction candidate",
        "reasons": ["positive operating margin", "valuation support available"],
        "blockers": [],
        "durable_anchor_count": 4,
        "severe_proof_gap_count": 0,
        "valuation": {
            "has_support": True,
            "is_attractive": True,
            "primary_kind": "market_cap_to_sales",
            "primary_value": 1.5,
            "summary": "Market cap/sales is 1.5x.",
        },
    }

    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )

    assert ledger["picks"][0]["long_term_gate"]["tier"] == "High-conviction candidate"
    assert ledger["picks"][0]["long_term_gate"]["durable_anchor_count"] == 4
```

- [ ] **Step 2: Write failing scorecard signal test**

Add:

```python
def test_performance_review_includes_long_term_gate_signals():
    ledger = {
        "schema_version": 1,
        "picks": [
            {
                "pick_id": "long-term:2026-05-01:GATE:SE",
                "strategy": "long-term",
                "report_date": "2026-05-01",
                "ticker": "GATE",
                "name": "Gate Result AB",
                "country": "SE",
                "segment": "first_north",
                "reasons": [],
                "warnings": [],
                "risks": [],
                "data_quality": "partial",
                "long_term_conviction": {"bucket": "Quality small-cap candidate"},
                "long_term_gate": {
                    "tier": "High-conviction candidate",
                    "durable_anchor_count": 4,
                    "severe_proof_gap_count": 0,
                    "valuation": {"primary_kind": "market_cap_to_sales"},
                },
                "report_url": "../reports/long-term/2026-05-01.html",
                "outcomes": {
                    "1d": {"status": "priced", "return_pct": 5.0},
                    "5d": {"status": "not_due", "return_pct": None},
                    "20d": {"status": "not_due", "return_pct": None},
                    "60d": {"status": "not_due", "return_pct": None},
                },
            }
        ],
        "market_snapshots": {},
    }

    rendered = render_scorecard_markdown(ledger, generated_at="2026-05-02 08:00 EEST")

    assert "Gate: High-conviction candidate" in rendered
    assert "Gate durable anchors: 4" in rendered
    assert "Gate severe proof gaps: 0" in rendered
    assert "Valuation proxy: Market cap to sales" in rendered
```

- [ ] **Step 3: Run performance tests to verify failures**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_performance.py::test_performance_ledger_preserves_long_term_gate_payload tests/test_performance.py::test_performance_review_includes_long_term_gate_signals -q
```

Expected: failures because `long_term_gate` is not persisted or summarized.

- [ ] **Step 4: Persist gate payload**

In `src/investmentagent/performance.py`, update `_pick_from_report_item()` after the conviction block:

```python
    gate = item.get("long_term_gate")
    if gate:
        pick["long_term_gate"] = gate
```

- [ ] **Step 5: Add gate signals**

In `_long_term_quality_signals()`, add:

```python
    gate = pick.get("long_term_gate") or {}
    if gate.get("tier"):
        signals.append(f"gate:{gate['tier']}")
    if gate.get("durable_anchor_count") is not None:
        signals.append(f"gate_durable_anchors:{gate['durable_anchor_count']}")
    if gate.get("severe_proof_gap_count") is not None:
        signals.append(f"gate_severe_proof_gaps:{gate['severe_proof_gap_count']}")
    valuation = gate.get("valuation") or {}
    if valuation.get("primary_kind"):
        signals.append(f"valuation_proxy:{valuation['primary_kind']}")
```

In `_humanize_signal()`, add labels:

```python
    if prefix == "gate":
        return f"Gate: {value}"
    if prefix == "gate_durable_anchors":
        return f"Gate durable anchors: {value}"
    if prefix == "gate_severe_proof_gaps":
        return f"Gate severe proof gaps: {value}"
    if prefix == "valuation_proxy":
        return f"Valuation proxy: {_sentence_case_signal_value(value)}"
```

- [ ] **Step 6: Run performance tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_performance.py -q
```

Expected: all performance tests pass.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add src/investmentagent/performance.py tests/test_performance.py
git commit -m "feat: track long-term gate performance"
```

## Task 5: Verify Daily Workflow And Latest Report Behavior

**Files:**
- Modify if needed: `tests/test_daily_public_workflow.py`
- No source change expected unless workflow tests reveal missing behavior.

- [ ] **Step 1: Run workflow tests**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest tests/test_daily_public_workflow.py -q
```

Expected: 3 passed.

- [ ] **Step 2: Run full test suite**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Generate fixture long-term smoke report**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m investmentagent.cli watchlist --provider fixture --strategy long-term --limit 10 --save /private/tmp/investmentagent-conviction-gate/long-term.md --save /private/tmp/investmentagent-conviction-gate/long-term.json
```

Expected: command exits 0, Markdown includes long-term tier headings, JSON contains `long_term_gate` for each item.

- [ ] **Step 4: Inspect smoke artifacts**

Run:

```bash
rg -n "High-Conviction Candidates|No high-conviction|long_term_gate|Gate tier" /private/tmp/investmentagent-conviction-gate
```

Expected: matches in both Markdown and JSON outputs.

- [ ] **Step 5: Commit any workflow/test adjustment**

If Task 5 required changes, commit them:

```bash
git add tests/test_daily_public_workflow.py src/investmentagent
git commit -m "test: verify long-term conviction gate workflow"
```

If there were no changes, do not create an empty commit.

## Task 6: Integrate Back To Main

**Files:**
- No source edits expected.

- [ ] **Step 1: Check final branch status**

Run:

```bash
git status --short --branch
```

Expected: clean branch `codex/long-term-conviction-gate`.

- [ ] **Step 2: Rebase on latest main**

Run:

```bash
git fetch origin main
git rebase origin/main
```

Expected: rebase succeeds.

- [ ] **Step 3: Run full tests after rebase**

Run:

```bash
/private/tmp/investmentagent-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 4: Fast-forward main and push**

From `/Users/vernerisirva1/Documents/Investmentagent`, run:

```bash
git fetch origin main
git merge --ff-only codex/long-term-conviction-gate
git push origin main
```

Expected: local `main` fast-forwards and pushes directly to GitHub.
