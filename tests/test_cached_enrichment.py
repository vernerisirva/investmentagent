from datetime import datetime, timezone

from investmentagent.fundamentals import EnrichedResearchProvider
from investmentagent.fundamentals_cache import (
    FileFundamentalsCache,
    FundamentalsFreshnessPolicy,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    FundamentalsSnapshot,
    ListingSegment,
    ObservationConfidence,
    ReportingPeriodType,
    SourceCheck,
)
from investmentagent.reports import build_watchlist


def timestamp(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


def make_company(ticker: str, country: str = "SE") -> Company:
    sequence = sum(ord(character) for character in ticker)
    isin = f"{country}{sequence:010d}"
    return Company(
        name=f"{ticker} Company",
        ticker=ticker,
        country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
        segment=ListingSegment.FIRST_NORTH,
        isin=isin,
        market_cap_eur_m=80.0,
        currency="SEK" if country == "SE" else "EUR",
    )


def make_snapshot(
    company: Company,
    *,
    pe_ratio: float = 8.0,
) -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        symbol=f"{company.ticker}.{'ST' if company.country == 'SE' else 'HE'}",
        market_cap_eur_m=company.market_cap_eur_m,
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            price_to_book=0.8,
            net_cash_eur_m=12.0,
            operating_margin_pct=16.0,
            data_quality=DataQuality.PARTIAL,
            observations=(
                FinancialObservation(
                    canonical_field="pe_ratio",
                    normalized_value=pe_ratio,
                    provider="eodhd",
                    source_metric="Valuation.TrailingPE",
                    as_of="2026-08-01",
                    period_type=ReportingPeriodType.TTM,
                    confidence=ObservationConfidence.MEDIUM,
                ),
                FinancialObservation(
                    canonical_field="price_to_book",
                    normalized_value=0.8,
                    provider="eodhd",
                    source_metric="Valuation.PriceBookMRQ",
                    period_type=ReportingPeriodType.MRQ,
                    confidence=ObservationConfidence.MEDIUM,
                ),
                FinancialObservation(
                    canonical_field="operating_margin_pct",
                    normalized_value=16.0,
                    provider="eodhd",
                    source_metric="Highlights.OperatingMarginTTM",
                    period_type=ReportingPeriodType.TTM,
                    confidence=ObservationConfidence.MEDIUM,
                ),
            ),
        ),
        evidence=Evidence(
            label=f"EODHD fundamentals lookup ({company.ticker})",
            url="https://example.test/eodhd",
            source="eodhd",
        ),
    )


class BaseProvider:
    def __init__(self, companies: tuple[Company, ...]) -> None:
        self.companies = companies

    def list_companies(self, countries, include_first_north):
        wanted = {country.upper() for country in countries}
        return [company for company in self.companies if company.country in wanted]

    def get_company_research(self, company: Company) -> CompanyResearch:
        return CompanyResearch(
            company=company,
            financials=FinancialSnapshot(
                price=10.0,
                currency=company.currency,
                data_quality=DataQuality.THIN,
            ),
            data_quality=DataQuality.THIN,
        )

    def get_research(self, ticker: str) -> CompanyResearch:
        return self.get_company_research(
            next(company for company in self.companies if company.ticker == ticker)
        )

    def source_checks(self):
        return [SourceCheck("base", "ok", "fixture base data")]


class RecordingFundamentalsProvider:
    def __init__(self, snapshots=None) -> None:
        self.snapshots = snapshots or {}
        self.requests: list[str] = []

    def get_fundamentals(self, company: Company):
        self.requests.append(company.ticker)
        return self.snapshots.get(company.ticker)

    def source_check(self):
        return SourceCheck("fundamentals", "ok", f"{len(self.requests)} requests")


def test_cached_company_outside_refresh_selection_can_enter_top_n(tmp_path):
    aaa = make_company("AAA")
    zzz = make_company("ZZZ")
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(zzz, make_snapshot(zzz), retrieved_at=timestamp(9))
    fundamentals = RecordingFundamentalsProvider()
    provider = EnrichedResearchProvider(
        BaseProvider((aaa, zzz)),
        fundamentals,
        enrichment_limit=1,
        cache=cache,
        freshness_policy=FundamentalsFreshnessPolicy(max_age_days=45),
        known_at=timestamp(10),
        retrieval_clock=lambda: timestamp(10, 9),
    )

    items = build_watchlist(
        provider,
        countries=("SE",),
        limit=1,
        include_first_north=True,
    )

    assert items[0].research.company.ticker == "ZZZ"
    assert items[0].research.financials.pe_ratio == 8.0
    assert fundamentals.requests == ["AAA"]
    assert "ZZZ" not in fundamentals.requests
    assert provider.enrichment_stats()["cache_hits"] == 1


