from __future__ import annotations

from openclaw.models import CompanyResearch, DataQuality, ListingSegment, ScoreBreakdown


DATA_QUALITY_PENALTIES = {
    DataQuality.GOOD: 0.0,
    DataQuality.PARTIAL: 7.0,
    DataQuality.THIN: 14.0,
}


def score_research(research: CompanyResearch) -> ScoreBreakdown:
    financials = research.financials
    company = research.company
    reasons: list[str] = []
    warnings: list[str] = []

    value = 0.0
    if financials.pe_ratio is not None and financials.pe_ratio <= 12:
        value += 20.0
        reasons.append(f"low P/E ({financials.pe_ratio:g})")
    if financials.price_to_book is not None and financials.price_to_book <= 1.2:
        value += 15.0
        reasons.append("low P/B")
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        value += 10.0
        reasons.append("net cash balance sheet")

    discovery = 0.0
    if company.market_cap_eur_m is not None and company.market_cap_eur_m <= 500:
        discovery += 15.0
        reasons.append("small market cap")
    if company.segment == ListingSegment.FIRST_NORTH:
        discovery += 10.0
        reasons.append("First North listing")
    if financials.one_year_return_pct is not None and financials.one_year_return_pct <= -25:
        discovery += 8.0
        reasons.append("one-year underperformance")
    if (
        financials.distance_from_52w_high_pct is not None
        and financials.distance_from_52w_high_pct <= -35
    ):
        discovery += 7.0
        reasons.append("far below 52-week high")

    catalyst = min(len(research.catalysts) * 8.0, 24.0)
    if catalyst:
        reasons.append(f"{len(research.catalysts)} catalyst(s)")

    risk_penalty = 0.0
    if (
        financials.average_daily_value_eur is not None
        and financials.average_daily_value_eur < 100_000
    ):
        risk_penalty += 8.0
        warnings.append("thin liquidity")
    if financials.debt_to_equity is not None and financials.debt_to_equity > 1.5:
        risk_penalty += 8.0
        warnings.append("high debt/equity")
    if financials.operating_margin_pct is not None and financials.operating_margin_pct < 0:
        risk_penalty += 10.0
        warnings.append("negative operating margin")
    if financials.pe_ratio is not None and financials.pe_ratio > 40:
        risk_penalty += 10.0
        warnings.append("high P/E")
    if financials.price_to_book is not None and financials.price_to_book > 5:
        risk_penalty += 8.0
        warnings.append("high P/B")

    risk_penalty += min(len(research.risks) * 3.0, 15.0)
    if research.risks:
        warnings.append(f"{len(research.risks)} stated risk(s)")

    data_quality_penalty = DATA_QUALITY_PENALTIES[research.data_quality]
    if data_quality_penalty:
        warnings.append(f"{research.data_quality.value} data quality")

    total = value + discovery + catalyst - risk_penalty - data_quality_penalty

    return ScoreBreakdown(
        value=round(value, 2),
        discovery=round(discovery, 2),
        catalyst=round(catalyst, 2),
        risk_penalty=round(risk_penalty, 2),
        data_quality_penalty=round(data_quality_penalty, 2),
        total=round(total, 2),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
