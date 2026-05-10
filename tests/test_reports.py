import json

import pytest

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)
from investmentagent.providers import FixtureResearchProvider
from investmentagent.renderers import (
    render_deep_dive_json,
    render_deep_dive_text,
    render_watchlist_json,
    render_watchlist_text,
)
from investmentagent.reports import build_deep_dive, build_watchlist


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


class MissingResearchProvider(FakeResearchProvider):
    def get_research(self, ticker: str) -> CompanyResearch:
        if ticker == "BROKEN":
            raise RuntimeError("source fetch failed")
        return super().get_research(ticker)


def make_research(
    ticker: str,
    *,
    pe_ratio: float | None = 10.0,
    price_to_book: float | None = 1.0,
    net_cash_eur_m: float | None = 5.0,
    price: float | None = None,
    currency: str | None = None,
    catalysts=(),
    risks=(),
    segment: ListingSegment = ListingSegment.MAIN_MARKET,
    data_quality: DataQuality = DataQuality.GOOD,
    evidence=(),
) -> CompanyResearch:
    company = Company(
        name=f"{ticker} AB",
        ticker=ticker,
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=segment,
        sector="Industrials",
        market_cap_eur_m=200,
    )
    financials = FinancialSnapshot(
        price=price,
        currency=currency,
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        net_cash_eur_m=net_cash_eur_m,
        data_quality=data_quality,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        catalysts=catalysts,
        risks=risks,
        evidence=evidence,
        data_quality=data_quality,
    )


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


def test_build_watchlist_skips_missing_research_rows():
    provider = MissingResearchProvider(
        (make_research("BROKEN"), make_research("READY"))
    )

    items = build_watchlist(provider, countries=("SE",), limit=2, include_first_north=True)

    assert [item.research.company.ticker for item in items] == ["READY"]


def test_build_watchlist_filters_market_cap_and_sector():
    items = build_watchlist(
        FixtureResearchProvider(),
        countries=("SE", "FI"),
        limit=10,
        include_first_north=True,
        min_market_cap=250,
        max_market_cap=350,
        sector="Gaming",
    )

    assert [item.research.company.ticker for item in items] == ["REMEDY"]


def test_balanced_strategy_ranks_extreme_spikes_below_orderly_candidates():
    provider = FakeResearchProvider(
        (
            make_research(
                "SPIKE",
                catalysts=("Strong intraday momentum (+155.65%)", "High live turnover"),
                risks=("Sparse live-source data", "Extreme intraday spike"),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "ORDERLY",
                catalysts=("Positive intraday momentum (+6.25%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="balanced"
    )

    assert [item.research.company.ticker for item in items] == ["ORDERLY", "SPIKE"]


def test_momentum_strategy_can_surface_extreme_spikes():
    provider = FakeResearchProvider(
        (
            make_research(
                "SPIKE",
                catalysts=("Strong intraday momentum (+155.65%)", "High live turnover"),
                risks=("Sparse live-source data", "Extreme intraday spike"),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "ORDERLY",
                catalysts=("Positive intraday momentum (+6.25%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="momentum"
    )

    assert items[0].research.company.ticker == "SPIKE"


def test_long_term_strategy_discounts_intraday_trading_setup():
    provider = FakeResearchProvider(
        (
            make_research(
                "TRADER",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("Strong intraday momentum (+12.93%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "VALUE",
                pe_ratio=9.0,
                price_to_book=0.9,
                net_cash_eur_m=20.0,
                catalysts=("Moderate live turnover",),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.PARTIAL,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert items[0].research.company.ticker == "VALUE"


def test_build_watchlist_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategy must be one of"):
        build_watchlist(
            FixtureResearchProvider(),
            countries=("SE", "FI"),
            limit=1,
            include_first_north=True,
            strategy="bad",
        )


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
                evidence=(
                    Evidence(
                        label="Nasdaq Nordic listing source",
                        url="https://api.nasdaq.com/api/nordic/screener/shares",
                        source="nasdaq",
                    ),
                ),
            ),
        )
    )

    report = build_deep_dive(provider, "LIVE")

    assert report.valuation_view[0] == "Live price is 34.9 SEK from Nasdaq Nordic."
    assert "P/E is unavailable" in report.valuation_view[1]


def test_build_deep_dive_uses_neutral_price_wording_for_non_nasdaq_sources():
    provider = FakeResearchProvider((make_research("FIX", price=5.0, currency="SEK"),))

    report = build_deep_dive(provider, "FIX")

    assert report.valuation_view[0] == "Price is 5 SEK."


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


def test_render_deep_dive_json_is_machine_readable():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    payload = json.loads(render_deep_dive_json(report))

    assert payload["company"]["ticker"] == "FREEM"
    assert payload["disclaimer"].startswith("Research triage")
    assert payload["bull_case"]
    assert payload["next_manual_checks"]


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
