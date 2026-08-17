import json
from collections import Counter
from urllib.parse import parse_qs, urlparse

import pytest

from investmentagent.models import DataQuality, ListingSegment
from investmentagent.providers import (
    FixtureResearchProvider,
    LiveNasdaqNordicProvider,
    NASDAQ_NORDIC_SCREENER_REQUESTS,
    _fetch_nasdaq_nordic_screener_payload,
    create_provider,
)
from investmentagent.scoring import score_research


LIVE_SAMPLE_CSV = """name,ticker,country,exchange,segment,sector,currency,isin
Nordic Value AB,NVAL,SE,Nasdaq Stockholm,main_market,Industrials,SEK,SE0000000001
First Growth Oyj,FGRO,FI,Nasdaq First North Growth Market,first_north,Software,EUR,FI0000000002
Ignored Denmark A/S,IGN,DK,Nasdaq Copenhagen,main_market,Industrials,DKK,DK0000000003
"""

LIVE_CAPITALIZED_HEADER_CSV = """Name,Symbol,Country,Exchange,Market,Sector,Currency
Capital Header AB,CHAB,SE,Nasdaq Stockholm,Main Market,Industrials,SEK
"""

LIVE_NASDAQ_SCREENER_RESPONSE = """{
  "source": "nasdaq_nordic_screener",
  "responses": [
    {
      "country": "SE",
      "exchange": "Nasdaq Stockholm",
      "segment": "main_market",
      "source_url": "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&market=STO&tableonly=false",
      "payload": {
        "data": {
          "instrumentListing": {
            "rows": [
              {
                "fullName": "Acast",
                "symbol": "ACAST",
                "currency": "SEK",
                "lastSalePrice": "34.90",
                "percentageChange": "+6.25%",
                "turnover": "10,116,648",
                "volume": "291,265",
                "sector": "Technology",
                "isin": "SE0015960935"
              },
              {
                "fullName": "Foreign Issuer Listed Stockholm",
                "symbol": "FIL",
                "currency": "DKK",
                "lastSalePrice": "12.00",
                "percentageChange": "+12.93%",
                "turnover": "2,500,000",
                "volume": "400,000",
                "sector": "Industrials",
                "isin": "DK0000000001"
              }
            ]
          }
        }
      }
    },
    {
      "country": "FI",
      "exchange": "Nasdaq First North Growth Market Finland",
      "segment": "first_north",
      "source_url": "https://api.nasdaq.com/api/nordic/screener/shares?category=FIRST_NORTH&market=HEL&tableonly=false",
      "payload": {
        "data": {
          "instrumentListing": {
            "rows": [
              {
                "fullName": "Aallon Group Oyj",
                "symbol": "AALLON",
                "currency": "EUR",
                "lastSalePrice": "9.22",
                "percentageChange": "-6.40%",
                "turnover": "3,010",
                "volume": "337",
                "sector": "Industrials",
                "isin": "FI4000369608"
              }
            ]
          }
        }
      }
    }
  ]
}"""

LIVE_DUPLICATE_TICKER_SCREENER_RESPONSE = """{
  "source": "nasdaq_nordic_screener",
  "responses": [
    {
      "country": "SE",
      "exchange": "Nasdaq Stockholm",
      "segment": "main_market",
      "payload": {
        "data": {
          "instrumentListing": {
            "rows": [
              {
                "fullName": "Same Symbol Sweden AB",
                "symbol": "SAME",
                "currency": "SEK",
                "lastSalePrice": "12.50",
                "percentageChange": "+1.50%",
                "turnover": "500,000",
                "volume": "40,000",
                "sector": "Technology",
                "isin": "SE0000000001"
              }
            ]
          }
        }
      }
    },
    {
      "country": "FI",
      "exchange": "Nasdaq Helsinki",
      "segment": "main_market",
      "payload": {
        "data": {
          "instrumentListing": {
            "rows": [
              {
                "fullName": "Same Symbol Finland Oyj",
                "symbol": "SAME",
                "currency": "EUR",
                "lastSalePrice": "7.75",
                "percentageChange": "+2.00%",
                "turnover": "750,000",
                "volume": "55,000",
                "sector": "Technology",
                "isin": "FI0000000002"
              }
            ]
          }
        }
      }
    }
  ]
}"""


