import json

import investmentagent.fundamentals as fundamentals
import pytest
from investmentagent.fundamentals import (
    EnrichedResearchProvider,
    EodhdFundamentalsProvider,
    FallbackFundamentalsProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    compose_valuation_fallback_provider,
    eodhd_symbol_candidates,
    finimpulse_symbol_candidates,
    finnhub_symbol_candidates,
    yahoo_symbol_candidates,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    ListingSegment,
    ObservationConfidence,
    ReportingPeriodType,
    SourceCheck,
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


def finimpulse_statistics_payload() -> str:
    return json.dumps(
        {
            "status_code": 20000,
            "status_message": "OK",
            "data": {"symbol": "KAR.ST"},
            "result": [
                {
                    "symbol": "KAR.ST",
                    "quote_type": "stock",
                    "currency": "SEK",
                    "current_price": 72.0,
                    "average_volume_10days": 485039,
                    "fifty_two_week_high": 129.2,
                    "market_cap": 7024167424,
                    "trailing_pe": 13.4,
                    "price_to_book": 1.2,
                    "enterprise_to_ebitda": 9.8,
                    "total_revenue": 2_400_000_000,
                    "net_income_to_common": 210_000_000,
                    "total_cash": 500_000_000,
                    "total_debt": 800_000_000,
                    "revenue_growth": 0.24636247668524147,
                    "profit_margins": 0.36760195,
                    "operating_margins": 0.21,
                    "debt_to_equity": 29.354096,
                    "update_time": "2026-08-08T05:30:00Z",
                }
            ],
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


def finimpulse_global_statistics_payload() -> str:
    return json.dumps(
        {
            "status_code": 20000,
            "status_message": "OK",
            "data": {"symbol": "NVDA"},
            "result": [
                {
                    "symbol": "NVDA",
                    "quote_type": "stock",
                    "currency": "USD",
                    "current_price": 142.0,
                    "average_volume_10days": 180_000_000,
                    "market_cap": 3_500_000_000_000,
                    "trailing_pe": 31.2,
                    "total_revenue": 130_000_000_000,
                    "revenue_growth": 0.65,
                    "profit_margins": 0.54,
                    "debt_to_equity": 20.0,
                }
            ],
        }
    )


def eodhd_payload() -> str:
    return json.dumps(
        {
            "General": {
                "Code": "MSFT",
                "Name": "Microsoft Corporation",
                "CurrencyCode": "USD",
                "Description": "Microsoft develops software and cloud services.",
                "WebURL": "https://www.microsoft.com/en-us/investor",
            },
            "Highlights": {
                "MarketCapitalization": 2_900_000_000_000,
                "PERatio": 28.4,
                "RevenueTTM": 245_000_000_000,
                "QuarterlyRevenueGrowthYOY": 0.13,
                "OperatingMarginTTM": 0.43,
                "ProfitMargin": 0.36,
            },
            "Valuation": {
                "TrailingPE": 29.1,
                "PriceBookMRQ": 9.8,
            },
        }
    )


def test_eodhd_symbol_candidates_for_sweden_finland_and_global_symbols():
    assert eodhd_symbol_candidates(make_company("KAR", "SE")) == ("KAR.ST",)
    assert eodhd_symbol_candidates(make_company("GOFORE", "FI")) == ("GOFORE.HE",)
    assert eodhd_symbol_candidates(make_company("BEAMMW B", "SE")) == (
        "BEAMMW-B.ST",
        "BEAMMWB.ST",
    )


def test_eodhd_provider_fetches_explicit_symbol_with_valuation():
    requested_urls: list[str] = []

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        return eodhd_payload()

    provider = EodhdFundamentalsProvider(api_key="eod-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals_for_symbol("msft", fallback_currency="USD")

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "MSFT"
    assert requested_urls == [
        "https://eodhd.com/api/v1.1/fundamentals/MSFT"
        "?api_token=eod-token&fmt=json"
    ]
    assert snapshot.market_cap_eur_m == 2_668_000.0
    assert snapshot.business_description == "Microsoft develops software and cloud services."
    assert snapshot.ir_url == "https://www.microsoft.com/en-us/investor"
    assert snapshot.financials.pe_ratio == 29.1
    assert snapshot.financials.price_to_book == 9.8
    assert snapshot.financials.revenue_eur_m == 225_400.0
    assert snapshot.financials.revenue_growth_pct == 13.0
    assert snapshot.financials.operating_margin_pct == 43.0
    assert snapshot.evidence.source == "eodhd"
    assert provider.source_check().status == "ok"
    assert "valuation support 1/1" in provider.source_check().detail


def test_eodhd_observations_explain_source_period_and_static_fx():
    provider = EodhdFundamentalsProvider(
        api_key="eod-token", fetcher=lambda url: eodhd_payload()
    )

    snapshot = provider.get_fundamentals_for_symbol("MSFT", fallback_currency="USD")

    assert snapshot is not None
    pe = snapshot.financials.observation_for("pe_ratio")
    revenue = snapshot.financials.observation_for("revenue_eur_m")
    assert pe is not None
    assert pe.provider == "eodhd"
    assert pe.source_metric == "Valuation.TrailingPE"
    assert pe.period_type == ReportingPeriodType.TTM
    assert pe.as_of is None
    assert revenue is not None
    assert revenue.original_currency == "USD"
    assert revenue.normalized_currency == "EUR"
    assert revenue.is_derived is True
    assert "static FX assumption: 1 USD = 0.92 EUR" in revenue.derivation
    assert revenue.confidence == ObservationConfidence.LOW


def test_eodhd_pe_precedence_falls_back_from_ttm_to_forward_with_metadata():
    payload = json.loads(eodhd_payload())
    payload["Highlights"].pop("PERatio")
    payload["Valuation"].pop("TrailingPE")
    payload["Valuation"]["ForwardPE"] = 24.2
    provider = EodhdFundamentalsProvider(
        api_key="eod-token", fetcher=lambda url: json.dumps(payload)
    )

    snapshot = provider.get_fundamentals_for_symbol("MSFT", fallback_currency="USD")

    assert snapshot is not None
    assert snapshot.financials.pe_ratio == 24.2
    observation = snapshot.financials.observation_for("pe_ratio")
    assert observation is not None
    assert observation.source_metric == "Valuation.ForwardPE"
    assert observation.period_type == ReportingPeriodType.FORWARD
    assert observation.confidence == ObservationConfidence.LOW


def test_eodhd_provider_source_check_reports_not_configured():
    provider = EodhdFundamentalsProvider(api_key=None, fetcher=lambda url: eodhd_payload())

    assert provider.get_fundamentals_for_symbol("MSFT") is None

    check = provider.source_check()

    assert check.name == "eodhd fundamentals"
    assert check.status == "warning"
    assert "EODHD_API_KEY is not configured" in check.detail


def test_compose_valuation_fallback_provider_inserts_eodhd_before_yahoo():
    primary = SymbolFundamentalsProvider(None, source_detail="finimpulse")
    eodhd = SymbolFundamentalsProvider(None, source_detail="eodhd")
    yahoo = SymbolFundamentalsProvider(
        None, source_status="warning", source_detail="yahoo"
    )

    provider = compose_valuation_fallback_provider(primary, eodhd, yahoo)

    provider.get_fundamentals_for_symbol("MSFT", fallback_currency="USD")
    checks = provider.source_checks()

    assert [check.detail for check in checks] == [
        "finimpulse",
        "eodhd",
        "0/1 fallback lookups parsed; 0 fallback valuation enrichments",
        "yahoo",
        (
            "0/1 fallback lookups parsed; 0 fallback valuation enrichments; "
            "fallback source: yahoo"
        ),
    ]


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


def test_yahoo_unknown_observation_metadata_remains_unknown():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    observation = snapshot.financials.observation_for("price_to_book")
    assert observation is not None
    assert observation.provider == "yahoo"
    assert observation.source_metric == "summaryDetail.priceToBook"
    assert observation.as_of is None
    assert observation.reporting_period is None
    assert observation.period_type is None


def test_yahoo_provider_fetches_explicit_global_symbol():
    requested_urls: list[str] = []

    def fetcher(url: str) -> str:
        requested_urls.append(url)
        return yahoo_payload()

    provider = YahooFundamentalsProvider(fetcher=fetcher)

    snapshot = provider.get_fundamentals_for_symbol("msft", fallback_currency="USD")

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "MSFT"
    assert requested_urls == [
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/MSFT"
        "?modules=price,summaryDetail,financialData"
    ]
    assert snapshot.financials.pe_ratio == 11.2
    assert provider.source_check().status == "ok"
    assert "valuation support 1/1" in provider.source_check().detail


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


def test_finnhub_metric_precedence_prefers_ttm_and_quarterly_values():
    payload = json.loads(finnhub_payload())
    payload["metrics"]["metric"].update(
        {
            "peNormalizedAnnual": 19.0,
            "pbAnnual": 2.0,
            "revenueGrowthQuarterlyYoy": 3.0,
            "operatingMarginAnnual": 9.0,
            "totalDebt/totalEquityAnnual": 80.0,
        }
    )

    snapshot = fundamentals._parse_finnhub_payload(
        payload, symbol="KAR.ST", fallback_currency="SEK"
    )

    assert snapshot is not None
    assert snapshot.financials.pe_ratio == 11.2
    assert snapshot.financials.price_to_book == 1.1
    assert snapshot.financials.operating_margin_pct == 14.0
    assert snapshot.financials.observation_for("pe_ratio").period_type == (
        ReportingPeriodType.TTM
    )
    assert snapshot.financials.observation_for("price_to_book").period_type == (
        ReportingPeriodType.QUARTERLY
    )


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


def test_finimpulse_provider_parses_statistics_with_token_safe_evidence():
    requested: list[tuple[str, str, dict[str, str]]] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested.append((url, payload, headers))
        return finimpulse_statistics_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.symbol == "KAR.ST"
    assert snapshot.market_cap_eur_m == 702.42
    assert snapshot.financials.pe_ratio == 13.4
    assert snapshot.financials.price_to_book == 1.2
    assert snapshot.financials.ev_to_ebit is None
    assert snapshot.financials.revenue_eur_m == 240.0
    assert snapshot.financials.book_value_eur_m is None
    assert snapshot.financials.net_income_eur_m == 21.0
    assert snapshot.financials.net_cash_eur_m == -30.0
    assert snapshot.financials.revenue_growth_pct == 24.64
    assert snapshot.financials.operating_margin_pct == 21.0
    assert snapshot.financials.debt_to_equity == 0.2935
    assert snapshot.financials.one_year_return_pct is None
    assert snapshot.financials.distance_from_52w_high_pct == -44.27
    assert snapshot.financials.average_daily_value_eur == 3_492_280.8
    assert snapshot.financials.data_quality == DataQuality.PARTIAL
    assert snapshot.evidence.source == "finimpulse"
    assert "KAR.ST" in snapshot.evidence.label
    assert "secret-token" not in snapshot.evidence.url
    assert requested
    assert requested[0][0] == "https://api.finimpulse.com/v1/statistics/general"
    assert json.loads(requested[0][1]) == {"symbol": "KAR.ST"}
    assert "secret-token" in requested[0][2]["Authorization"]
    assert snapshot.evidence.url.endswith("/v1/statistics/general/")


def test_finimpulse_does_not_substitute_ev_to_ebitda_for_ev_to_ebit():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, request, headers: finimpulse_statistics_payload(),
    )

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.financials.ev_to_ebit is None
    assert snapshot.financials.observation_for("ev_to_ebit") is None


@pytest.mark.parametrize("margin_key", ["profit_margins", "ebitda_margins"])
def test_finimpulse_does_not_substitute_other_margins_for_operating_margin(
    margin_key: str,
):
    payload = json.loads(finimpulse_statistics_payload())
    item = payload["result"][0]
    item.pop("operating_margins")
    item[margin_key] = 0.41
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, request, headers: json.dumps(payload),
    )

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.financials.operating_margin_pct is None
    assert snapshot.financials.observation_for("operating_margin_pct") is None


def test_finimpulse_retains_genuine_operating_margin_when_supplied():
    payload = json.loads(finimpulse_statistics_payload())
    payload["result"][0]["operating_margins"] = 0.31
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, request, headers: json.dumps(payload),
    )

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.financials.operating_margin_pct == 31.0
    observation = snapshot.financials.observation_for("operating_margin_pct")
    assert observation is not None
    assert observation.source_metric == "operating_margins"
    assert observation.provider == "finimpulse"


@pytest.mark.parametrize(
    ("source_metric", "invalid_value", "canonical_field"),
    [
        ("trailing_pe", "NaN", "pe_ratio"),
        ("price_to_book", "Infinity", "price_to_book"),
        ("debt_to_equity", "-Infinity", "debt_to_equity"),
    ],
)
def test_finimpulse_rejects_non_finite_provider_values(
    source_metric: str,
    invalid_value: str,
    canonical_field: str,
):
    payload = json.loads(finimpulse_statistics_payload())
    payload["result"][0][source_metric] = invalid_value
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, request, headers: json.dumps(payload),
    )

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert getattr(snapshot.financials, canonical_field) is None
    assert snapshot.financials.observation_for(canonical_field) is None


