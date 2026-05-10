import pytest

from investmentagent.models import DataQuality, ListingSegment
from investmentagent.providers import (
    FixtureResearchProvider,
    LiveNasdaqNordicProvider,
    create_provider,
)


LIVE_SAMPLE_CSV = """name,ticker,country,exchange,segment,sector,currency,isin
Nordic Value AB,NVAL,SE,Nasdaq Stockholm,main_market,Industrials,SEK,SE0000000001
First Growth Oyj,FGRO,FI,Nasdaq First North Growth Market,first_north,Software,EUR,FI0000000002
Ignored Denmark A/S,IGN,DK,Nasdaq Copenhagen,main_market,Industrials,DKK,DK0000000003
"""

LIVE_CAPITALIZED_HEADER_CSV = """Name,Symbol,Country,Exchange,Market,Sector,Currency
Capital Header AB,CHAB,SE,Nasdaq Stockholm,Main Market,Industrials,SEK
"""


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
    assert companies[1].segment == ListingSegment.FIRST_NORTH


def test_live_provider_parses_capitalized_headers():
    provider = LiveNasdaqNordicProvider(fetcher=lambda url: LIVE_CAPITALIZED_HEADER_CSV)

    companies = provider.list_companies(countries=("SE",), include_first_north=True)

    assert [company.ticker for company in companies] == ["CHAB"]
    assert companies[0].segment == ListingSegment.MAIN_MARKET


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