HEALTHY_NASDAQ_COUNTS = {
    ("SE", "main_market"): 400,
    ("FI", "main_market"): 140,
    ("SE", "first_north"): 300,
    ("FI", "first_north"): 45,
}


def _nasdaq_coverage_payload(
    counts: dict[tuple[str, str], int] | None = None,
    *,
    omitted: set[tuple[str, str]] | None = None,
    row_overrides: dict[tuple[str, str], list | None] | None = None,
) -> str:
    counts = counts or HEALTHY_NASDAQ_COUNTS
    omitted = omitted or set()
    row_overrides = row_overrides or {}
    responses = []
    for request in NASDAQ_NORDIC_SCREENER_REQUESTS:
        key = (request["country"], request["listing_segment"])
        if key in omitted:
            continue
        segment_code = "M" if key[1] == "main_market" else "F"
        rows = [
            {
                "fullName": f"{key[0]} {segment_code} Company {index}",
                "symbol": f"{key[0]}{segment_code}{index:04d}",
                "currency": "SEK" if key[0] == "SE" else "EUR",
                "isin": f"{key[0]}{index:010d}",
            }
            for index in range(counts.get(key, 0))
        ]
        if key in row_overrides:
            rows = row_overrides[key]
        responses.append(
            {
                "country": request["country"],
                "exchange": request["exchange"],
                "segment": request["listing_segment"],
                "payload": {"data": {"instrumentListing": {"rows": rows}}},
            }
        )
    return json.dumps({"source": "nasdaq_nordic_screener", "responses": responses})


def _nasdaq_request_key(url: str) -> tuple[str, str]:
    params = parse_qs(urlparse(url).query)
    country = "SE" if params["market"] == ["STO"] else "FI"
    segment = (
        ListingSegment.MAIN_MARKET.value
        if params["category"] == ["MAIN_MARKET"]
        else ListingSegment.FIRST_NORTH.value
    )
    return country, segment


def _nasdaq_segment_response(key: tuple[str, str], count: int) -> str:
    segment_code = "M" if key[1] == ListingSegment.MAIN_MARKET.value else "F"
    rows = [
        {
            "fullName": f"{key[0]} {segment_code} Company {index}",
            "symbol": f"{key[0]}{segment_code}{index:04d}",
            "currency": "SEK" if key[0] == "SE" else "EUR",
            "isin": f"{key[0]}{index:010d}",
        }
        for index in range(count)
    ]
    return json.dumps({"data": {"instrumentListing": {"rows": rows}}})


def test_fixture_provider_filters_country_and_first_north():
    provider = FixtureResearchProvider()

    companies = provider.list_companies(countries=("FI",), include_first_north=True)

    assert companies
    assert all(company.country == "FI" for company in companies)
    assert any(company.segment.value == "first_north" for company in companies)


def test_fixture_provider_returns_research_with_evidence():
    provider = FixtureResearchProvider()
    company = provider.list_companies(countries=("SE",), include_first_north=True)[0]

    research = provider.get_research(company.ticker)

    assert research.company.ticker == company.ticker
    assert research.data_quality in {DataQuality.GOOD, DataQuality.PARTIAL, DataQuality.THIN}
    assert research.evidence


def test_source_checks_report_seed_data_available():
    provider = FixtureResearchProvider()

    checks = provider.source_checks()

    assert checks[0].name == "bundled seed data"
    assert checks[0].status == "ok"


def test_create_provider_defaults_to_fixture():
    provider = create_provider("fixture")

    assert isinstance(provider, FixtureResearchProvider)


def test_create_provider_returns_live_provider():
    provider = create_provider("live")

    assert isinstance(provider, LiveNasdaqNordicProvider)


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="provider must be 'fixture' or 'live'"):
        create_provider("unknown")