def test_finimpulse_as_of_metadata_is_preserved_without_inference():
    payload = json.loads(finimpulse_statistics_payload())
    payload["result"][0]["update_time"] = "2026-08-08T05:30:00Z"
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, request, headers: json.dumps(payload),
    )

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    observation = snapshot.financials.observation_for("pe_ratio")
    assert observation is not None
    assert observation.as_of == "2026-08-08T05:30:00Z"
    assert observation.reporting_period is None


def test_finimpulse_provider_fetches_explicit_symbol():
    requested_payloads: list[dict[str, object]] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested_payloads.append(json.loads(payload))
        return finimpulse_global_statistics_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals_for_symbol("NVDA", fallback_currency="USD")

    assert snapshot is not None
    assert snapshot.symbol == "NVDA"
    assert snapshot.financials.pe_ratio == 31.2
    assert snapshot.financials.revenue_eur_m is not None
    assert provider.source_check().status == "ok"
    assert "Finimpulse lookups parsed" in provider.source_check().detail
    assert requested_payloads[0] == {"symbol": "NVDA"}


def test_finimpulse_provider_fetches_profile_business_description():
    requested: list[str] = []

    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        requested.append(url)
        if url.endswith("/v1/profile"):
            return finimpulse_profile_payload()
        return finimpulse_statistics_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.business_description.startswith("Karnov Group provides legal")
    assert snapshot.ir_url == "https://www.karnovgroup.com/en/investors/"
    assert "https://api.finimpulse.com/v1/statistics/general" in requested
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
        return finimpulse_statistics_payload()

    provider = EnrichedResearchProvider(
        BaseProvider(),
        FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher),
        enrichment_limit=1,
    )

    research = provider.get_research("KAR")

    assert research.company.business_description.startswith("Karnov Group provides legal")
    assert research.company.ir_url == "https://www.karnovgroup.com/en/investors/"


