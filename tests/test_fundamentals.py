import json

from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    finimpulse_symbol_candidates,
    finnhub_symbol_candidates,
    yahoo_symbol_candidates,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
)


def make_company(
    ticker: str = "KAR",
    country: str = "SE",
    name: str = "Karnov Group AB",
) -> Company:
    return Company(
        name=name,
        ticker=ticker,
        country=country,
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        currency="SEK" if country == "SE" else "EUR",
    )


def yahoo_payload() -> str:
    return json.dumps(
        {
            "quoteSummary": {
                "result": [
                    {
                        "price": {
                            "shortName": "Karnov Group AB",
                            "currency": "SEK",
                            "marketCap": {"raw": 5_500_000_000},
                        },
                        "summaryDetail": {
                            "trailingPE": {"raw": 11.2},
                            "priceToBook": {"raw": 1.1},
                            "averageDailyVolume10Day": {"raw": 250_000},
                            "previousClose": {"raw": 110.0},
                        },
                        "financialData": {
                            "revenueGrowth": {"raw": 0.08},
                            "operatingMargins": {"raw": 0.14},
                            "debtToEquity": {"raw": 52.0},
                            "totalCash": {"raw": 900_000_000},
                            "totalDebt": {"raw": 650_000_000},
                        },
                    }
                ],
                "error": None,
            }
        }
    )


def finnhub_payload() -> str:
    return json.dumps(
        {
            "profile": {
                "country": "SE",
                "currency": "SEK",
                "exchange": "ST",
                "marketCapitalization": 5500.0,
                "name": "Karnov Group AB",
                "ticker": "KAR.ST",
            },
            "metrics": {
                "metric": {
                    "peBasicExclExtraTTM": 11.2,
                    "pbQuarterly": 1.1,
                    "revenueGrowthTTMYoy": 8.0,
                    "operatingMarginTTM": 14.0,
                    "totalDebt/totalEquityQuarterly": 52.0,
                }
            },
        }
    )


def finimpulse_search_payload() -> str:
    return json.dumps(
        {
            "status_code": 20000,
            "status_message": "OK",
            "data": {"symbols": ["KAR.ST"], "quote_types": ["stock"], "limit": 1},
            "result": {
                "total_count": 1,
                "items_count": 1,
                "items": [
                    {
                        "symbol": "KAR.ST",
                        "short_name": "Karnov Group AB",
                        "long_name": "Karnov Group AB (publ)",
                        "quote_type": "stock",
                        "currency": "SEK",
                        "regular_market_price": 72.0,
                        "average_daily_volume_10_day": 485039,
                        "one_year_return": -16.473,
                        "fifty_two_week_high_change_percent": -44.272444,
                        "market_region": "SE",
                        "sector": "Industrials",
                        "industry": "Specialty Business Services",
                        "amount": 7024167424,
                        "revenue_growth": 0.24636247668524147,
                        "net_margin": 0.36760195,
                        "free_cash_flow_margin": 0.19304025,
                        "debt_to_equity": 0.29354096,
                    }
                ],
            },
        }
    )


def finimpulse_profile_payload() -> str:
    return json.dumps(
        {
            "status_code": 20000,
            "status_message": "OK",
            "result": {
                "total_count": 1,
                "items": [
                    {
                        "symbol": "KAR.ST",
                        "quote_type": "stock",
                        "sector": "Industrials",
                        "industry": "Specialty Business Services",
                        "long_business_summary": (
                            "Karnov Group provides legal, tax, accounting, "
                            "environmental, and health and safety information "
                            "services through subscription-based digital workflow "
                            "tools in the Nordic region."
                        ),
                        "ir_website": "https://www.karnovgroup.com/en/investors/",
                    }
                ],
            },
        }
    )


