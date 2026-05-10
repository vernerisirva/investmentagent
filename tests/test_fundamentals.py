import json

from investmentagent.fundamentals import (
    FundamentalsSnapshot,
    YahooFundamentalsProvider,
    yahoo_symbol_candidates,
)
from investmentagent.models import Company, DataQuality, ListingSegment


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