def test_live_provider_parses_companies_from_sample_payload():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies] == ["NVAL", "FGRO"]
    assert companies[0].country == "SE"
    assert companies[0].isin == "SE0000000001"
    assert companies[1].segment == ListingSegment.FIRST_NORTH


def test_live_provider_parses_capitalized_headers():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_CAPITALIZED_HEADER_CSV)

    companies = provider.list_companies(countries=("SE",), include_first_north=True)

    assert [company.ticker for company in companies] == ["CHAB"]
    assert companies[0].segment == ListingSegment.MAIN_MARKET


def test_live_provider_parses_nasdaq_nordic_screener_payload():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies] == ["ACAST", "FIL", "AALLON"]
    assert companies[0].name == "Acast"
    assert companies[0].country == "SE"
    assert companies[0].exchange == "Nasdaq Stockholm"
    assert companies[0].segment == ListingSegment.MAIN_MARKET
    assert companies[0].sector == "Technology"
    assert companies[0].isin == "SE0015960935"
    assert companies[1].country == "SE"
    assert companies[2].country == "FI"
    assert companies[2].segment == ListingSegment.FIRST_NORTH


def test_live_provider_skips_nasdaq_screener_segments_with_null_rows():
    payload = json.loads(LIVE_NASDAQ_SCREENER_RESPONSE)
    payload["responses"][0]["payload"]["data"]["instrumentListing"]["rows"] = None
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: json.dumps(payload))

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies] == ["AALLON"]
    assert provider.source_checks()[0].status == "error"


def test_live_provider_reports_healthy_complete_nasdaq_universe():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: _nasdaq_coverage_payload())

    check = provider.source_checks()[0]

    assert check.status == "ok"
    assert len(provider.list_companies()) == 885


def test_live_provider_rejects_severely_truncated_nasdaq_universe():
    counts = {
        ("SE", "main_market"): 14,
        ("FI", "main_market"): 1,
        ("SE", "first_north"): 10,
        ("FI", "first_north"): 1,
    }
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: _nasdaq_coverage_payload(counts)
    )

    check = provider.source_checks()[0]

    assert check.status == "error"
    assert "total 26 is below 700" in check.detail


def test_live_provider_rejects_nasdaq_universe_without_sweden():
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: _nasdaq_coverage_payload(
            omitted={("SE", "main_market"), ("SE", "first_north")}
        )
    )

    check = provider.source_checks()[0]

    assert check.status == "error"
    assert "SE=0" in check.detail
    assert "STO/main_market response is missing" in check.detail


def test_live_provider_rejects_nasdaq_universe_without_finland():
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: _nasdaq_coverage_payload(
            omitted={("FI", "main_market"), ("FI", "first_north")}
        )
    )

    check = provider.source_checks()[0]

    assert check.status == "error"
    assert "FI=0" in check.detail
    assert "HEL/main_market response is missing" in check.detail


@pytest.mark.parametrize("rows", [None, []])
def test_live_provider_rejects_null_or_empty_expected_segment(rows):
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: _nasdaq_coverage_payload(
            row_overrides={("FI", "first_north"): rows}
        )
    )

    check = provider.source_checks()[0]

    assert check.status == "error"
    assert "HEL/first_north" in check.detail
    assert "rows are null" in check.detail or "returned no rows" in check.detail


def test_live_provider_allows_normal_nasdaq_listing_fluctuations():
    counts = {
        ("SE", "main_market"): 380,
        ("FI", "main_market"): 130,
        ("SE", "first_north"): 280,
        ("FI", "first_north"): 35,
    }
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: _nasdaq_coverage_payload(counts)
    )

    assert provider.source_checks()[0].status == "ok"


def test_live_provider_source_diagnostics_include_universe_coverage():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: _nasdaq_coverage_payload())

    detail = provider.source_checks()[0].detail

    assert "total=885" in detail
    assert "SE=700" in detail
    assert "FI=185" in detail
    assert "STO/main_market=400" in detail
    assert "HEL/main_market=140" in detail
    assert "STO/first_north=300" in detail
    assert "HEL/first_north=45" in detail