def test_failed_refresh_preserves_stale_cached_snapshot(tmp_path):
    zzz = make_company("ZZZ")
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(zzz, make_snapshot(zzz, pe_ratio=8.0), retrieved_at=timestamp(1))
    fundamentals = RecordingFundamentalsProvider()
    provider = EnrichedResearchProvider(
        BaseProvider((zzz,)),
        fundamentals,
        enrichment_limit=1,
        cache=cache,
        freshness_policy=FundamentalsFreshnessPolicy(max_age_days=5),
        known_at=timestamp(10),
        retrieval_clock=lambda: timestamp(10, 9),
    )

    items = build_watchlist(
        provider,
        countries=("SE",),
        limit=1,
        include_first_north=True,
    )

    assert fundamentals.requests == ["ZZZ"]
    assert items[0].research.financials.pe_ratio == 8.0
    assert len(cache.records_for(zzz)) == 1
    stats = provider.enrichment_stats()
    assert stats["stale_companies"] == 1
    assert stats["attempts"] == 1
    assert stats["successful_enrichments"] == 0


def test_refresh_requests_are_bounded(tmp_path):
    companies = tuple(make_company(f"C{index}") for index in range(5))
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    fundamentals = RecordingFundamentalsProvider(
        {company.ticker: make_snapshot(company) for company in companies}
    )
    provider = EnrichedResearchProvider(
        BaseProvider(companies),
        fundamentals,
        enrichment_limit=2,
        cache=cache,
        known_at=timestamp(10),
        retrieval_clock=lambda: timestamp(10, 9),
    )

    build_watchlist(
        provider,
        countries=("SE",),
        limit=2,
        include_first_north=True,
    )

    assert len(fundamentals.requests) == 2
    assert len(cache.records) == 2
    stats = provider.enrichment_stats()
    assert stats["refresh_budget"] == 2
    assert stats["cached_companies"] == 2
    assert stats["fresh_companies"] == 2
    assert stats["missing_companies"] == 3
    assert "cache coverage=2/5" in provider.enrichment_source_check().detail


def test_repeated_bounded_refreshes_expand_cache_coverage(tmp_path):
    companies = tuple(make_company(f"C{index}") for index in range(5))
    cache_path = tmp_path / "cache.json"
    covered_counts = []

    for day in (10, 11, 12):
        cache = FileFundamentalsCache(cache_path)
        fundamentals = RecordingFundamentalsProvider(
            {company.ticker: make_snapshot(company) for company in companies}
        )
        provider = EnrichedResearchProvider(
            BaseProvider(companies),
            fundamentals,
            enrichment_limit=2,
            cache=cache,
            freshness_policy=FundamentalsFreshnessPolicy(max_age_days=45),
            known_at=timestamp(day),
            retrieval_clock=lambda day=day: timestamp(day, 9),
        )
        build_watchlist(
            provider,
            countries=("SE",),
            limit=2,
            include_first_north=True,
        )
        covered_counts.append(len(cache.records))

    assert covered_counts == [2, 4, 5]


def test_cache_enrichment_respects_requested_countries(tmp_path):
    swe = make_company("SWE", "SE")
    fin = make_company("FIN", "FI")
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(swe, make_snapshot(swe), retrieved_at=timestamp(9))
    cache.store(fin, make_snapshot(fin), retrieved_at=timestamp(9))
    provider = EnrichedResearchProvider(
        BaseProvider((swe, fin)),
        RecordingFundamentalsProvider(),
        enrichment_limit=0,
        cache=cache,
        known_at=timestamp(10),
        retrieval_clock=lambda: timestamp(10, 9),
    )

    items = build_watchlist(
        provider,
        countries=("FI",),
        limit=1,
        include_first_north=True,
        min_country_counts={"FI": 1},
    )

    assert [item.research.company.ticker for item in items] == ["FIN"]
    stats = provider.enrichment_stats()
    assert stats["eligible_companies"] == 1
    assert stats["country_coverage"] == {
        "FI": {"eligible": 1, "cached": 1, "fresh": 1, "stale": 0, "missing": 0}
    }


def test_refresh_is_recorded_when_received_not_at_run_start(tmp_path):
    aaa = make_company("AAA")
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    provider = EnrichedResearchProvider(
        BaseProvider((aaa,)),
        RecordingFundamentalsProvider({"AAA": make_snapshot(aaa)}),
        enrichment_limit=1,
        cache=cache,
        known_at=timestamp(10, 8),
        retrieval_clock=lambda: timestamp(10, 12),
    )

    build_watchlist(
        provider,
        countries=("SE",),
        limit=1,
        include_first_north=True,
    )

    assert cache.get_latest(aaa, known_at=timestamp(10, 10)) is None
    assert cache.get_latest(aaa, known_at=timestamp(10, 13)).retrieved_at == timestamp(
        10, 12
    )