def test_finimpulse_profile_failure_keeps_statistics_fundamentals():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        if url.endswith("/v1/profile"):
            raise RuntimeError(f"profile failed {headers['Authorization']}")
        return finimpulse_statistics_payload()

    provider = FinimpulseFundamentalsProvider(api_key="secret-token", fetcher=fetcher)

    snapshot = provider.get_fundamentals(make_company())
    check = provider.source_check()

    assert isinstance(snapshot, FundamentalsSnapshot)
    assert snapshot.market_cap_eur_m == 702.42
    assert snapshot.business_description is None
    assert "secret-token" not in check.detail


def test_finimpulse_provider_returns_none_for_empty_statistics_results():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, payload, headers: json.dumps(
            {"status_code": 20000, "result": []}
        ),
    )

    assert provider.get_fundamentals(make_company()) is None


def test_finimpulse_provider_ignores_non_matching_statistics_results():
    def fetcher(url: str, payload: str, headers: dict[str, str]) -> str:
        return json.dumps(
            {
                "status_code": 20000,
                "result": [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "market_cap": 4_000_000_000_000,
                        "revenue_growth": 0.1,
                    }
                ],
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


def test_finimpulse_source_check_reports_valuation_coverage():
    provider = FinimpulseFundamentalsProvider(
        api_key="secret-token",
        fetcher=lambda url, payload, headers: finimpulse_statistics_payload(),
    )
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Finimpulse lookups parsed" in check.detail
    assert "valuation support 1/1" in check.detail
    assert "direct valuation 1/1" in check.detail
    assert "proxy inputs 1/1" in check.detail
    assert "missing valuation support 0/1" in check.detail


def test_yahoo_provider_leaves_unknown_currency_money_fields_empty():
    def fetcher(url: str) -> str:
        return json.dumps(
            {
                "quoteSummary": {
                    "result": [
                        {
                            "price": {
                                "currency": "GBP",
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


def test_yahoo_source_check_reports_valuation_coverage():
    provider = YahooFundamentalsProvider(fetcher=lambda url: yahoo_payload())
    provider.get_fundamentals(make_company())

    check = provider.source_check()

    assert check.status == "ok"
    assert "1/1 Yahoo-style lookups parsed" in check.detail
    assert "valuation support 1/1" in check.detail
    assert "direct valuation 1/1" in check.detail
    assert "missing valuation support 0/1" in check.detail


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


class SymbolFundamentalsProvider:
    def __init__(
        self,
        snapshot,
        source_status: str = "ok",
        source_detail: str = "fixture provider",
    ):
        self.snapshot = snapshot
        self.source_status = source_status
        self.source_detail = source_detail
        self.company_requests: list[Company] = []
        self.symbol_requests: list[tuple[str, str | None]] = []

    def get_fundamentals(self, company: Company):
        self.company_requests.append(company)
        return self.snapshot

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ):
        self.symbol_requests.append((symbol, fallback_currency))
        return self.snapshot

    def source_check(self):
        return SourceCheck("symbol provider", self.source_status, self.source_detail)


def test_fallback_provider_merges_valuation_without_overwriting_profile():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            market_cap_eur_m=3_000_000,
            business_description="FinImpulse profile text",
            ir_url="https://investor.nvidia.com/",
            financials=FinancialSnapshot(
                revenue_growth_pct=51.7,
                operating_margin_pct=55.6,
                debt_to_equity=0.05,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        canonical_field="revenue_growth_pct",
                        normalized_value=51.7,
                        provider="finimpulse",
                        source_metric="revenue_growth",
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
            evidence=Evidence(
                "FinImpulse lookup", "https://finimpulse.example", "finimpulse"
            ),
        )
    )
    fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            market_cap_eur_m=3_100_000,
            financials=FinancialSnapshot(
                pe_ratio=31.2,
                price_to_book=19.0,
                average_daily_value_eur=9_000_000_000,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        canonical_field="pe_ratio",
                        normalized_value=31.2,
                        provider="yahoo",
                        source_metric="summaryDetail.trailingPE",
                        period_type=ReportingPeriodType.TTM,
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
            evidence=Evidence("Yahoo valuation lookup", "https://yahoo.example", "yahoo"),
        )
    )
    provider = FallbackFundamentalsProvider(primary, fallback)

    snapshot = provider.get_fundamentals_for_symbol("NVDA", fallback_currency="USD")

    assert snapshot is not None
    assert snapshot.business_description == "FinImpulse profile text"
    assert snapshot.ir_url == "https://investor.nvidia.com/"
    assert snapshot.market_cap_eur_m == 3_000_000
    assert snapshot.financials.pe_ratio == 31.2
    assert snapshot.financials.revenue_growth_pct == 51.7
    assert snapshot.financials.observation_for("pe_ratio").provider == "yahoo"
    assert (
        snapshot.financials.observation_for("revenue_growth_pct").provider
        == "finimpulse"
    )
    assert snapshot.evidence.source == "finimpulse"
    assert fallback.symbol_requests == [("NVDA", "USD")]


def test_nested_fallbacks_preserve_distinct_field_provenance():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            financials=FinancialSnapshot(
                revenue_growth_pct=51.7,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        "revenue_growth_pct",
                        51.7,
                        "finimpulse",
                        "revenue_growth",
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
        )
    )
    first_fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            financials=FinancialSnapshot(
                operating_margin_pct=55.6,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        "operating_margin_pct",
                        55.6,
                        "eodhd",
                        "Highlights.OperatingMarginTTM",
                        period_type=ReportingPeriodType.TTM,
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
        )
    )
    second_fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="NVDA",
            financials=FinancialSnapshot(
                pe_ratio=31.2,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        "pe_ratio",
                        31.2,
                        "yahoo",
                        "summaryDetail.trailingPE",
                        period_type=ReportingPeriodType.TTM,
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
        )
    )
    provider = FallbackFundamentalsProvider(
        FallbackFundamentalsProvider(primary, first_fallback),
        second_fallback,
    )

    snapshot = provider.get_fundamentals_for_symbol("NVDA", fallback_currency="USD")

    assert snapshot is not None
    assert snapshot.financials.revenue_growth_pct == 51.7
    assert snapshot.financials.operating_margin_pct == 55.6
    assert snapshot.financials.pe_ratio == 31.2
    assert {
        observation.canonical_field: observation.provider
        for observation in snapshot.financials.observations
    } == {
        "revenue_growth_pct": "finimpulse",
        "operating_margin_pct": "eodhd",
        "pe_ratio": "yahoo",
    }


def test_fallback_provider_skips_fallback_when_primary_has_valuation():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="KAR.ST",
            financials=FinancialSnapshot(
                pe_ratio=12.0, data_quality=DataQuality.PARTIAL
            ),
        )
    )
    fallback = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="KAR.ST",
            financials=FinancialSnapshot(
                pe_ratio=9.0, data_quality=DataQuality.PARTIAL
            ),
        )
    )
    provider = FallbackFundamentalsProvider(primary, fallback)

    snapshot = provider.get_fundamentals(make_company())

    assert snapshot is not None
    assert snapshot.financials.pe_ratio == 12.0
    assert fallback.company_requests == []