def test_yahoo_symbol_candidates_for_sweden_and_finland():
    assert yahoo_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert yahoo_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_yahoo_symbol_candidates_normalize_spaces_and_share_classes():
    assert yahoo_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_yahoo_provider_parses_fundamentals_with_evidence():
    requested_urls: list[str] = []

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        return yahoo_payload()

    provider = YahooFundamentalsProvider(fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 550.0
    assert snapshot.financials.pe_ratio == 11.2
    assert snapshot.financials.price_to_book == 1.1
    assert snapshot.financials.revenue_growth_pct == 8.0
    assert snapshot.financials.operating_margin_pct == 14.0
    assert snapshot.financials.debt_to_equity == 0.52
    assert snapshot.financials.net_cash_eur_m == 25.0
    assert snapshot.financials.average_daily_value_eur == 2_750_000.0
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "yahoo"
    assert "KAR.ST" in snapshot.evidence.label
    assert requested_urls


def test_finnhub_symbol_candidates_for_sweden_and_finland():
    assert finnhub_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert finnhub_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_finnhub_symbol_candidates_normalize_spaces_and_share_classes():
    assert finnhub_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_finnhub_provider_parses_profile_and_metrics_with_token_safe_evidence():
    requested_urls: list[str] = []
    payload = json.loads(finnhub_payload())

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        if "/stock/profile2" in url:
            return json.dumps(payload["profile"])
        return json.dumps(payload["metrics"])

    provider = FinnhubFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 550.0
    assert snapshot.financials.pe_ratio == 11.2
    assert snapshot.financials.price_to_book == 1.1
    assert snapshot.financials.revenue_growth_pct == 8.0
    assert snapshot.financials.operating_margin_pct == 14.0
    assert snapshot.financials.debt_to_equity == 0.52
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "finnhub"
    assert "KAR.ST" in snapshot.evidence.label
    assert "secret-token" not in snapshot.evidence.url
    assert "token=" not in snapshot.evidence.url
    assert requested_urls
    assert any("secret-token" in url for url in requested_urls)


def test_finnhub_provider_returns_none_for_malformed_or_missing_data():
    provider = FinnhubFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url: json.dumps({}),
    )

    assert provider.get_fundamentals(make_company()) is None


def test_finnhub_source_check_warns_without_leaking_token_when_all_lookups_fail():
    def fetcher(url: str) -> str:
        raise RuntimeError(f"failed url {url}")

    provider = FinnhubFundamentalsProvider(api_key="secret-token", fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.name == "finnhub fundamentals"
    assert check.status == "warning"
    assert "no successful" in check.detail.lower()
    assert "secret-token" not in check.detail
    assert "token=" not in check.detail


def test_finnhub_source_check_redacts_raw_token_in_errors():
    def fetcher(url: str) -> str:
        raise RuntimeError("direct secret-token leak")

    provider = FinnhubFundamentalsProvider(api_key="secret-token", fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert "secret-token" not in check.detail
    assert "<redacted>" in check.detail


def test_finnhub_source_check_ok_when_lookup_succeeds():
    payload = json.loads(finnhub_payload())

    def fetcher(url: str) -> str:
        if "/stock/profile2" in url:
            return json.dumps(payload["profile"])
        return json.dumps(payload["metrics"])

    provider = FinnhubFundamentalsProvider(
        api_key="secret-token",
        fetcher=fetcher,
    )
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Finnhub lookups parsed" in check.detail


def test_finimpulse_symbol_candidates_for_sweden_and_finland():
    assert finimpulse_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert finimpulse_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)


def test_finimpulse_symbol_candidates_normalize_spaces_and_share_classes():
    assert finimpulse_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_finimpulse_provider_parses_search_result_with_token_safe_evidence():
    requested: list[tuple[str, str, dict[str, str]]] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested.append((url, payload, headers))
        return finimpulse_search_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 702.42
    assert snapshot.financials.revenue_growth_pct == 24.64
    assert snapshot.financials.operating_margin_pct == 36.76
    assert snapshot.financials.debt_to_equity == 0.29354096
    assert snapshot.financials.one_year_return_pct == -16.473
    assert snapshot.financials.distance_from_52w_high_pct == -44.272444
    assert snapshot.financials.average_daily_value_eur == 3_492_280.8
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "finimpulse"
    assert "KAR.ST" in snapshot.evidence.label
    assert "secret-token" not in snapshot.evidence.url
    assert requested
    assert requested[0][0] == "https://api.finimpulse.com/v1/search"
    assert "secret-token" in requested[0][2]["Authorization"]


def test_finimpulse_provider_fetches_profile_business_description():
    requested: list[str] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested.append(url)
        if url.endswith("/v1/profile"):
            return finimpulse_profile_payload()
        return finimpulse_search_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.business_description.startswith("Karnov Group provides legal")
    assert snapshot.ir_url == "https://www.karnovgroup.com/en/investors/"
    assert "https://api.finimpulse.com/v1/search" in requested
    assert "https://api.finimpulse.com/v1/profile" in requested


def test_enriched_provider_merges_finimpulse_business_description_into_company():
    class BaseProvider:
        def list_companies(self, countries, include_first_north):
            return [make_company()]

        def get_research(self, ticker: str) -> CompanyResearch:
            return CompanyResearch(
                company=make_company(),
                financials=FinancialSnapshot(data_quality=DataQuality.THIN),
                data_quality=DataQuality.THIN,
            )

        def source_checks(self):
            return []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        if url.endswith("/v1/profile"):
            return finimpulse_profile_payload()
        return finimpulse_search_payload()

    provider = EnrichedResearchProvider(
        BaseProvider(),
        FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher),
        max_enrichments=1,
    )

    research = provider.get_research("KAR")

    assert research.company.business_description.startswith("Karnov Group provides legal")
    assert research.company.ir_url == "https://www.karnovgroup.com/en/investors/"


