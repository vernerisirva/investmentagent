import pytest

from investmentagent.models import DataQuality
from investmentagent.providers import FixtureResearchProvider, create_provider


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


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="provider must be 'fixture' or 'live'"):
        create_provider("unknown")
