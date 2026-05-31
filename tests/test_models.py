from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    DeepDiveReport,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
)


def make_company() -> Company:
    return Company(
        name="Example AB",
        ticker="EXAB",
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.FIRST_NORTH,
    )


def make_research() -> CompanyResearch:
    return CompanyResearch(company=make_company(), financials=FinancialSnapshot())


def make_score() -> ScoreBreakdown:
    return ScoreBreakdown(
        value=10.0,
        discovery=10.0,
        catalyst=10.0,
        risk_penalty=0.0,
        data_quality_penalty=0.0,
        total=30.0,
    )


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


def test_financial_snapshot_accepts_valuation_proxy_inputs():
    snapshot = FinancialSnapshot(
        revenue_eur_m=120.0,
        book_value_eur_m=80.0,
        net_income_eur_m=12.0,
    )

    assert snapshot.revenue_eur_m == 120.0
    assert snapshot.book_value_eur_m == 80.0
    assert snapshot.net_income_eur_m == 12.0


def test_evidence_requires_label_and_url():
    evidence = Evidence(label="IR page", url="https://example.com/ir")

    assert evidence.label == "IR page"
    assert evidence.url == "https://example.com/ir"


def test_company_research_converts_mutable_collections_to_tuples():
    evidence = Evidence(label="IR page", url="https://example.com/ir")
    research = CompanyResearch(
        company=make_company(),
        financials=FinancialSnapshot(),
        catalysts=["New product"],
        risks=["Thin liquidity"],
        evidence=[evidence],
    )

    assert research.catalysts == ("New product",)
    assert research.risks == ("Thin liquidity",)
    assert research.evidence == (evidence,)
    assert isinstance(research.catalysts, tuple)
    assert isinstance(research.risks, tuple)
    assert isinstance(research.evidence, tuple)


def test_score_breakdown_converts_mutable_collections_to_tuples():
    score = ScoreBreakdown(
        value=10.0,
        discovery=10.0,
        catalyst=10.0,
        risk_penalty=2.0,
        data_quality_penalty=1.0,
        total=27.0,
        reasons=["Cheap valuation"],
        warnings=["Thin disclosure"],
    )

    assert score.reasons == ("Cheap valuation",)
    assert score.warnings == ("Thin disclosure",)
    assert isinstance(score.reasons, tuple)
    assert isinstance(score.warnings, tuple)


def test_deep_dive_report_converts_mutable_collections_to_tuples():
    report = DeepDiveReport(
        research=make_research(),
        score=make_score(),
        why_it_appeared=["High score"],
        valuation_view=["Looks inexpensive"],
        bull_case=["Margin expansion"],
        base_case=["Steady growth"],
        bear_case=["Demand slows"],
        next_manual_checks=["Read latest annual report"],
    )

    assert report.why_it_appeared == ("High score",)
    assert report.valuation_view == ("Looks inexpensive",)
    assert report.bull_case == ("Margin expansion",)
    assert report.base_case == ("Steady growth",)
    assert report.bear_case == ("Demand slows",)
    assert report.next_manual_checks == ("Read latest annual report",)
    assert isinstance(report.why_it_appeared, tuple)
    assert isinstance(report.valuation_view, tuple)
    assert isinstance(report.bull_case, tuple)
    assert isinstance(report.base_case, tuple)
    assert isinstance(report.bear_case, tuple)
    assert isinstance(report.next_manual_checks, tuple)