def test_fallback_provider_source_checks_include_both_providers():
    primary = SymbolFundamentalsProvider(None)
    fallback = SymbolFundamentalsProvider(None)
    provider = FallbackFundamentalsProvider(primary, fallback)

    checks = provider.source_checks()

    assert [check.name for check in checks] == [
        "symbol provider",
        "symbol provider",
        "valuation fallback",
    ]
    assert checks[-1].status == "warning"
    assert "0 fallback valuation enrichments" in checks[-1].detail


def test_fallback_provider_source_check_includes_fallback_failure_detail():
    primary = SymbolFundamentalsProvider(
        FundamentalsSnapshot(
            symbol="MSFT",
            financials=FinancialSnapshot(data_quality=DataQuality.PARTIAL),
        )
    )
    fallback = SymbolFundamentalsProvider(
        None,
        source_status="warning",
        source_detail=(
            "No successful Yahoo-style fundamentals lookups "
            "(0/1 Yahoo-style lookups parsed): certificate verify failed"
        ),
    )
    provider = FallbackFundamentalsProvider(primary, fallback)

    provider.get_fundamentals_for_symbol("MSFT", fallback_currency="USD")

    check = provider.source_check()

    assert check.status == "warning"
    assert "certificate verify failed" in check.detail


def test_enriched_provider_includes_composite_fundamentals_source_checks():
    base = BaseProvider()
    primary = SymbolFundamentalsProvider(None, source_detail="primary detail")
    fallback = SymbolFundamentalsProvider(None, source_detail="fallback detail")
    provider = EnrichedResearchProvider(
        base,
        FallbackFundamentalsProvider(primary, fallback),
    )

    checks = provider.source_checks()

    assert [check.detail for check in checks] == [
        "watchlist enrichment not prepared; budget=30",
        "primary detail",
        "fallback detail",
        "0 fallback valuation enrichments; no fallback lookups attempted",
    ]


