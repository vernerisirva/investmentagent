from openclaw import __version__
from openclaw.cli import app
from openclaw.models import Company, DataQuality, Evidence, FinancialSnapshot, ListingSegment


def test_package_exposes_version():
    assert __version__ == "0.1.0"


def test_console_script_target_exposes_app():
    assert app is not None


def test_company_normalizes_ticker_and_country():
    company = Company(
        name="Example AB",
        ticker=" exab ",
        country=" se ",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.FIRST_NORTH,
        sector="Industrials",
    )

    assert company.ticker == "EXAB"
    assert company.country == "SE"


def test_financial_snapshot_defaults_to_thin_quality():
    snapshot = FinancialSnapshot()

    assert snapshot.data_quality == DataQuality.THIN


def test_evidence_requires_label_and_url():
    evidence = Evidence(label="IR page", url="https://example.com/ir")

    assert evidence.label == "IR page"
    assert evidence.url == "https://example.com/ir"