def test_finimpulse_profile_failure_keeps_search_fundamentals():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        if url.endswith("/v1/profile"):
            raise RuntimeError(f"profile failed {headers['Authorization']}")
        return finimpulse_search_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())
    check = provider.source_check()

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.market_cap_eur_m == 702.42
    assert snapshot.business_description is None
    assert "secret-token" not in check.detail


def test_finimpulse_provider_returns_none_for_empty_search_results():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, payload, headers: json.dumps(
            {"status_code": 20000, "result": {"items": []}}
        ),
    )

    assert provider.get_fundamentals(make_company()) is None


def test_finimpulse_provider_ignores_non_matching_search_results():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        return json.dumps(
            {
                "status_code": 20000,
                "result": {
                    "items": [
                        {
                            "symbol": "AAPL",
                            "currency": "USD",
                            "amount": 4_000_000_000_000,
                            "revenue_growth": 0.1,
                        }
                    ]
                },
            }
        )

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    assert provider.get_fundamentals(make_company()) is None


def test_finimpulse_source_check_warns_without_leaking_token_when_lookups_fail():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        raise RuntimeError(f"failed Authorization: {headers['Authorization']}")

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.name == "finimpulse fundamentals"
    assert check.status == "warning"
    assert "no successful" in check.detail.lower()
    assert "secret-token" not in check.detail
    assert "<redacted>" in check.detail


def test_yahoo_provider_leaves_unknown_currency_money_fields_empty():
    def fetcher(url: str) -> str:
        return json.dumps(
            {
                "quoteSummary": {
                    "result": [
                        {
                            "price": {
                                "currency": "USD",
                                "marketCap": {"raw": 1_000_000_000},
                            },
                            "summaryDetail": {
                                "trailingPE": {"raw": 9.5},
                                "averageDailyVolume10Day": {"raw": 100_000},
                                "previousClose": {"raw": 20.0},
                            },
                            "financialData": {
                                "totalCash": {"raw": 200_000_000},
                                "totalDebt": {"raw": 50_000_000},
                            },
                        }
                    ],
                    "error": None,
                }
            }
        )

    provider = YahooFundamentalsProvider(fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.market_cap_eur_m is None
    assert snapshot.financials.net_cash_eur_m is None
    assert snapshot.financials.average_daily_value_eur is None
    assert snapshot.financials.pe_ratio == 9.5


def test_yahoo_provider_returns_none_for_malformed_or_missing_data():
    provider = YahooFundamentalsProvider(fetcher=lambda url: "{}")

    assert provider.get_fundamentals(make_company()) is None


def test_yahoo_source_check_warns_when_no_lookups_attempted():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())

    check = provider.source_check()

    assert check.name == "free fundamentals"
    assert check.status == "warning"
    assert "no lookups attempted" in check.detail.lower()