def test_live_provider_fetches_nasdaq_nordic_screener_segments():
    fetched_urls: list[str] = []

    def fake_fetcher(url: str) -> str:
        fetched_urls.append(url)
        return '{"data":{"instrumentListing":{"rows":[]}}}'

    payload = _fetch_nasdaq_nordic_screener_payload(
        "https://api.nasdaq.com/api/nordic/screener/shares",
        fake_fetcher,
        retry_delays_seconds=(),
    )

    assert "nasdaq_nordic_screener" in payload
    assert any("market=STO" in url for url in fetched_urls)
    assert any("market=HEL" in url for url in fetched_urls)
    assert any("category=FIRST_NORTH" in url for url in fetched_urls)
    assert len(fetched_urls) == 4


def test_live_provider_retries_only_transiently_incomplete_nasdaq_segment():
    attempts: Counter[tuple[str, str]] = Counter()
    sleeps = []

    def fake_fetcher(url: str) -> str:
        key = _nasdaq_request_key(url)
        attempts[key] += 1
        count = HEALTHY_NASDAQ_COUNTS[key]
        if key == ("SE", ListingSegment.MAIN_MARKET.value) and attempts[key] < 3:
            count = 14
        return _nasdaq_segment_response(key, count)

    payload = _fetch_nasdaq_nordic_screener_payload(
        "https://api.nasdaq.com/api/nordic/screener/shares",
        fake_fetcher,
        retry_delays_seconds=(15.0, 45.0),
        sleeper=sleeps.append,
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: payload)
    responses = json.loads(payload)["responses"]

    assert provider.source_checks()[0].status == "ok"
    assert attempts[("SE", ListingSegment.MAIN_MARKET.value)] == 3
    assert all(
        attempts[key] == 1
        for key in HEALTHY_NASDAQ_COUNTS
        if key != ("SE", ListingSegment.MAIN_MARKET.value)
    )
    assert sleeps == [15.0, 45.0]
    assert responses[0]["fetch_attempts"] == 3
    assert responses[0]["last_fetch_issue"] is None


def test_live_provider_still_rejects_segment_incomplete_after_retries():
    attempts: Counter[tuple[str, str]] = Counter()
    sleeps = []

    def fake_fetcher(url: str) -> str:
        key = _nasdaq_request_key(url)
        attempts[key] += 1
        count = HEALTHY_NASDAQ_COUNTS[key]
        if key == ("SE", ListingSegment.MAIN_MARKET.value):
            count = 14
        return _nasdaq_segment_response(key, count)

    payload = _fetch_nasdaq_nordic_screener_payload(
        "https://api.nasdaq.com/api/nordic/screener/shares",
        fake_fetcher,
        retry_delays_seconds=(15.0, 45.0),
        sleeper=sleeps.append,
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: payload)
    check = provider.source_checks()[0]
    responses = json.loads(payload)["responses"]

    assert check.status == "error"
    assert "STO/main_market 14 is below 300" in check.detail
    assert attempts[("SE", ListingSegment.MAIN_MARKET.value)] == 3
    assert sleeps == [15.0, 45.0]
    assert responses[0]["fetch_attempts"] == 3
    assert responses[0]["last_fetch_issue"] == "14 parseable companies is below 300"


def test_live_provider_filters_first_north():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=False)

    assert [company.ticker for company in companies] == ["NVAL"]


def test_live_provider_returns_thin_research_with_evidence():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_SAMPLE_CSV)

    research = provider.get_research("FGRO")

    assert research.company.ticker == "FGRO"
    assert research.data_quality == DataQuality.THIN
    assert research.financials.data_quality == DataQuality.THIN
    assert research.risks == ("Sparse live-source data",)
    assert research.evidence


def test_live_provider_research_includes_market_signal_fields():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("ACAST")

    assert research.financials.price == 34.9
    assert research.financials.currency == "SEK"
    assert "Live price available from Nasdaq Nordic" in research.catalysts


def test_live_provider_research_adds_positive_momentum_signal():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("ACAST")

    assert "Positive intraday momentum (+6.25%)" in research.catalysts
    assert "High live turnover" in research.catalysts


