from investmentagent.long_term_quality import (
    LongTermGateTier,
    LongTermQualityBucket,
    assess_long_term_gate,
    assess_long_term_quality,
    assess_valuation_support,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    FinancialSnapshot,
    ListingSegment,
)


def make_research(
    *,
    ticker: str = "QUAL",
    segment: ListingSegment = ListingSegment.FIRST_NORTH,
    business_description: str | None = "Quality AB sells workflow software.",
    pe_ratio: float | None = 12.0,
    price_to_book: float | None = 1.4,
    net_cash_eur_m: float | None = 10.0,
    debt_to_equity: float | None = 0.2,
    revenue_growth_pct: float | None = 10.0,
    operating_margin_pct: float | None = 14.0,
    average_daily_value_eur: float | None = 250_000,
    catalysts: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
    data_quality: DataQuality = DataQuality.PARTIAL,
) -> CompanyResearch:
    return CompanyResearch(
        company=Company(
            name=f"{ticker} AB",
            ticker=ticker,
            country="SE",
            exchange="Nasdaq First North Growth Market Sweden",
            segment=segment,
            sector="Software",
            market_cap_eur_m=180,
            currency="SEK",
            business_description=business_description,
        ),
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            price_to_book=price_to_book,
            net_cash_eur_m=net_cash_eur_m,
            debt_to_equity=debt_to_equity,
            revenue_growth_pct=revenue_growth_pct,
            operating_margin_pct=operating_margin_pct,
            average_daily_value_eur=average_daily_value_eur,
            data_quality=data_quality,
        ),
        catalysts=catalysts,
        risks=risks,
        data_quality=data_quality,
    )


def test_quality_assessment_rewards_first_north_with_durable_fundamentals():
    profile = assess_long_term_quality(make_research())

    assert profile.bucket == LongTermQualityBucket.QUALITY_SMALL_CAP
    assert profile.quality_adjustment > 25
    assert profile.proof_penalty == 0
    assert "Quality small-cap candidate" in profile.bucket.value
    assert "Positive operating margin" in profile.reasons
    assert "Revenue growth" in profile.reasons
    assert "Conservative balance sheet" in profile.reasons
    assert "First North discovery opportunity" in profile.reasons


def test_quality_assessment_penalizes_first_north_without_long_term_proof():
    profile = assess_long_term_quality(
        make_research(
            ticker="SPEC",
            business_description=None,
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            debt_to_equity=None,
            revenue_growth_pct=None,
            operating_margin_pct=None,
            average_daily_value_eur=40_000,
            catalysts=("Strong intraday momentum (+18.0%)", "High live turnover"),
            risks=("Sparse live-source data",),
            data_quality=DataQuality.THIN,
        )
    )

    assert profile.bucket == LongTermQualityBucket.INSUFFICIENT_EVIDENCE
    assert profile.proof_penalty >= 30
    assert "Missing valuation data" in profile.proof_gaps
    assert "No profitability signal" in profile.proof_gaps
    assert "No growth signal" in profile.proof_gaps
    assert "Thin liquidity" in profile.proof_gaps
    assert "Only live-market support" in profile.proof_gaps


def test_quality_assessment_labels_speculative_monitor_when_some_proof_exists():
    profile = assess_long_term_quality(
        make_research(
            ticker="MON",
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            debt_to_equity=0.4,
            revenue_growth_pct=4.0,
            operating_margin_pct=None,
            average_daily_value_eur=120_000,
            data_quality=DataQuality.PARTIAL,
        )
    )

    assert profile.bucket == LongTermQualityBucket.SPECULATIVE_MONITOR
    assert "Missing valuation data" in profile.proof_gaps
    assert "No profitability signal" in profile.proof_gaps
    assert profile.quality_adjustment > 0


def test_quality_assessment_flags_live_only_support_despite_unrelated_risk():
    profile = assess_long_term_quality(
        make_research(
            ticker="LIVE",
            business_description=None,
            pe_ratio=None,
            price_to_book=None,
            net_cash_eur_m=None,
            debt_to_equity=None,
            revenue_growth_pct=None,
            operating_margin_pct=None,
            average_daily_value_eur=40_000,
            catalysts=("Strong intraday momentum (+18.0%)",),
            risks=("Low liquidity",),
            data_quality=DataQuality.THIN,
        )
    )

    assert "Only live-market support" in profile.proof_gaps


def test_quality_assessment_flags_missing_liquidity_data_for_strong_company():
    profile = assess_long_term_quality(
        make_research(average_daily_value_eur=None)
    )

    assert "Missing liquidity data" in profile.proof_gaps
    assert profile.proof_penalty > 0
    assert profile.bucket != LongTermQualityBucket.QUALITY_SMALL_CAP


def test_valuation_support_uses_market_cap_to_sales_proxy():
    research = make_research(
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=None,
    )
    research = CompanyResearch(
        company=Company(
            name=research.company.name,
            ticker=research.company.ticker,
            country=research.company.country,
            exchange=research.company.exchange,
            segment=research.company.segment,
            sector=research.company.sector,
            market_cap_eur_m=180.0,
            currency=research.company.currency,
            business_description=research.company.business_description,
        ),
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            debt_to_equity=0.2,
            revenue_growth_pct=10.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    support = assess_valuation_support(research)

    assert support.has_support is True
    assert support.is_attractive is True
    assert support.primary_kind == "market_cap_to_sales"
    assert support.primary_value == 1.5
    assert "Market cap/sales is 1.5x" in support.summary


def test_high_quality_company_with_proxy_passes_high_conviction_gate():
    research = make_research(
        pe_ratio=None,
        price_to_book=None,
        net_cash_eur_m=12.0,
    )
    research = CompanyResearch(
        company=Company(
            name=research.company.name,
            ticker=research.company.ticker,
            country=research.company.country,
            exchange=research.company.exchange,
            segment=research.company.segment,
            sector=research.company.sector,
            market_cap_eur_m=180.0,
            currency=research.company.currency,
            business_description=research.company.business_description,
        ),
        financials=FinancialSnapshot(
            revenue_eur_m=120.0,
            net_cash_eur_m=12.0,
            debt_to_equity=0.2,
            revenue_growth_pct=10.0,
            operating_margin_pct=14.0,
            average_daily_value_eur=250_000,
            data_quality=DataQuality.PARTIAL,
        ),
        data_quality=DataQuality.PARTIAL,
    )

    decision = assess_long_term_gate(research)

    assert decision.tier == LongTermGateTier.HIGH_CONVICTION
    assert decision.durable_anchor_count >= 4
    assert decision.severe_proof_gap_count == 0
    assert "valuation support available" in decision.reasons


def test_negative_margin_company_is_demoted_by_gate():
    decision = assess_long_term_gate(
        make_research(
            operating_margin_pct=-8.0,
            revenue_growth_pct=20.0,
            pe_ratio=8.0,
            price_to_book=1.0,
            average_daily_value_eur=250_000,
        )
    )

    assert decision.tier != LongTermGateTier.HIGH_CONVICTION
    assert "negative operating margin" in decision.blockers
