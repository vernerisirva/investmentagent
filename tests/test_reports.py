import json

import pytest

from investmentagent.fundamentals import EnrichedResearchProvider, FundamentalsSnapshot
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
    render_watchlist_report_json,
    render_watchlist_report_markdown,
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


class CompanyAwareDuplicateTickerProvider:
    def __init__(self) -> None:
        self._research = (
            _make_country_specific_research("SE", "SEK", 12.5),
            _make_country_specific_research("FI", "EUR", 7.75),
        )
        self._companies = [item.company for item in self._research]

    def list_companies(
        self, countries: tuple[str, ...], include_first_north: bool
    ) -> list[Company]:
        wanted = {country.upper() for country in countries}
        return [company for company in self._companies if company.country in wanted]

    def get_research(self, ticker: str) -> CompanyResearch:
        for research in self._research:
            if research.company.ticker == ticker:
                return research
        raise LookupError(ticker)

    def get_company_research(self, company: Company) -> CompanyResearch:
        for research in self._research:
            if (
                research.company.ticker == company.ticker
                and research.company.country == company.country
            ):
                return research
        raise LookupError(company.ticker)


def make_research(
    ticker: str,
    *,
    name: str | None = None,
    country: str = "SE",
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
        name=name or f"{ticker} AB",
        ticker=ticker,
        country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
        segment=segment,
        sector="Industrials",
        market_cap_eur_m=200,
        currency="SEK" if country == "SE" else "EUR",
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


def _make_country_specific_research(
    country: str, currency: str, price: float
) -> CompanyResearch:
    company = Company(
        name=f"Same Symbol {country}",
        ticker="SAME",
        country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
        segment=ListingSegment.MAIN_MARKET,
        sector="Industrials",
        market_cap_eur_m=200,
        currency=currency,
    )
    financials = FinancialSnapshot(
        price=price,
        currency=currency,
        pe_ratio=10.0,
        price_to_book=1.0,
        net_cash_eur_m=5.0,
        data_quality=DataQuality.THIN,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        data_quality=DataQuality.THIN,
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


def test_build_watchlist_can_require_minimum_country_representation():
    provider = FakeResearchProvider(
        (
            make_research("SEA", country="SE", catalysts=("High live turnover",)),
            make_research("SEB", country="SE", catalysts=("High live turnover",)),
            make_research("SEC", country="SE", catalysts=("High live turnover",)),
            make_research("SED", country="SE", catalysts=("High live turnover",)),
            make_research("FIA", country="FI"),
            make_research("FIB", country="FI"),
            make_research("FIC", country="FI"),
        )
    )

    items = build_watchlist(
        provider,
        countries=("SE", "FI"),
        limit=5,
        include_first_north=True,
        min_country_counts={"FI": 3},
    )

    assert len(items) == 5
    assert sum(item.research.company.country == "FI" for item in items) == 3
    assert [item.rank for item in items] == [1, 2, 3, 4, 5]


def test_build_watchlist_uses_available_country_count_when_requirement_exceeds_supply():
    provider = FakeResearchProvider(
        (
            make_research("SEA", country="SE", catalysts=("High live turnover",)),
            make_research("SEB", country="SE", catalysts=("High live turnover",)),
            make_research("FIA", country="FI"),
        )
    )

    items = build_watchlist(
        provider,
        countries=("SE", "FI"),
        limit=5,
        include_first_north=True,
        min_country_counts={"FI": 3},
    )

    assert len(items) == 3
    assert sum(item.research.company.country == "FI" for item in items) == 1


def test_build_watchlist_skips_missing_research_rows():
    provider = MissingResearchProvider(
        (make_research("BROKEN"), make_research("READY"))
    )

    items = build_watchlist(provider, countries=("SE",), limit=2, include_first_north=True)

    assert [item.research.company.ticker for item in items] == ["READY"]


def test_build_watchlist_preserves_company_specific_duplicate_tickers():
    provider = CompanyAwareDuplicateTickerProvider()

    items = build_watchlist(provider, countries=("SE", "FI"), limit=2, include_first_north=True)

    assert [item.research.company.country for item in items] == ["SE", "FI"]
    assert [item.research.financials.currency for item in items] == ["SEK", "EUR"]


def test_build_watchlist_deduplicates_dual_listed_company_names():
    provider = FakeResearchProvider(
        (
            make_research(
                "NANOFS",
                name="Nanoform Finland Oyj",
                country="SE",
                catalysts=("High live turnover",),
            ),
            make_research(
                "NANOFH",
                name="Nanoform Finland Oyj",
                country="FI",
                catalysts=("Positive intraday momentum (+5.1%)",),
            ),
            make_research("AIFORIA", name="Aiforia Technologies Oyj", country="FI"),
            make_research("ELISA", name="Elisa Oyj", country="FI"),
            make_research("IVACC", name="Intervacc AB", country="SE"),
        )
    )

    items = build_watchlist(
        provider,
        countries=("SE", "FI"),
        limit=4,
        include_first_north=True,
        min_country_counts={"FI": 2},
    )

    assert len(items) == 4
    assert [item.research.company.name for item in items].count("Nanoform Finland Oyj") == 1
    assert sum(item.research.company.country == "FI" for item in items) >= 2


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


def test_long_term_strategy_prefers_enriched_value_over_intraday_mover():
    provider = FakeResearchProvider(
        (
            make_research(
                "MOVER",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("Strong intraday momentum (+12.93%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "VALUE",
                pe_ratio=8.5,
                price_to_book=0.9,
                net_cash_eur_m=30.0,
                catalysts=("Live price available from Nasdaq Nordic",),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.PARTIAL,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert items[0].research.company.ticker == "VALUE"


def test_long_term_strategy_prioritizes_fundamental_quality_over_momentum():
    quality = make_research(
        "QUALITY",
        pe_ratio=11.0,
        price_to_book=1.1,
        net_cash_eur_m=25.0,
        catalysts=("Live price available from Nasdaq Nordic",),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.PARTIAL,
    )
    quality = CompanyResearch(
        company=Company(
            name=quality.company.name,
            ticker=quality.company.ticker,
            country=quality.company.country,
            exchange=quality.company.exchange,
            segment=quality.company.segment,
            sector=quality.company.sector,
            market_cap_eur_m=quality.company.market_cap_eur_m,
            currency=quality.company.currency,
            business_description="Quality AB sells profitable niche software to industrial customers.",
        ),
        financials=FinancialSnapshot(
            pe_ratio=11.0,
            price_to_book=1.1,
            net_cash_eur_m=25.0,
            revenue_growth_pct=12.0,
            operating_margin_pct=18.0,
            debt_to_equity=0.2,
            data_quality=DataQuality.PARTIAL,
        ),
        catalysts=quality.catalysts,
        risks=quality.risks,
        data_quality=DataQuality.PARTIAL,
    )
    mover = make_research(
        "MOVER",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=("Strong intraday momentum (+14.16%)", "High live turnover"),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.PARTIAL,
    )

    items = build_watchlist(
        FakeResearchProvider((mover, quality)),
        countries=("SE",),
        limit=2,
        include_first_north=True,
        strategy="long-term",
    )

    assert items[0].research.company.ticker == "QUALITY"
    assert "Strong intraday momentum (+14.16%)" not in items[0].score.reasons
    assert "High live turnover" not in items[0].score.reasons
    assert "Positive operating margin" in items[0].score.reasons
    assert "Revenue growth" in items[0].score.reasons
    assert "Business description available" in items[0].score.reasons


def test_long_term_strategy_penalizes_intraday_mover_without_fundamental_anchor():
    momentum = make_research(
        "MOMO",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=("Positive intraday momentum (+5.9%)", "High live turnover"),
        segment=ListingSegment.FIRST_NORTH,
        data_quality=DataQuality.GOOD,
    )
    momentum = CompanyResearch(
        company=Company(
            name=momentum.company.name,
            ticker=momentum.company.ticker,
            country=momentum.company.country,
            exchange=momentum.company.exchange,
            segment=momentum.company.segment,
            sector=momentum.company.sector,
            market_cap_eur_m=momentum.company.market_cap_eur_m,
            currency=momentum.company.currency,
            business_description="Momo AB has a business description, but no supporting fundamentals.",
        ),
        financials=momentum.financials,
        catalysts=momentum.catalysts,
        risks=momentum.risks,
        data_quality=momentum.data_quality,
    )

    items = build_watchlist(
        FakeResearchProvider((momentum,)),
        countries=("SE",),
        limit=1,
        include_first_north=True,
        strategy="long-term",
    )

    assert items[0].score.total <= 0
    assert "missing long-term fundamental support" in items[0].score.warnings
    assert not any("intraday momentum" in reason.lower() for reason in items[0].score.reasons)


def test_watchlist_fundamentals_budget_uses_preliminary_ranking_not_listing_order():
    weak = make_research(
        "WEAK",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=(),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )
    value = make_research(
        "VALUE",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=("High live turnover",),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )
    value = CompanyResearch(
        company=Company(
            name=value.company.name,
            ticker=value.company.ticker,
            country=value.company.country,
            exchange=value.company.exchange,
            segment=value.company.segment,
            sector=value.company.sector,
            market_cap_eur_m=value.company.market_cap_eur_m,
            currency=value.company.currency,
            business_description="Value AB has a defined business for long-term review.",
        ),
        financials=FinancialSnapshot(
            debt_to_equity=0.2,
            average_daily_value_eur=200000,
            data_quality=DataQuality.THIN,
        ),
        catalysts=value.catalysts,
        risks=value.risks,
        data_quality=value.data_quality,
    )

    class StaticFundamentalsProvider:
        def __init__(self) -> None:
            self.requests: list[Company] = []

        def get_fundamentals(self, company: Company):
            self.requests.append(company)
            if company.ticker != "VALUE":
                return None
            return FundamentalsSnapshot(
                symbol="VALUE.ST",
                financials=FinancialSnapshot(
                    pe_ratio=8.5,
                    price_to_book=0.9,
                    net_cash_eur_m=30.0,
                    data_quality=DataQuality.PARTIAL,
                ),
            )

    fundamentals = StaticFundamentalsProvider()
    provider = EnrichedResearchProvider(
        FakeResearchProvider((weak, value)), fundamentals, max_enrichments=1
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert [company.ticker for company in fundamentals.requests] == ["VALUE"]
    assert items[0].research.company.ticker == "VALUE"
    assert items[0].research.financials.pe_ratio == 8.5


def test_watchlist_fundamentals_budget_includes_min_country_candidates():
    sweden = make_research(
        "SWEA",
        country="SE",
        catalysts=("High live turnover",),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )
    finland = make_research(
        "FINA",
        country="FI",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=(),
        risks=("Sparse live-source data",),
        data_quality=DataQuality.THIN,
    )

    class StaticFundamentalsProvider:
        def __init__(self) -> None:
            self.requests: list[Company] = []

        def get_fundamentals(self, company: Company):
            self.requests.append(company)
            if company.ticker != "FINA":
                return None
            return FundamentalsSnapshot(
                symbol="FINA.HE",
                financials=FinancialSnapshot(
                    revenue_growth_pct=9.0,
                    operating_margin_pct=12.0,
                    data_quality=DataQuality.PARTIAL,
                ),
            )

    fundamentals = StaticFundamentalsProvider()
    provider = EnrichedResearchProvider(
        FakeResearchProvider((sweden, finland)), fundamentals, max_enrichments=1
    )

    items = build_watchlist(
        provider,
        countries=("SE", "FI"),
        limit=1,
        include_first_north=True,
        strategy="long-term",
        min_country_counts={"FI": 1},
    )

    assert [company.ticker for company in fundamentals.requests] == ["FINA"]
    assert items[0].research.company.ticker == "FINA"
    assert items[0].research.financials.operating_margin_pct == 12.0


def test_trading_strategy_boosts_strong_momentum_and_turnover():
    provider = FakeResearchProvider(
        (
            make_research(
                "FAST",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("Strong intraday momentum (+12.93%)", "High live turnover"),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
            make_research(
                "SLOW",
                pe_ratio=None,
                price_to_book=None,
                net_cash_eur_m=None,
                catalysts=("High live turnover",),
                risks=("Sparse live-source data",),
                data_quality=DataQuality.THIN,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="trading"
    )

    assert items[0].research.company.ticker == "FAST"
    assert items[0].score.catalyst == 26.0
    assert items[0].score.total == 12.75
    assert "trading strategy adjustment applied" in items[0].score.reasons


def test_trading_strategy_requires_short_term_setup():
    generic_value = make_research(
        "VALUE",
        pe_ratio=8.0,
        price_to_book=0.8,
        net_cash_eur_m=30.0,
        catalysts=("Live price available from Nasdaq Nordic",),
        segment=ListingSegment.FIRST_NORTH,
    )
    event_setup = make_research(
        "EVENT",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=("Order win announced",),
        segment=ListingSegment.MAIN_MARKET,
    )

    items = build_watchlist(
        FakeResearchProvider((generic_value, event_setup)),
        countries=("SE",),
        limit=2,
        include_first_north=True,
        strategy="trading",
    )

    assert [item.research.company.ticker for item in items] == ["EVENT"]
    assert "Order win announced" in items[0].score.reasons


def test_trading_and_long_term_strategies_diverge_on_their_criteria():
    durable_quality = make_research(
        "QUALITY",
        pe_ratio=10.0,
        price_to_book=1.0,
        net_cash_eur_m=30.0,
        catalysts=("Live price available from Nasdaq Nordic",),
        segment=ListingSegment.FIRST_NORTH,
    )
    durable_quality = CompanyResearch(
        company=Company(
            name=durable_quality.company.name,
            ticker=durable_quality.company.ticker,
            country=durable_quality.company.country,
            exchange=durable_quality.company.exchange,
            segment=durable_quality.company.segment,
            sector=durable_quality.company.sector,
            market_cap_eur_m=durable_quality.company.market_cap_eur_m,
            currency=durable_quality.company.currency,
            business_description="Quality AB sells profitable niche software.",
        ),
        financials=FinancialSnapshot(
            pe_ratio=10.0,
            price_to_book=1.0,
            net_cash_eur_m=30.0,
            revenue_growth_pct=9.0,
            operating_margin_pct=18.0,
            debt_to_equity=0.1,
            data_quality=DataQuality.PARTIAL,
        ),
        catalysts=durable_quality.catalysts,
        risks=durable_quality.risks,
        data_quality=DataQuality.PARTIAL,
    )
    short_term_setup = make_research(
        "TRADE",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        catalysts=("Strong intraday momentum (+12.0%)", "High live turnover"),
        segment=ListingSegment.MAIN_MARKET,
        data_quality=DataQuality.THIN,
    )

    provider = FakeResearchProvider((durable_quality, short_term_setup))

    trading_items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="trading"
    )
    long_term_items = build_watchlist(
        provider, countries=("SE",), limit=2, include_first_north=True, strategy="long-term"
    )

    assert [item.research.company.ticker for item in trading_items] == ["TRADE"]
    assert long_term_items[0].research.company.ticker == "QUALITY"


def test_long_term_strategy_downweights_discovery_without_fundamentals():
    first_north_shell = make_research(
        "SHELL",
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
        segment=ListingSegment.FIRST_NORTH,
    )
    quality_main_market = make_research(
        "QUALITY",
        pe_ratio=16.0,
        price_to_book=2.5,
        net_cash_eur_m=None,
        segment=ListingSegment.MAIN_MARKET,
    )
    quality_main_market = CompanyResearch(
        company=Company(
            name=quality_main_market.company.name,
            ticker=quality_main_market.company.ticker,
            country=quality_main_market.company.country,
            exchange=quality_main_market.company.exchange,
            segment=quality_main_market.company.segment,
            sector=quality_main_market.company.sector,
            market_cap_eur_m=900,
            currency=quality_main_market.company.currency,
        ),
        financials=FinancialSnapshot(
            pe_ratio=16.0,
            price_to_book=2.5,
            revenue_growth_pct=8.0,
            operating_margin_pct=16.0,
            debt_to_equity=0.2,
            data_quality=DataQuality.PARTIAL,
        ),
        catalysts=quality_main_market.catalysts,
        risks=quality_main_market.risks,
        data_quality=DataQuality.PARTIAL,
    )

    items = build_watchlist(
        FakeResearchProvider((first_north_shell, quality_main_market)),
        countries=("SE",),
        limit=2,
        include_first_north=True,
        strategy="long-term",
    )

    assert items[0].research.company.ticker == "QUALITY"


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
            average_daily_value_eur=250000,
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
            average_daily_value_eur=35000,
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
            average_daily_value_eur=160000,
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


def test_long_term_strategy_dedupes_overlapping_quality_signals():
    duplicate_signals = CompanyResearch(
        company=Company(
            name="Duplicate Signals AB",
            ticker="DUP",
            country="SE",
            exchange="Nasdaq Stockholm",
            segment=ListingSegment.MAIN_MARKET,
            sector="Software",
            market_cap_eur_m=240,
            currency="SEK",
            business_description="Duplicate Signals sells subscription workflow tools.",
        ),
        financials=FinancialSnapshot(
            pe_ratio=11.0,
            price_to_book=1.1,
            net_cash_eur_m=12.0,
            debt_to_equity=0.2,
            revenue_growth_pct=9.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=45000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    items = build_watchlist(
        FakeResearchProvider((duplicate_signals,)),
        countries=("SE",),
        limit=1,
        include_first_north=True,
        strategy="long-term",
    )

    normalized_reasons = [reason.strip().lower() for reason in items[0].score.reasons]
    normalized_warnings = [
        warning.strip().lower() for warning in items[0].score.warnings
    ]
    assert normalized_reasons.count("net cash balance sheet") == 1
    assert normalized_warnings.count("thin liquidity") == 1


def test_discovery_strategy_boosts_first_north_and_penalizes_spikes():
    provider = FakeResearchProvider(
        (
            make_research(
                "MAIN",
                catalysts=("Moderate live turnover",),
                segment=ListingSegment.MAIN_MARKET,
            ),
            make_research(
                "FIRST",
                catalysts=("Moderate live turnover",),
                segment=ListingSegment.FIRST_NORTH,
            ),
            make_research(
                "SPIKE",
                catalysts=("Strong intraday momentum (+155.65%)",),
                risks=("Extreme intraday spike", "Missing live turnover"),
                segment=ListingSegment.FIRST_NORTH,
            ),
        )
    )

    items = build_watchlist(
        provider, countries=("SE",), limit=3, include_first_north=True, strategy="discovery"
    )

    assert [item.research.company.ticker for item in items] == ["FIRST", "MAIN", "SPIKE"]
    assert items[0].score.catalyst == 8.0
    assert items[0].score.total == 78.0
    assert "discovery strategy adjustment applied" in items[0].score.reasons
    assert items[2].score.risk_penalty == 46.0
    assert "discovery strategy adjustment applied" in items[2].score.warnings


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


def test_render_watchlist_text_includes_company_presentation():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True
    )

    output = render_watchlist_text(items)

    assert "Presentation:" in output
    assert "listed" in output
    assert "Score:" in output
    assert output.index("Presentation:") < output.index("Score:")


def test_render_watchlist_text_hides_internal_live_turnover_flag():
    company = Company(
        name="Turnover Missing AB",
        ticker="TURN",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
            risks=("Missing live turnover",),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=1.0,
        ),
    )

    output = render_watchlist_text([item])

    assert "Risks: None provided." in output
    assert "Missing live turnover" not in output


def test_render_watchlist_json_is_machine_readable():
    items = build_watchlist(FixtureResearchProvider(), countries=("SE", "FI"), limit=1, include_first_north=True)

    payload = json.loads(render_watchlist_json(items))

    assert payload["disclaimer"].startswith("Research triage")
    assert payload["items"][0]["rank"] == 1
    assert "evidence" in payload["items"][0]


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

    conviction = payload["items"][0]["long_term_conviction"]
    assert conviction["bucket"] == "Quality small-cap candidate"
    assert "multiple long-term quality signals" in conviction["thesis"]
    assert conviction["components"]["Business quality"]["score"] == 5
    assert conviction["components"]["Valuation"]["view"].startswith(
        "Attractive valuation"
    )


def test_render_watchlist_report_json_uses_new_long_term_bucket_names():
    company = Company(
        name="Monitor AB",
        ticker="MON",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
        market_cap_eur_m=80,
        currency="SEK",
        business_description="Monitor AB has an understandable business.",
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(
                debt_to_equity=0.4,
                revenue_growth_pct=4.0,
                average_daily_value_eur=120000,
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


def test_render_watchlist_report_markdown_formats_company_sections():
    company = Company(
        name="Karnov Group AB",
        ticker="KAR",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        sector="Industrials",
        business_description=(
            "Karnov Group provides legal, tax, accounting, environmental, "
            "and health and safety information services through digital tools."
        ),
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
            risks=("Execution risk",),
            evidence=(
                Evidence(
                    label="Finimpulse profile lookup (KAR.ST)",
                    url="https://developers.finimpulse.com/v1/profile/",
                    source="finimpulse",
                ),
            ),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=4.0,
            discovery=3.0,
            catalyst=2.0,
            risk_penalty=1.0,
            data_quality_penalty=0.0,
            total=8.0,
            reasons=("Profitable niche data provider", "Small-cap discovery"),
            warnings=("partial data quality",),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "## #1 Karnov Group AB (KAR)" in output
    assert "**What the company does:** Karnov Group provides legal" in output
    assert "**Score:** 8" in output
    assert "### Reasons" in output
    assert "- Profitable niche data provider" in output
    assert "### Risks" in output
    assert "- Execution risk" in output
    assert "Data quality is partial" not in output
    assert "[Finimpulse profile lookup (KAR.ST)]" in output
    assert "Presentation:" not in output
    assert "Research triage only. Not financial advice.\n\nWatchlist" not in output


def test_render_watchlist_report_markdown_names_trading_strategy_page():
    output = render_watchlist_report_markdown(
        [],
        metadata={"strategy": "trading", "limit": 10},
        source_checks=[],
    )

    assert output.startswith("# InvestmentAgent Trading Ideas")
    assert (
        "Short-term setup candidates based on momentum, liquidity, and catalysts."
        in output
    )


def test_render_watchlist_report_markdown_names_long_term_strategy_page():
    output = render_watchlist_report_markdown(
        [],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert output.startswith("# InvestmentAgent Long-Term Investment Ideas")
    assert (
        "Longer-horizon candidates based on business quality, valuation, growth, "
        "balance sheet, and risk."
        in output
    )


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
                average_daily_value_eur=250000,
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
            reasons=(
                "Positive operating margin (18.0%)",
                "Revenue growth (12.0%)",
                "Conservative debt/equity",
                "Business description available from profile data",
            ),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "### Long-Term Conviction" in output
    assert "**Bucket:** Quality small-cap candidate" in output
    assert "multiple long-term quality signals" in output
    assert "| Component | Score | View |" in output
    assert "| Business quality | 5/5 | Strong - profitable business with a clear profile. |" in output
    assert "| Valuation | 5/5 | Attractive valuation on available P/E or P/B metrics. |" in output
    assert "| Growth | 4/5 | Healthy revenue growth of 12.0%. |" in output
    assert "| Balance sheet | 5/5 | Net cash and conservative debt/equity. |" in output
    assert "| Data confidence | 4/5 | Several fundamentals plus profile text are available. |" in output


def test_render_long_term_report_markdown_flags_trading_only_movers():
    company = Company(
        name="Momentum Only AB",
        ticker="MOMO",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.THIN),
            catalysts=("Strong intraday momentum (+18.0%)", "High live turnover"),
            risks=("Sparse live-source data",),
            data_quality=DataQuality.THIN,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=5.0,
            catalyst=0.0,
            risk_penalty=18.0,
            data_quality_penalty=8.0,
            total=-21.0,
            warnings=("long-term strategy penalty applied",),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "**Bucket:** Insufficient evidence" in output
    assert "lacks enough durable evidence" in output
    assert "| Business quality | 0/5 | Insufficient business and margin data. |" in output
    assert "| Data confidence | 0/5 | No useful fundamentals or profile text are available today. |" in output
    assert "Sparse live-source data" not in output
    assert "One risk flag" not in output


def test_render_long_term_report_markdown_flags_weak_data_without_trading_signal():
    company = Company(
        name="Unknown Fundamentals AB",
        ticker="UNKN",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
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
            discovery=5.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=8.0,
            total=-3.0,
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "long-term", "limit": 10},
        source_checks=[],
    )

    assert "**Bucket:** Insufficient evidence" in output
    assert "lacks enough durable evidence" in output


def test_render_trading_report_markdown_omits_long_term_conviction_layer():
    company = Company(
        name="Trading Setup AB",
        ticker="TRADE",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
            catalysts=("Strong intraday momentum (+12.0%)",),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=5.0,
            catalyst=20.0,
            risk_penalty=0.0,
            data_quality_penalty=4.0,
            total=21.0,
            reasons=("Strong intraday momentum (+12.0%)",),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "trading", "limit": 10},
        source_checks=[],
    )

    assert "### Long-Term Conviction" not in output
    assert "**Bucket:**" not in output


def test_render_watchlist_report_markdown_humanizes_reason_and_risk_signals():
    company = Company(
        name="Sprint Bioscience",
        ticker="SPRINT",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
        sector="Health Care",
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
            risks=("Sparse live-source data", "Missing live turnover"),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=33.0,
            reasons=(
                "small market cap",
                "Positive intraday momentum (+8.71%)",
                "trading strategy adjustment applied",
            ),
            warnings=(
                "1 stated risk(s)",
                "partial data quality",
                "trading strategy adjustment applied",
            ),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "trading"},
        source_checks=[],
    )

    assert "- Small market cap" in output
    assert "- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist." in output
    assert "Live data is sparse" not in output
    assert "- One risk flag was found in the source data." not in output
    assert "Data quality is partial" not in output
    assert "- partial data quality" not in output
    assert "- 1 stated risk(s)" not in output
    assert "Missing live turnover" not in output
    assert "- trading strategy adjustment applied" not in output
    assert "Trading strategy penalty applied by the ranking model" not in output


def test_render_watchlist_report_markdown_keeps_specific_risks_only():
    company = Company(
        name="Margin Risk AB",
        ticker="MRGN",
        country="SE",
        exchange="Nasdaq First North Growth Market Sweden",
        segment=ListingSegment.FIRST_NORTH,
    )
    item = WatchlistItem(
        rank=1,
        research=CompanyResearch(
            company=company,
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
            risks=("Sparse live-source data",),
            data_quality=DataQuality.PARTIAL,
        ),
        score=ScoreBreakdown(
            value=0.0,
            discovery=0.0,
            catalyst=0.0,
            risk_penalty=0.0,
            data_quality_penalty=0.0,
            total=1.0,
            warnings=(
                "negative operating margin",
                "1 stated risk(s)",
                "partial data quality",
            ),
        ),
    )

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "trading"},
        source_checks=[],
    )

    assert "- Negative operating margin" in output
    assert "Sparse live-source data" not in output
    assert "One risk flag" not in output
    assert "Data quality is partial" not in output


def test_render_watchlist_report_markdown_falls_back_to_presentation():
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

    output = render_watchlist_report_markdown(
        [item],
        metadata={"strategy": "trading"},
        source_checks=[],
    )

    assert (
        "**What the company does:** Sparse AB is a Sweden-listed First North company "
        "on Nasdaq First North Growth Market Sweden."
    ) in output


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