def test_yahoo_source_check_warns_when_all_lookups_fail():
    def fetcher(url: str) -> str:
        raise RuntimeError("malformed response")

    provider = YahooFundamentalsProvider(fetcher=fetcher)
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "warning"
    assert "no successful" in check.detail.lower()
    assert "0/1 Yahoo-style lookups parsed" in check.detail
    assert "malformed response" in check.detail


def test_yahoo_source_check_ok_when_all_attempted_lookups_succeed():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Yahoo-style lookups parsed" in check.detail


def test_yahoo_source_check_warns_when_lookup_success_is_mixed():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())
    provider.attempted_lookups = 2
    provider.successful_lookups = 1
    provider.last_error = "malformed response"

    check = provider.source_check()

    assert check.status == "warning"
    assert "1/2 Yahoo-style lookups parsed" in check.detail


class BaseProvider:
    def __init__(self) -> None:
        self.company = make_company()

    def list_companies(self, countries, include_first_north):
        return [self.company]

    def get_research(self, ticker: str) -> CompanyResearch:
        return CompanyResearch(
            company=self.company,
            financials=FinancialSnapshot(
                price=110.0, currency="SEK", data_quality=DataQuality.THIN
            ),
            catalysts=("Live price available from Nasdaq Nordic",),
            risks=("Sparse live-source data",),
            evidence=(),
            data_quality=DataQuality.THIN,
        )

    def get_company_research(self, company: Company) -> CompanyResearch:
        return self.get_research(company.ticker)

    def source_checks(self):
        return []


class StaticFundamentalsProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.requests: list[Company] = []

    def get_fundamentals(self, company: Company):
        self.requests.append(company)
        return self.snapshot

    def source_check(self):
        from investmentagent.models import SourceCheck

        return SourceCheck("free fundamentals", "ok", "fixture fundamentals available")