def test_live_provider_research_adds_strong_momentum_and_high_turnover_signals():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("FIL")

    assert "Strong intraday momentum (+12.93%)" in research.catalysts
    assert "High live turnover" in research.catalysts


def test_live_provider_scores_stronger_live_signals_higher():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    stronger = score_research(provider.get_research("FIL"))
    weaker = score_research(provider.get_research("ACAST"))

    assert stronger.total > weaker.total


def test_live_provider_research_adds_selloff_and_liquidity_risks():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_NASDAQ_SCREENER_RESPONSE)

    research = provider.get_research("AALLON")

    assert "Sharp intraday selloff" in research.risks
    assert "Low live turnover" in research.risks


def test_live_provider_research_adds_extreme_spike_and_low_price_risks():
    payload = LIVE_NASDAQ_SCREENER_RESPONSE.replace("+6.25%", "+155.65%").replace(
        "34.90", "0.86"
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: payload)

    research = provider.get_research("ACAST")

    assert "Extreme intraday spike" in research.risks
    assert "Speculative low-price share" in research.risks


def test_live_provider_deduplicates_nasdaq_rows_by_ticker_and_country():
    payload = json.loads(LIVE_NASDAQ_SCREENER_RESPONSE)
    acast_row = dict(
        payload["responses"][0]["payload"]["data"]["instrumentListing"]["rows"][0]
    )
    acast_row["fullName"] = "Acast First North Duplicate"
    payload["responses"].append(
        {
            "country": "SE",
            "exchange": "Nasdaq First North Growth Market Sweden",
            "segment": "first_north",
            "source_url": (
                "https://api.nasdaq.com/api/nordic/screener/shares"
                "?category=FIRST_NORTH&market=STO&tableonly=false"
            ),
            "payload": {"data": {"instrumentListing": {"rows": [acast_row]}}},
        }
    )
    duplicate_payload = json.dumps(payload)
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: duplicate_payload)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)

    assert [company.ticker for company in companies].count("ACAST") == 1


def test_live_provider_returns_company_specific_research_for_duplicate_country_tickers():
    provider = LiveNasdaqNordicProvider(
        fetcher=lambda url: LIVE_DUPLICATE_TICKER_SCREENER_RESPONSE
    )

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)
    swedish = next(company for company in companies if company.country == "SE")
    finnish = next(company for company in companies if company.country == "FI")
    swedish_research = provider.get_company_research(swedish)
    finnish_research = provider.get_company_research(finnish)

    assert [company.ticker for company in companies] == ["SAME", "SAME"]
    assert swedish_research.company.name == "Same Symbol Sweden AB"
    assert swedish_research.financials.currency == "SEK"
    assert swedish_research.financials.price == 12.5
    assert finnish_research.company.name == "Same Symbol Finland Oyj"
    assert finnish_research.financials.currency == "EUR"
    assert finnish_research.financials.price == 7.75


def test_live_provider_ignores_malformed_market_signal_numbers():
    malformed_payload = LIVE_NASDAQ_SCREENER_RESPONSE.replace("34.90", "not-a-price").replace(
        "+6.25%", "n/a"
    )
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: malformed_payload)

    research = provider.get_research("ACAST")

    assert research.financials.price is None
    assert "Live price available from Nasdaq Nordic" not in research.catalysts
    assert not any("intraday momentum" in catalyst for catalyst in research.catalysts)


def test_live_provider_reports_malformed_payload_as_error():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: "<html>not csv</html>")

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)
    checks = provider.source_checks()

    assert companies == []
    assert checks[0].status == "error"
    assert "required listing columns" in checks[0].detail


def test_live_provider_reports_fetch_failures_in_source_checks():
    def failing_fetcher(url: str) -> str:
        raise OSError("network unavailable")

    provider = LiveNasdaqNordicProvider(fetcher=failing_fetcher)

    companies = provider.list_companies(countries=("SE", "FI"), include_first_north=True)
    checks = provider.source_checks()

    assert companies == []
    assert checks[0].name == "nasdaq nordic live data"
    assert checks[0].status == "error"
    assert "network unavailable" in checks[0].detail
