import json

import pytest

from openclaw.models import (
    Company,
    CompanyResearch,
    DataQuality,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)
from openclaw.providers import FixtureResearchProvider
from openclaw.renderers import render_deep_dive_text, render_watchlist_json, render_watchlist_text
from openclaw.reports import build_deep_dive, build_watchlist


class FakeResearchProvider:
    def __init__(self, research: tuple[CompanyResearch, ...]) -> None:
        self._research_by_ticker = {item.company.ticker: item for item in research}
        self._companies = [item.company for item in research]

    def list_companies(
        self, countries: tuple[str, ...], include_first_north: bool
    ) -> list[Company]:
        return self._companies

    def get_research(self, ticker: str) -> CompanyResearch:
        return self._research_by_ticker[ticker]


def make_research(ticker: str, *, pe_ratio: float | None = 10.0) -> CompanyResearch:
    company = Company(
        name=f"{ticker} AB",
        ticker=ticker,
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        sector="Industrials",
        market_cap_eur_m=200,
    )
    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=1.0,
        net_cash_eur_m=5.0,
        data_quality=DataQuality.GOOD,
    )
    return CompanyResearch(company=company, financials=financials, data_quality=DataQuality.GOOD)


def test_build_watchlist_returns_ranked_items_by_score():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=3, include_first_north=True
    )

    assert len(items) == 3
    assert [item.rank for item in items] == [1, 2, 3]
    assert items[0].score.total >= items[1].score.total


def test_build_watchlist_rejects_invalid_limit():
    with pytest.raises(ValueError, match="limit must be at least 1"):
        build_watchlist(
            FixtureResearchProvider(),
            countries=("SE", "FI"),
            limit=0,
            include_first_north=True,
        )


def test_build_watchlist_sorts_equal_scores_by_ticker():
    provider = FakeResearchProvider((make_research("BBB"), make_research("AAA")))

    items = build_watchlist(provider, countries=("SE",), limit=2, include_first_north=True)

    assert [item.research.company.ticker for item in items] == ["AAA", "BBB"]


def test_build_deep_dive_includes_manual_checks_and_thesis():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    assert report.research.company.ticker == "FREEM"
    assert report.why_it_appeared
    assert report.valuation_view
    assert report.bull_case
    assert report.base_case
    assert report.bear_case
    assert report.next_manual_checks

    valuation_text = " ".join(report.valuation_view)
    assert "P/E" in valuation_text
    assert "Price/book" in valuation_text
    assert (
        "Net cash" in valuation_text
        or "Net debt" in valuation_text
        or "unavailable" in valuation_text
    )

    manual_checks_text = " ".join(report.next_manual_checks)
    for required_text in (
        "annual",
        "interim",
        "insider",
        "ownership",
        "liquidity",
        "bid/ask",
        "Nordic",
        "peer",
    ):
        assert required_text in manual_checks_text


def test_build_deep_dive_treats_negative_pe_as_not_meaningful():
    provider = FakeResearchProvider((make_research("NEG", pe_ratio=-5.0),))

    report = build_deep_dive(provider, "NEG")

    pe_text = next(item for item in report.valuation_view if "P/E" in item)
    assert "-5" not in pe_text
    assert "unavailable" in pe_text or "not meaningful" in pe_text


def test_render_watchlist_text_includes_rank_score_risks_and_links():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True)

    output = render_watchlist_text(items)

    assert "#1" in output
    assert "Score:" in output
    assert "Risks:" in output
    assert "Evidence:" in output
    assert "Not financial advice" in output


def test_render_watchlist_json_is_machine_readable():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True)

    payload = json.loads(render_watchlist_json(items))

    assert payload["disclaimer"].startswith("Research triage")
    assert payload["items"][0]["rank"] == 1
    assert "evidence" in payload["items"][0]


def test_render_watchlist_json_normalizes_non_finite_floats():
    company = Company(
        name="Nanotech AB",
        ticker="NAN",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(price=float("nan"), data_quality=DataQuality.GOOD),
            data_quality=DataQuality.GOOD,
        ),
        score=ScoreBreakdown(
            value=float("inf"),
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=float("-inf"),
        ),
    )

    output = render_watchlist_json([item])

    assert "NaN" not in output
    assert "Infinity" not in output
    payload = json.loads(output)
    assert payload["items"][0]["financials"]["price"] is None
    assert payload["items"][0]["score"]["value"] is None
    assert payload["items"][0]["score"]["total"] is None


def test_render_deep_dive_text_includes_thesis_sections():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    output = render_deep_dive_text(report)

    assert "Bull case" in output
    assert "Base case" in output
    assert "Bear case" in output
    assert "Next manual checks" in output