def test_enriched_provider_merges_fundamentals_into_research():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        market_cap_eur_m=550.0,
        financials=FinancialSnapshot(
            pe_ratio=11.2,
            price_to_book=1.1,
            operating_margin_pct=14.0,
            data_quality=DataQuality.PARTIAL,
        ),
        evidence=Evidence(
            "Yahoo-style fundamentals lookup (KAR.ST)",
            "https://example.test",
            "yahoo",
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m == 550.0
    assert research.financials.price == 110.0
    assert research.financials.currency == "SEK"
    assert research.financials.pe_ratio == 11.2
    assert research.financials.price_to_book == 1.1
    assert research.financials.operating_margin_pct == 14.0
    assert research.financials.data_quality == DataQuality.PARTIAL
    assert research.data_quality == DataQuality.PARTIAL
    assert research.evidence[-1].source == "yahoo"


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


def test_enriched_provider_preserves_curated_fundamentals():
    class CuratedBaseProvider(BaseProvider):
        def __init__(self) -> None:
            super().__init__()
            self.company = Company(
                name=self.company.name,
                ticker=self.company.ticker,
                country=self.company.country,
                exchange=self.company.exchange,
                segment=self.company.segment,
                market_cap_eur_m=700.0,
                currency=self.company.currency,
            )

        def get_research(self, ticker: str) -> CompanyResearch:
            return CompanyResearch(
                company=self.company,
                financials=FinancialSnapshot(
                    price=110.0,
                    currency="SEK",
                    pe_ratio=9.0,
                    price_to_book=0.8,
                    operating_margin_pct=20.0,
                    data_quality=DataQuality.GOOD,
                ),
                catalysts=("Curated fundamentals available",),
                risks=(),
                evidence=(),
                data_quality=DataQuality.GOOD,
            )

    base = CuratedBaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        market_cap_eur_m=550.0,
        financials=FinancialSnapshot(
            pe_ratio=11.2,
            price_to_book=1.1,
            operating_margin_pct=14.0,
            data_quality=DataQuality.PARTIAL,
        ),
        evidence=Evidence(
            "Yahoo-style fundamentals lookup (KAR.ST)",
            "https://example.test",
            "yahoo",
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m == 700.0
    assert research.financials.pe_ratio == 9.0
    assert research.financials.price_to_book == 0.8
    assert research.financials.operating_margin_pct == 20.0
    assert research.financials.data_quality == DataQuality.GOOD
    assert research.data_quality == DataQuality.GOOD
    assert research.evidence[-1].source == "yahoo"


def test_enriched_provider_upgrades_quality_when_only_market_cap_is_filled():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        market_cap_eur_m=550.0,
        financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
        evidence=Evidence(
            "Yahoo-style fundamentals lookup (KAR.ST)",
            "https://example.test",
            "yahoo",
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m == 550.0
    assert research.financials.data_quality == DataQuality.PARTIAL
    assert research.data_quality == DataQuality.PARTIAL
    assert research.evidence[-1].source == "yahoo"


def test_enriched_provider_leaves_research_unchanged_when_fundamentals_missing():
    base = BaseProvider()
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(None))

    research = provider.get_company_research(base.company)

    assert research.company.market_cap_eur_m is None
    assert research.financials.pe_ratio is None
    assert research.data_quality == DataQuality.THIN


def test_enriched_provider_respects_enrichment_budget():
    class ThreeCompanyProvider(BaseProvider):
        def __init__(self) -> None:
            self.companies = (
                make_company("ONE"),
                make_company("TWO"),
                make_company("THREE"),
            )

        def list_companies(self, countries, include_first_north):
            return list(self.companies)

        def get_company_research(self, company: Company) -> CompanyResearch:
            return CompanyResearch(
                company=company,
                financials=FinancialSnapshot(data_quality=DataQuality.THIN),
                data_quality=DataQuality.THIN,
            )

    snapshot = FundamentalsSnapshot(
        symbol="TEST.ST",
        financials=FinancialSnapshot(pe_ratio=9.5, data_quality=DataQuality.PARTIAL),
    )
    fundamentals = StaticFundamentalsProvider(snapshot)
    provider = EnrichedResearchProvider(
        ThreeCompanyProvider(), fundamentals, max_enrichments=2
    )

    companies = provider.list_companies(("SE",), include_first_north=True)
    research = [provider.get_company_research(company) for company in companies]

    assert [item.financials.pe_ratio for item in research] == [9.5, 9.5, None]
    assert [company.ticker for company in fundamentals.requests] == ["ONE", "TWO"]


def test_enriched_provider_can_restrict_enrichment_to_prepared_companies():
    class CompanyEchoProvider(BaseProvider):
        def get_company_research(self, company: Company) -> CompanyResearch:
            return CompanyResearch(
                company=company,
                financials=FinancialSnapshot(data_quality=DataQuality.THIN),
                data_quality=DataQuality.THIN,
            )

    snapshot = FundamentalsSnapshot(
        symbol="TEST.ST",
        financials=FinancialSnapshot(pe_ratio=9.5, data_quality=DataQuality.PARTIAL),
    )
    fundamentals = StaticFundamentalsProvider(snapshot)
    provider = EnrichedResearchProvider(CompanyEchoProvider(), fundamentals, max_enrichments=2)
    eligible = make_company("ELIGIBLE")
    skipped = make_company("SKIPPED")

    provider.prepare_watchlist_enrichment((eligible,))
    enriched = provider.get_company_research(eligible)
    not_enriched = provider.get_company_research(skipped)

    assert enriched.financials.pe_ratio == 9.5
    assert not_enriched.financials.pe_ratio is None
    assert [company.ticker for company in fundamentals.requests] == ["ELIGIBLE"]
