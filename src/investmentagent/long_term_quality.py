from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from investmentagent.models import CompanyResearch, DataQuality, ListingSegment


class LongTermQualityBucket(str, Enum):
    QUALITY_SMALL_CAP = "Quality small-cap candidate"
    FUNDAMENTAL_WATCHLIST = "Fundamental watchlist candidate"
    SPECULATIVE_MONITOR = "Speculative small-cap monitor"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


class LongTermGateTier(str, Enum):
    HIGH_CONVICTION = "High-conviction candidate"
    FUNDAMENTAL_WATCHLIST = "Fundamental watchlist"
    SPECULATIVE_MONITOR = "Speculative monitor"
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"


@dataclass(frozen=True)
class LongTermQualityProfile:
    quality_adjustment: float
    proof_penalty: float
    bucket: LongTermQualityBucket
    reasons: tuple[str, ...]
    proof_gaps: tuple[str, ...]
    thesis: str


@dataclass(frozen=True)
class ValuationSupport:
    has_support: bool
    is_attractive: bool
    primary_kind: str | None
    primary_value: float | None
    summary: str


@dataclass(frozen=True)
class LongTermGateDecision:
    tier: LongTermGateTier
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    durable_anchor_count: int
    severe_proof_gap_count: int
    valuation: ValuationSupport


SEVERE_PROOF_GAPS = {
    "No profitability signal",
    "Negative operating margin",
    "High debt/equity",
    "Thin data quality",
    "Missing business description",
    "Missing liquidity data",
}


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

    valuation = assess_valuation_support(research)
    if valuation.is_attractive:
        quality_adjustment += 8.0
        reasons.append("Attractive valuation support")
    elif valuation.has_support:
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
    else:
        proof_penalty += 6.0
        proof_gaps.append("Missing liquidity data")

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


def assess_valuation_support(research: CompanyResearch) -> ValuationSupport:
    financials = research.financials
    direct_metrics = (
        ("pe_ratio", financials.pe_ratio, 14.0, "P/E"),
        ("price_to_book", financials.price_to_book, 1.5, "Price/book"),
        ("ev_to_ebit", financials.ev_to_ebit, 12.0, "EV/EBIT"),
    )
    for kind, value, threshold, label in direct_metrics:
        if value is None or value <= 0:
            continue
        return ValuationSupport(
            has_support=True,
            is_attractive=value <= threshold,
            primary_kind=kind,
            primary_value=round(value, 2),
            summary=f"{label} is {value:g}.",
        )

    proxy = _valuation_proxy(research)
    if proxy is not None:
        return proxy

    return ValuationSupport(
        has_support=False,
        is_attractive=False,
        primary_kind=None,
        primary_value=None,
        summary="No valuation metric or proxy is available.",
    )


def assess_long_term_gate(research: CompanyResearch) -> LongTermGateDecision:
    quality = assess_long_term_quality(research)
    valuation = assess_valuation_support(research)
    durable_anchors = _durable_anchors(research, valuation)
    severe_gaps = tuple(gap for gap in quality.proof_gaps if gap in SEVERE_PROOF_GAPS)
    blockers = [_signal_key(gap) for gap in severe_gaps]
    reasons = list(durable_anchors)

    if valuation.has_support:
        reasons.append("valuation support available")
    else:
        blockers.append("missing valuation support")

    if quality.bucket == LongTermQualityBucket.QUALITY_SMALL_CAP:
        tier = LongTermGateTier.HIGH_CONVICTION
    elif (
        quality.bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST
        and len(durable_anchors) >= 3
    ):
        tier = LongTermGateTier.HIGH_CONVICTION
    elif quality.bucket == LongTermQualityBucket.FUNDAMENTAL_WATCHLIST:
        tier = LongTermGateTier.FUNDAMENTAL_WATCHLIST
    elif quality.bucket == LongTermQualityBucket.SPECULATIVE_MONITOR:
        tier = LongTermGateTier.SPECULATIVE_MONITOR
    else:
        tier = LongTermGateTier.INSUFFICIENT_EVIDENCE

    if tier == LongTermGateTier.HIGH_CONVICTION and (
        blockers or len(durable_anchors) < 2 or not valuation.has_support
    ):
        tier = LongTermGateTier.FUNDAMENTAL_WATCHLIST

    return LongTermGateDecision(
        tier=tier,
        reasons=tuple(dict.fromkeys(reasons)),
        blockers=tuple(dict.fromkeys(blockers)),
        durable_anchor_count=len(durable_anchors),
        severe_proof_gap_count=len(severe_gaps),
        valuation=valuation,
    )


def _has_attractive_valuation(research: CompanyResearch) -> bool:
    return assess_valuation_support(research).is_attractive


def _valuation_proxy(research: CompanyResearch) -> ValuationSupport | None:
    company = research.company
    financials = research.financials
    market_cap = company.market_cap_eur_m
    if market_cap is None or market_cap <= 0:
        return None

    if financials.revenue_eur_m is not None and financials.revenue_eur_m > 0:
        value = round(market_cap / financials.revenue_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value <= 2.0,
            primary_kind="market_cap_to_sales",
            primary_value=value,
            summary=f"Market cap/sales is {value:g}x.",
        )
    if financials.book_value_eur_m is not None and financials.book_value_eur_m > 0:
        value = round(market_cap / financials.book_value_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value <= 1.5,
            primary_kind="market_cap_to_book",
            primary_value=value,
            summary=f"Market cap/book value is {value:g}x.",
        )
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        value = round((financials.net_cash_eur_m / market_cap) * 100, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=value >= 20.0,
            primary_kind="net_cash_to_market_cap",
            primary_value=value,
            summary=f"Net cash equals {value:g}% of market cap.",
        )
    if financials.net_income_eur_m is not None and financials.net_income_eur_m > 0:
        pe_ratio = round(market_cap / financials.net_income_eur_m, 2)
        return ValuationSupport(
            has_support=True,
            is_attractive=pe_ratio <= 14.0,
            primary_kind="earnings_yield_pe",
            primary_value=pe_ratio,
            summary=f"Implied P/E is {pe_ratio:g}.",
        )
    return None


def _durable_anchors(
    research: CompanyResearch, valuation: ValuationSupport
) -> tuple[str, ...]:
    financials = research.financials
    anchors: list[str] = []
    if (
        financials.operating_margin_pct is not None
        and financials.operating_margin_pct > 0
    ):
        anchors.append("positive operating margin")
    if financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0:
        anchors.append("revenue growth")
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        anchors.append("net cash balance sheet")
    if financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        anchors.append("conservative balance sheet")
    if (
        financials.average_daily_value_eur is not None
        and financials.average_daily_value_eur >= 100_000
    ):
        anchors.append("adequate liquidity")
    if valuation.is_attractive:
        anchors.append("attractive valuation support")
    elif valuation.has_support:
        anchors.append("valuation data available")
    return tuple(dict.fromkeys(anchors))


def _signal_key(value: str) -> str:
    return value.strip().lower()


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
    signals = tuple(item.lower() for item in research.catalysts)
    live_terms = (
        "live price available",
        "live turnover",
        "intraday momentum",
        "sparse live-source data",
    )
    return any(
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
