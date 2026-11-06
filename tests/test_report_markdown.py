"""Public idea reports: compared layout, negative evidence and static-site safety."""
import re

import pytest

from investmentagent.models import (
    Company, CompanyResearch, DataQuality, Evidence, FinancialSnapshot, ListingSegment,
    ScoreBreakdown, SourceCheck, WatchlistItem,
)
from investmentagent.renderers import render_watchlist_report_markdown
from investmentagent.report_comparisons import compare_ideas, comparison_rows


def _item(index, *, rank, country="SE", segment=ListingSegment.MAIN_MARKET, pe=10.0, margin=10.0,
          debt=0.5, liquidity=500_000.0, one_year=5.0, quality=DataQuality.PARTIAL, risks=(),
          warnings=("partial data quality",), score=50.0):
    company = Company(
        name=f"Company {index}", ticker=f"C{index:02d}", country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki", segment=segment,
        isin=f"{country}{index:010d}", market_cap_eur_m=100.0 + index,
        currency="SEK" if country == "SE" else "EUR",
        business_description=f"Company {index} makes things.",
    )
    financials = FinancialSnapshot(
        pe_ratio=pe, price_to_book=1.0 + index / 10, operating_margin_pct=margin,
        revenue_growth_pct=float(index), debt_to_equity=debt, average_daily_value_eur=liquidity,
        one_year_return_pct=one_year, data_quality=quality,
    )
    research = CompanyResearch(company=company, financials=financials, risks=risks, data_quality=quality,
                               evidence=(Evidence("Source", "https://example.invalid/", "fixture"),))
    return WatchlistItem(rank=rank, research=research, score=ScoreBreakdown(
        value=20.0, discovery=5.0, catalyst=max(score - 18.0, 0.0), risk_penalty=0.0,
        data_quality_penalty=7.0, total=score, reasons=("low P/E (10)",), warnings=warnings))


def _universe():
    items = [_item(i, rank=i + 1, pe=8.0 + i, margin=20.0 - i, score=80.0 - i) for i in range(12)]
    items[1] = _item(1, rank=2, pe=-4.0, margin=-3.0, debt=2.5, liquidity=20_000.0, one_year=-40.0,
                     risks=("Refinancing need",), warnings=("high debt/equity", "partial data quality"),
                     score=79.0)
    return items


METADATA = {
    "generated_at": "2026-11-06T06:21:00+00:00", "strategy": "trading", "limit": 3,
    "min_country_counts": {"FI": 3},
    "evaluation": {"run_id": "evaluation-abc", "scoring_model_version": "nordic-ranking-v1",
                   "decision_at": "2026-11-06T06:21:00Z"},
}
CHECKS = [SourceCheck("fixture", "ok", "12 companies")]


def _render(items, selected=3, metadata=METADATA, strategy="trading"):
    rows = comparison_rows(items, strategy=strategy)
    comparison = compare_ideas(rows, [row.company_id for row in rows[:selected]], strategy=strategy,
                               public_limit=selected, decision_at=metadata["evaluation"]["decision_at"],
                               cache_recorded=False, source_universe_size=40)
    return render_watchlist_report_markdown(items[:selected], metadata, CHECKS, comparison)


def test_compared_report_leads_with_summary_and_moves_diagnostics_last():
    text = _render(_universe())
    assert text.index("## Summary") < text.index("## Watchlist") < text.index("## Run Diagnostics")
    assert text.index("## Run Diagnostics") < text.index("### Metadata")
    assert "**Eligible universe (X):** 12 companies (SE 12)" in text
    assert "| 1 | [Company 0 (C00)](#idea-1) | SE main market | 80 | 100th |" in text
    assert text.count('<a id="idea-') == 3


def test_negative_pe_is_not_meaningful_and_listed_as_a_risk():
    text = _render(_universe())
    section = text[text.index('<a id="idea-2">'):text.index('<a id="idea-3">')]
    assert "| P/E | Not meaningful (zero or negative earnings) |" in section
    assert "P/E is not meaningful: zero or negative earnings" in section
    assert "High debt/equity (model warning)." in section
    assert "1 stated risk(s) cost 3 risk-penalty points: Refinancing need." in section
    assert "Partial data quality (7-point data-quality penalty)." in section
    assert "One-year share-price return of -40.0%" in section
    assert "Less traded than" in section and "listing peers" in section
    assert "None provided." not in section.split("### Reasons")[0]