def test_yahoo_fetch_uses_certifi_certificate_context(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def read(self):
            return b"{}"

    def fake_urlopen(request, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(fundamentals, "urlopen", fake_urlopen)

    assert fundamentals._fetch_url("https://query1.finance.yahoo.com/test") == "{}"
    assert "context" in captured


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
            observations=(
                FinancialObservation(
                    canonical_field="pe_ratio",
                    normalized_value=11.2,
                    provider="yahoo",
                    source_metric="summaryDetail.trailingPE",
                    period_type=ReportingPeriodType.TTM,
                    confidence=ObservationConfidence.MEDIUM,
                ),
            ),
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


def test_enriched_provider_does_not_upgrade_quality_from_low_confidence_field():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        financials=FinancialSnapshot(
            revenue_eur_m=550.0,
            data_quality=DataQuality.PARTIAL,
            observations=(
                FinancialObservation(
                    canonical_field="revenue_eur_m",
                    normalized_value=550.0,
                    provider="finimpulse",
                    source_metric="total_revenue",
                    original_currency="SEK",
                    normalized_currency="EUR",
                    is_derived=True,
                    derivation="static FX assumption: 1 SEK = 0.1 EUR",
                    confidence=ObservationConfidence.LOW,
                ),
            ),
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.financials.revenue_eur_m == 550.0
    assert research.financials.data_quality == DataQuality.THIN
    assert research.data_quality == DataQuality.THIN


def test_enriched_provider_does_not_upgrade_quality_from_stale_observation():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        financials=FinancialSnapshot(
            pe_ratio=11.2,
            data_quality=DataQuality.PARTIAL,
            observations=(
                FinancialObservation(
                    canonical_field="pe_ratio",
                    normalized_value=11.2,
                    provider="eodhd",
                    source_metric="Valuation.TrailingPE",
                    as_of="2000-01-01",
                    period_type=ReportingPeriodType.TTM,
                    confidence=ObservationConfidence.MEDIUM,
                ),
            ),
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.financials.pe_ratio == 11.2
    assert research.financials.data_quality == DataQuality.THIN


def test_enriched_provider_does_not_upgrade_quality_for_mixed_forward_history():
    base = BaseProvider()
    snapshot = FundamentalsSnapshot(
        symbol="KAR.ST",
        financials=FinancialSnapshot(
            pe_ratio=10.0,
            operating_margin_pct=14.0,
            data_quality=DataQuality.PARTIAL,
            observations=(
                FinancialObservation(
                    canonical_field="pe_ratio",
                    normalized_value=10.0,
                    provider="eodhd",
                    source_metric="Valuation.ForwardPE",
                    period_type=ReportingPeriodType.FORWARD,
                    confidence=ObservationConfidence.LOW,
                ),
                FinancialObservation(
                    canonical_field="operating_margin_pct",
                    normalized_value=14.0,
                    provider="eodhd",
                    source_metric="Highlights.OperatingMarginTTM",
                    period_type=ReportingPeriodType.TTM,
                    confidence=ObservationConfidence.MEDIUM,
                ),
            ),
        ),
    )
    provider = EnrichedResearchProvider(base, StaticFundamentalsProvider(snapshot))

    research = provider.get_company_research(base.company)

    assert research.financials.pe_ratio == 10.0
    assert research.financials.operating_margin_pct == 14.0
    assert research.financials.data_quality == DataQuality.THIN


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


def test_enriched_provider_does_not_upgrade_quality_for_unproven_market_cap():
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
    assert research.financials.data_quality == DataQuality.THIN
    assert research.data_quality == DataQuality.THIN
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
        ThreeCompanyProvider(), fundamentals, enrichment_limit=2
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
    provider = EnrichedResearchProvider(
        CompanyEchoProvider(), fundamentals, enrichment_limit=2
    )
    eligible = make_company("ELIGIBLE")
    skipped = make_company("SKIPPED")

    provider.prepare_watchlist_enrichment((eligible,))
    enriched = provider.get_company_research(eligible)
    not_enriched = provider.get_company_research(skipped)

    assert enriched.financials.pe_ratio == 9.5
    assert not_enriched.financials.pe_ratio is None
    assert [company.ticker for company in fundamentals.requests] == ["ELIGIBLE"]


def test_enriched_provider_rejects_negative_enrichment_limit():
    with pytest.raises(ValueError, match="enrichment_limit must be at least 0"):
        EnrichedResearchProvider(BaseProvider(), StaticFundamentalsProvider(None), -1)


def test_enriched_provider_reports_watchlist_enrichment_diagnostics():
    base = BaseProvider()
    company = base.company
    snapshot = FundamentalsSnapshot(
        symbol="AUDIT.ST",
        financials=FinancialSnapshot(pe_ratio=9.5, data_quality=DataQuality.PARTIAL),
    )
    provider = EnrichedResearchProvider(
        base, StaticFundamentalsProvider(snapshot), enrichment_limit=3
    )

    provider.prepare_watchlist_enrichment(
        (company,),
        eligible_universe_size=20,
        cutoff_tie_count=4,
        cutoff_tie_excluded=2,
    )
    provider.get_company_research(company)
    check = provider.enrichment_source_check()

    assert check.status == "ok"
    assert "eligible=20" in check.detail
    assert "budget=3" in check.detail
    assert "selected=1" in check.detail
    assert "attempts=1" in check.detail
    assert "successful=1" in check.detail
    assert "cutoff ties=4 (2 excluded)" in check.detail
    assert provider.enrichment_stats()["candidate_keys"] == ("SE|KAR",)
