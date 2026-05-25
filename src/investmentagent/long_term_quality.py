from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from investmentagent.models import CompanyResearch, DataQuality, ListingSegment


class LongTermQualityBucket(str, Enum):
    QUALITY_SMALL_CAP = "Quality small-cap candidate"
    FUNDAMENTAL_WATCHLIST = "Fundamental watchlist candidate"
    SPECULATIVE_MONITOR = "Speculative small-cap monitor"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


@dataclass(frozen=True)
class LongTermQualityProfile:
    quality_adjustment: float
    proof_penalty: float
    bucket: LongTermQualityBucket
    reasons: tuple[str, ...]
    proof_gaps: tuple[str, ...]
    thesis: str


def assess_long_term_quality(research: CompanyResearch) -> LongTermQualityProfile:
    financials = research.financials
    company = research.company
    reasons: list[str] = []
    proof_gaps: list[str] = []
    quality_adjustment = 0.0
    proof_penalty = 0.0

    if company.segment == ListingSegment.FIRST_NORTH:
        quality_adjustment += 5.0
        reasons.append("First North discovery opportunity")

    if financials.operating_margin_pct is not None and financials.operating_margin_pct > 0:
        quality_adjustment += 10.0
        reasons.append("Positive operating margin")
    elif financials.operating_margin_pct is not None and financials.operating_margin_pct < 0:
        proof_penalty += 14.0
        proof_gaps.append("Negative operating margin")
    else:
        proof_penalty += 8.0
        proof_gaps.append("No profitability signal")

    if financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0:
        quality_adjustment += 8.0
        reasons.append("Revenue growth")
    else:
        proof_penalty += 7.0
        proof_gaps.append("No growth signal")

    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        quality_adjustment += 7.0
        reasons.append("Net cash balance sheet")
    if financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        quality_adjustment += 5.0
        reasons.append("Conservative balance sheet")
    elif financials.debt_to_equity is not None and financials.debt_to_equity > 1.5:
        proof_penalty += 10.0
        proof_gaps.append("High debt/equity")

    has_valuation = any(
        metric is not None
        for metric in (
            financials.pe_ratio,
            financials.price_to_book,
            financials.ev_to_ebit,
        )
    )
    if _has_attractive_valuation(research):
        quality_adjustment += 8.0
        reasons.append("Attractive valuation support")
    elif has_valuation:
        quality_adjustment += 2.0
        reasons.append("Valuation data available")
    else:
        proof_penalty += 9.0
        proof_gaps.append("Missing valuation data")

    if company.business_description:
        quality_adjustment += 4.0
        reasons.append("Business description available")
    else:
        proof_penalty += 5.0
        proof_gaps.append("Missing business description")

    if financials.average_daily_value_eur is not None:
        if financials.average_daily_value_eur >= 100_000:
            quality_adjustment += 3.0
            reasons.append("Adequate liquidity")
        else:
            proof_penalty += 7.0
            proof_gaps.append("Thin liquidity")

    if _has_live_only_support(research) and not _has_durable_support(research):
        proof_penalty += 12.0
        proof_gaps.append("Only live-market support")

    if research.data_quality == DataQuality.THIN:
        proof_penalty += 8.0
        proof_gaps.append("Thin data quality")
    elif research.data_quality == DataQuality.PARTIAL and proof_gaps:
        proof_penalty += 3.0

    bucket = _bucket_for(quality_adjustment, proof_penalty, proof_gaps)
    return LongTermQualityProfile(
        quality_adjustment=round(quality_adjustment, 2),
        proof_penalty=round(proof_penalty, 2),
        bucket=bucket,
        reasons=tuple(dict.fromkeys(reasons)),
        proof_gaps=tuple(dict.fromkeys(proof_gaps)),
        thesis=_thesis_for(research, bucket, proof_gaps),
    )


def _has_attractive_valuation(research: CompanyResearch) -> bool:
    financials = research.financials
    return any(
        (
            financials.pe_ratio is not None and 0 < financials.pe_ratio <= 14,
            financials.price_to_book is not None and 0 < financials.price_to_book <= 1.5,
            financials.ev_to_ebit is not None and 0 < financials.ev_to_ebit <= 12,
        )
    )


def _has_durable_support(research: CompanyResearch) -> bool:
    financials = research.financials
    return any(
        (
            financials.operating_margin_pct is not None
            and financials.operating_margin_pct > 0,
            financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0,
            financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0,
            financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5,
            _has_attractive_valuation(research),
            bool(research.company.business_description),
        )
    )


def _has_live_only_support(research: CompanyResearch) -> bool:
    signals = tuple(item.lower() for item in (*research.catalysts, *research.risks))
    live_terms = (
        "live price available",
        "live turnover",
        "intraday momentum",
        "sparse live-source data",
    )
    return bool(signals) and all(
        any(term in signal for term in live_terms) for signal in signals
    )


def _bucket_for(
    quality_adjustment: float, proof_penalty: float, proof_gaps: list[str]
) -> LongTermQualityBucket:
    if proof_penalty >= 35 or len(proof_gaps) >= 5:
        return LongTermQualityBucket.INSUFFICIENT_EVIDENCE
    if quality_adjustment >= 32 and proof_penalty <= 8:
        return LongTermQualityBucket.QUALITY_SMALL_CAP
    if quality_adjustment >= 20 and proof_penalty <= 18:
        return LongTermQualityBucket.FUNDAMENTAL_WATCHLIST
    return LongTermQualityBucket.SPECULATIVE_MONITOR


def _thesis_for(
    research: CompanyResearch, bucket: LongTermQualityBucket, proof_gaps: list[str]
) -> str:
    name = research.company.name
    if bucket == LongTermQualityBucket.QUALITY_SMALL_CAP:
        return (
            f"{name} has multiple long-term quality signals for a small-cap research "
            "queue; verify valuation, reporting cadence, and liquidity before acting."
        )
    if bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST:
        return (
            f"{name} has enough fundamental evidence for manual research, but at "
            "least one proof gap should be checked before it becomes a high-priority "
            "idea."
        )
    if bucket == LongTermQualityBucket.SPECULATIVE_MONITOR:
        issue = proof_gaps[0].lower() if proof_gaps else "the evidence is incomplete"
        return (
            f"{name} is an interesting small-cap monitor, but the long-term case "
            f"needs more proof because {issue}."
        )
    return (
        f"{name} lacks enough durable evidence for a strong long-term thesis today; "
        "wait for clearer fundamentals, valuation, liquidity, or business evidence."
    )
