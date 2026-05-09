from openclaw.models import Company, CompanyResearch, DataQuality, FinancialSnapshot, ListingSegment
from openclaw.scoring import score_research


def make_research(**financial_overrides):
    financial_defaults = {
        "pe_ratio": 9.0,
        "price_to_book": 0.8,
        "net_cash_eur_m": 12.0,
        "one_year_return_pct": -35.0,
        "distance_from_52w_high_pct": -45.0,
        "average_daily_value_eur": 80_000,
        "data_quality": DataQuality.GOOD,
    }
    financials = FinancialSnapshot(**(financial_defaults | financial_overrides))
    company = Company(
        name="Hidden Value Oyj",
        ticker="HVO",
        country="FI",
        exchange="Nasdaq Helsinki",
        segment=ListingSegment.FIRST_NORTH,
        sector="Technology",
        market_cap_eur_m=90,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        catalysts=("New contract announced",),
        risks=("Low liquidity",),
        data_quality=financials.data_quality,
    )


def test_score_rewards_small_value_companies_with_catalysts():
    score = score_research(make_research())

    assert score.value > 0
    assert score.discovery > 0
    assert score.catalyst > 0
    assert score.total > 0
    assert "low P/E" in " ".join(score.reasons)


def test_score_penalizes_thin_data_quality():
    good = score_research(make_research(data_quality=DataQuality.GOOD))
    thin = score_research(make_research(data_quality=DataQuality.THIN))

    assert thin.data_quality_penalty > good.data_quality_penalty
    assert thin.total < good.total


def test_score_penalizes_expensive_unprofitable_profile():
    score = score_research(
        make_research(
            pe_ratio=80.0,
            price_to_book=8.0,
            net_cash_eur_m=-30.0,
            operating_margin_pct=-12.0,
        )
    )

    assert score.risk_penalty > 0
    assert score.total < 10