def test_lower_is_better_peer_wording_and_denominators():
    text = _render(_universe())
    first = text[text.index('<a id="idea-1">'):text.index('<a id="idea-2">')]
    # P/E 8 is below every positive peer multiple (10 to 19); the loss-maker is excluded.
    assert "| P/E | 8.00 | median 14.5; cheaper than 100% · n=10/11 (1 not meaningful) |" in first
    assert "| Market cap (EUR m) | 100 | median 106; larger than 0% · n=11/11 |" in first
    assert "| Avg. daily traded value (EUR) | 500k |" in first


def test_every_metric_row_reports_provenance_or_unavailable():
    items = _universe()[:4]  # 3 peers: below the 5-observation minimum
    text = _render(items)
    assert "Unavailable: fewer than 5 comparable peers · n=3/3" in text
    assert "(peers unavailable)" in text


def test_country_minimum_inclusion_is_explained():
    items = _universe()
    finn = _item(30, rank=3, country="FI", pe=9.0, score=20.0)
    universe = [items[0], items[2], finn, *items[3:]]
    universe = [type(item)(rank=index + 1, research=item.research, score=item.score)
                for index, item in enumerate(universe)]
    text = _render(universe)
    assert "included by the minimum-country rule (FI:3). Without it the company would rank 12 of 12" in text


def test_empty_trading_report_explains_no_candidates():
    comparison = compare_ideas([], [], strategy="trading", public_limit=10,
                               decision_at="2026-11-06T06:20:55Z", cache_recorded=True,
                               source_universe_size=935)
    text = render_watchlist_report_markdown([], METADATA, CHECKS, comparison)
    assert "**No trading candidates at decision time.** None of the 935 listed companies screened" in text
    assert "not a pipeline failure" in text
    assert "## Summary" not in text and "## Run Diagnostics" in text


def test_comparison_must_describe_the_rendered_items():
    items = _universe()
    rows = comparison_rows(items, strategy="trading")
    comparison = compare_ideas(rows, [rows[1].company_id], strategy="trading", public_limit=1,
                               decision_at="2026-11-06T06:21:00Z", cache_recorded=False)
    with pytest.raises(ValueError, match="does not describe"):
        render_watchlist_report_markdown(items[:1], METADATA, CHECKS, comparison)


def test_legacy_layout_is_unchanged_without_a_comparison():
    items = _universe()[:2]
    text = render_watchlist_report_markdown(items, METADATA, CHECKS)
    assert text.splitlines()[:7] == [
        "# InvestmentAgent Trading Ideas", "", "> Research triage only. Not financial advice.", "",
        "_Short-term setup candidates based on momentum, liquidity, and catalysts._", "", "## Metadata"]
    assert "## Summary" not in text and "<details" not in text
    notice = render_watchlist_report_markdown(items, METADATA, CHECKS, comparison_error="ValueError")
    assert "peer comparisons are unavailable for this run (ValueError)" in notice


@pytest.mark.parametrize("strategy", ["trading", "long-term"])
def test_static_output_is_safe_for_the_jekyll_build(strategy):
    metadata = {**METADATA, "strategy": strategy}
    text = _render(_universe(), metadata=metadata, strategy=strategy)
    assert "{{" not in text and "{%" not in text
    assert set(re.findall(r"</?([A-Za-z][\w-]*)", text)) <= {"a", "details", "summary"}
    assert text.count("<details") == text.count("</details>")
    links = re.findall(r"\]\(([^)]+)\)", text)
    relative = [link for link in links if not link.startswith(("http", "#"))]
    assert set(relative) == {"../../performance/", "../../performance/#metric-definitions"}
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', text))
    assert {link[1:] for link in links if link.startswith("#")} <= anchors
