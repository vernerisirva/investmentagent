from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from investmentagent.long_term_quality import (
    LongTermGateTier,
    assess_long_term_gate,
    assess_long_term_quality,
    assess_valuation_support,
)
from investmentagent.report_comparisons import (
    ALL_ELIGIBLE,
    LISTING_PEERS,
    PEER_MINIMUM_OBSERVATIONS,
    IdeaComparison,
    MetricComparison,
    PeerStat,
    ReportComparison,
    relative_summary,
)
from investmentagent.models import (
    Company,
    DataQuality,
    DeepDiveReport,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)


DISCLAIMER = "Research triage only. Not financial advice."
LONG_TERM_TIER_HEADINGS = {
    LongTermGateTier.HIGH_CONVICTION: "High-Conviction Candidates",
    LongTermGateTier.FUNDAMENTAL_WATCHLIST: "Fundamental Watchlist",
    LongTermGateTier.SPECULATIVE_MONITOR: "Speculative Monitors",
    LongTermGateTier.INSUFFICIENT_EVIDENCE: "Insufficient Evidence",
}


@dataclass(frozen=True)
class _ConvictionComponent:
    name: str
    score: int
    view: str


@dataclass(frozen=True)
class _LongTermConviction:
    bucket: str
    thesis: str
    components: tuple[_ConvictionComponent, ...]


def render_watchlist_text(items: list[WatchlistItem]) -> str:
    lines = [DISCLAIMER, "", "Watchlist"]

    for item in items:
        company = item.research.company
        lines.extend(
            [
                "",
                f"#{item.rank} {company.name} ({company.ticker})",
                (
                    f"{company.country} | {company.exchange} | "
                    f"{_stringify(company.segment)}"
                ),
                f"Presentation: {_company_presentation(item)}",
                f"Score: {item.score.total:g}",
                f"Reasons: {_joined(item.score.reasons)}",
                f"Risks: {_joined_public_risks((*item.research.risks, *item.score.warnings))}",
                f"Data quality: {_stringify(item.research.data_quality)}",
                "Evidence:",
            ]
        )
        lines.extend(_evidence_lines(item.research.evidence))

    return "\n".join(lines)


def render_watchlist_json(items: list[WatchlistItem]) -> str:
    payload = {
        "disclaimer": DISCLAIMER,
        "items": _watchlist_items_payload(items),
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)


def render_watchlist_report_json(
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks
) -> str:
    strategy = str(metadata.get("strategy") or "").strip().lower()
    payload = {
        "disclaimer": DISCLAIMER,
        "metadata": metadata,
        "source_checks": [_source_check_payload(check) for check in source_checks],
        "items": _watchlist_items_payload(items, strategy=strategy),
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)


def render_watchlist_report_markdown(
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks,
    comparison: ReportComparison | None = None, *, comparison_error: str | None = None,
) -> str:
    strategy = str(metadata.get("strategy") or "").strip().lower()
    subtitle = _watchlist_report_subtitle(strategy)
    if comparison is not None:
        return _render_compared_watchlist_markdown(
            items, metadata, source_checks, comparison, strategy, subtitle
        )
    notice = (
        [
            "> Decision-time peer comparisons are unavailable for this run "
            f"({comparison_error}); the ranking and selection are unaffected.",
            "",
        ]
        if comparison_error
        else []
    )
    lines = [
        f"# {_watchlist_report_title(strategy)}",
        "",
        f"> {DISCLAIMER}",
        "",
        *notice,
        *(["_" + subtitle + "_", ""] if subtitle else []),
        "## Metadata",
        *_metadata_lines(metadata),
        "",
        "## Source Checks",
        *[
            f"- {check.name}: {check.status} - {check.detail}"
            for check in source_checks
        ],
        "",
        "## Watchlist",
        "",
        *_watchlist_markdown_sections(items, strategy),
    ]
    return "\n".join(lines)


def render_global_ai_report_markdown(report) -> str:
    lines = [
        "# InvestmentAgent Global AI Top 5",
        "",
        f"> {DISCLAIMER}",
        "",
        (
            "_Long-term AI candidates ranked by valuation discipline, quality, "
            "growth, AI relevance, and risk._"
        ),
        "",
        "## Metadata",
        *_metadata_lines(report.metadata),
        "",
        "## Source Checks",
        *[
            f"- {check.name}: {check.status} - {check.detail}"
            for check in report.source_checks
        ],
        "",
        "## Top 5 Global AI Candidates",
        "",
    ]
    if not report.items:
        lines.append(
            "_No global AI candidates could be ranked with the current data source._"
        )
        return "\n".join(lines)

    lines.extend(_global_ai_item_markdown_sections(report.items))
    return "\n".join(lines)


def render_global_ai_report_json(report) -> str:
    payload = {
        "disclaimer": DISCLAIMER,
        "metadata": report.metadata,
        "source_checks": [
            _source_check_payload(check) for check in report.source_checks
        ],
        "items": [_global_ai_item_payload(item) for item in report.items],
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)


def _watchlist_report_title(strategy: str) -> str:
    if strategy == "trading":
        return "InvestmentAgent Trading Ideas"
    if strategy == "long-term":
        return "InvestmentAgent Long-Term Investment Ideas"
    return "InvestmentAgent Watchlist"


def _watchlist_report_subtitle(strategy: str) -> str:
    if strategy == "trading":
        return "Short-term setup candidates based on momentum, liquidity, and catalysts."
    if strategy == "long-term":
        return (
            "Longer-horizon candidates based on business quality, valuation, growth, "
            "balance sheet, and risk."
        )
    return ""


def render_deep_dive_json(report: DeepDiveReport) -> str:
    payload = {
        "disclaimer": DISCLAIMER,
        "company": _company_payload(report.research.company),
        "financials": _financials_payload(report.research.financials),
        "score": _score_payload(report.score),
        "business_summary": report.business_summary,
        "why_it_appeared": list(report.why_it_appeared),
        "valuation_view": list(report.valuation_view),
        "catalysts": list(report.research.catalysts),
        "risks": list(report.research.risks),
        "bull_case": list(report.bull_case),
        "base_case": list(report.base_case),
        "bear_case": list(report.bear_case),
        "next_manual_checks": list(report.next_manual_checks),
        "evidence": [_evidence_payload(evidence) for evidence in report.research.evidence],
        "data_quality": _stringify(report.research.data_quality),
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)


def render_deep_dive_text(report: DeepDiveReport) -> str:
    company = report.research.company
    lines = [
        DISCLAIMER,
        "",
        f"{company.name} ({company.ticker}) deep dive",
        f"{company.country} | {company.exchange} | {_stringify(company.segment)}",
        "",
        "Business summary",
        report.business_summary or "No business summary is available.",
        "",
        f"Score: {report.score.total:g}",
        f"Data quality: {_stringify(report.research.data_quality)}",
        "",
        "Why appeared",
        *_bullet_lines(report.why_it_appeared),
        "",
        "Valuation",
        *_bullet_lines(report.valuation_view),
        "",
        "Catalysts",
        *_bullet_lines(report.research.catalysts),
        "",
        "Bull case",
        *_bullet_lines(report.bull_case),
        "",
        "Base case",
        *_bullet_lines(report.base_case),
        "",
        "Bear case",
        *_bullet_lines(report.bear_case),
        "",
        "Next manual checks",
        *_bullet_lines(report.next_manual_checks),
        "",
        "Evidence",
        *_evidence_lines(report.research.evidence),
    ]
    return "\n".join(lines)


def _company_payload(company: Company) -> dict[str, Any]:
    return {
        "name": company.name,
        "ticker": company.ticker,
        "country": company.country,
        "isin": company.isin,
        "exchange": company.exchange,
        "segment": _stringify(company.segment),
        "sector": company.sector,
        "market_cap_eur_m": company.market_cap_eur_m,
        "currency": company.currency,
        "ir_url": company.ir_url,
        "business_description": company.business_description,
    }


def _watchlist_items_payload(
    items: list[WatchlistItem], strategy: str = ""
) -> list[dict[str, Any]]:
    payloads = []
    for item in items:
        payload = {
            "rank": item.rank,
            "company": _company_payload(item.research.company),
            "company_presentation": _company_presentation(item),
            "financials": _financials_payload(item.research.financials),
            "score": _score_payload(item.score),
            "risks": list(item.research.risks),
            "catalysts": list(item.research.catalysts),
            "evidence": [_evidence_payload(evidence) for evidence in item.research.evidence],
            "data_quality": _stringify(item.research.data_quality),
        }
        if strategy == "long-term":
            payload["long_term_conviction"] = _long_term_conviction_payload(item)
            payload["long_term_gate"] = _long_term_gate_payload(item)
        payloads.append(payload)
    return payloads


def _financials_payload(financials: FinancialSnapshot) -> dict[str, Any]:
    return {
        "price": financials.price,
        "currency": financials.currency,
        "pe_ratio": financials.pe_ratio,
        "price_to_book": financials.price_to_book,
        "ev_to_ebit": financials.ev_to_ebit,
        "revenue_eur_m": financials.revenue_eur_m,
        "book_value_eur_m": financials.book_value_eur_m,
        "net_income_eur_m": financials.net_income_eur_m,
        "net_cash_eur_m": financials.net_cash_eur_m,
        "debt_to_equity": financials.debt_to_equity,
        "revenue_growth_pct": financials.revenue_growth_pct,
        "operating_margin_pct": financials.operating_margin_pct,
        "one_year_return_pct": financials.one_year_return_pct,
        "distance_from_52w_high_pct": financials.distance_from_52w_high_pct,
        "average_daily_value_eur": financials.average_daily_value_eur,
        "data_quality": _stringify(financials.data_quality),
        "observations": [
            _financial_observation_payload(observation)
            for observation in financials.observations
        ],
    }


def _financial_observation_payload(
    observation: FinancialObservation,
) -> dict[str, Any]:
    return {
        "canonical_field": observation.canonical_field,
        "normalized_value": observation.normalized_value,
        "provider": observation.provider,
        "source_metric": observation.source_metric,
        "as_of": observation.as_of,
        "reporting_period": observation.reporting_period,
        "period_type": observation.period_type,
        "original_currency": observation.original_currency,
        "normalized_currency": observation.normalized_currency,
        "is_derived": observation.is_derived,
        "derivation": observation.derivation,
        "confidence": observation.confidence,
    }


def _score_payload(score: ScoreBreakdown) -> dict[str, Any]:
    return {
        "value": score.value,
        "discovery": score.discovery,
        "catalyst": score.catalyst,
        "risk_penalty": score.risk_penalty,
        "data_quality_penalty": score.data_quality_penalty,
        "total": score.total,
        "reasons": list(score.reasons),
        "warnings": list(score.warnings),
    }


def _evidence_payload(evidence: Evidence) -> dict[str, str | None]:
    return {
        "label": evidence.label,
        "url": evidence.url,
        "source": evidence.source,
        "timestamp": evidence.timestamp,
    }


def _source_check_payload(check) -> dict[str, str]:
    return {"name": check.name, "status": check.status, "detail": check.detail}


def _global_ai_item_payload(item) -> dict[str, Any]:
    return {
        "rank": item.rank,
        "company": _company_payload(item.research.company),
        "ai_category": item.entry.ai_category,
        "ai_thesis": item.entry.ai_thesis,
        "financials": _financials_payload(item.research.financials),
        "score": _global_ai_score_payload(item.score),
        "valuation_summary": item.valuation_summary,
        "quality_summary": item.quality_summary,
        "growth_summary": item.growth_summary,
        "risk_flags": list(item.risk_flags),
        "evidence": [
            _evidence_payload(evidence) for evidence in item.research.evidence
        ],
        "data_quality": _stringify(item.research.data_quality),
    }


def _global_ai_score_payload(score) -> dict[str, Any]:
    return {
        "valuation": score.valuation,
        "quality": score.quality,
        "growth": score.growth,
        "ai_relevance": score.ai_relevance,
        "risk_penalty": score.risk_penalty,
        "data_quality_penalty": score.data_quality_penalty,
        "total": score.total,
        "reasons": list(score.reasons),
        "warnings": list(score.warnings),
    }


def _global_ai_item_markdown_sections(items) -> list[str]:
    lines: list[str] = []
    for item in items:
        company = item.research.company
        lines.extend(
            [
                f"### #{item.rank} {company.name} ({company.ticker})",
                f"`{company.country}` | {company.exchange} | `{item.entry.ai_category}`",
                "",
                f"**AI thesis:** {item.entry.ai_thesis}",
                f"**Score:** {item.score.total:g}",
                f"**Valuation:** {item.valuation_summary}",
                f"**Quality:** {item.quality_summary}",
                f"**Growth:** {item.growth_summary}",
                f"**Data quality:** {_stringify(item.research.data_quality)}",
                "",
                "#### Reasons",
                *_bullet_lines(item.score.reasons),
                "",
                "#### Risks",
                *_bullet_lines(item.risk_flags),
                "",
                "#### Evidence",
                *_markdown_evidence_lines(item.research.evidence),
                "",
            ]
        )
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _watchlist_markdown_sections(
    items: list[WatchlistItem], strategy: str = ""
) -> list[str]:
    if strategy == "long-term":
        return _long_term_markdown_sections(items)
    return _watchlist_item_markdown_sections(items, strategy)


def _watchlist_item_markdown_sections(
    items: list[WatchlistItem], strategy: str = ""
) -> list[str]:
    lines: list[str] = []
    for item in items:
        company = item.research.company
        lines.extend(
            [
                f"## #{item.rank} {company.name} ({company.ticker})",
                "",
                (
                    f"`{company.country}` | {company.exchange} | "
                    f"`{_stringify(company.segment)}`"
                ),
                "",
                f"**What the company does:** {_company_description(item)}",
                "",
                f"**Score:** {item.score.total:g}",
                f"**Data quality:** {_stringify(item.research.data_quality)}",
                "",
            ]
        )
        if strategy == "long-term":
            lines.extend(_long_term_conviction_lines(item))
        lines.extend(
            [
                "### Reasons",
                *_public_reason_lines(item.score.reasons),
                "",
                "### Risks",
                *_public_risk_lines((*item.research.risks, *item.score.warnings)),
                "",
                "### Evidence",
                *_markdown_evidence_lines(item.research.evidence),
                "",
            ]
        )
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _long_term_markdown_sections(items: list[WatchlistItem]) -> list[str]:
    lines: list[str] = []
    research_tiers = {
        LongTermGateTier.HIGH_CONVICTION,
        LongTermGateTier.FUNDAMENTAL_WATCHLIST,
    }
    if not any(
        assess_long_term_gate(item.research).tier in research_tiers
        for item in items
    ):
        lines.extend(
            [
                (
                    "_No long-term research candidates passed the gate today. "
                    "Rows below are speculative monitors or evidence-audit rows, "
                    "not primary long-term investment ideas._"
                ),
                "",
            ]
        )

    for tier, heading in LONG_TERM_TIER_HEADINGS.items():
        tier_items = [
            item for item in items if assess_long_term_gate(item.research).tier == tier
        ]
        if not tier_items:
            continue
        lines.extend([f"## {heading}", ""])
        if tier == LongTermGateTier.SPECULATIVE_MONITOR:
            lines.extend(
                [
                    "_These are not primary long-term investment ideas; they need "
                    "valuation or stronger proof before promotion._",
                    "",
                ]
            )
        lines.extend(_watchlist_item_markdown_sections(tier_items, "long-term"))
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _long_term_conviction_lines(item: WatchlistItem) -> list[str]:
    conviction = _long_term_conviction(item)
    lines = [
        "### Long-Term Conviction",
        f"**Bucket:** {conviction.bucket}",
        f"**Thesis:** {conviction.thesis}",
        "",
        "| Component | Score | View |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {_table_cell(component.name)} | {component.score}/5 | "
        f"{_table_cell(component.view)} |"
        for component in conviction.components
    )
    lines.append("")
    return lines


def _long_term_conviction(item: WatchlistItem) -> _LongTermConviction:
    components = (
        _business_quality_component(item),
        _valuation_component(item),
        _growth_component(item),
        _balance_sheet_component(item),
        _momentum_component(item),
        _risk_component(item),
        _data_confidence_component(item),
    )
    quality = assess_long_term_quality(item.research)
    return _LongTermConviction(
        bucket=quality.bucket.value,
        thesis=quality.thesis,
        components=components,
    )


def _long_term_conviction_payload(item: WatchlistItem) -> dict[str, Any]:
    conviction = _long_term_conviction(item)
    return {
        "bucket": conviction.bucket,
        "thesis": conviction.thesis,
        "components": {
            component.name: {
                "score": component.score,
                "view": component.view,
            }
            for component in conviction.components
        },
    }


def _long_term_gate_payload(item: WatchlistItem) -> dict[str, Any]:
    decision = assess_long_term_gate(item.research)
    return {
        "tier": decision.tier.value,
        "reasons": list(decision.reasons),
        "blockers": list(decision.blockers),
        "durable_anchor_count": decision.durable_anchor_count,
        "severe_proof_gap_count": decision.severe_proof_gap_count,
        "valuation": {
            "has_support": decision.valuation.has_support,
            "is_attractive": decision.valuation.is_attractive,
            "primary_kind": decision.valuation.primary_kind,
            "primary_value": decision.valuation.primary_value,
            "summary": decision.valuation.summary,
        },
    }


def _business_quality_component(item: WatchlistItem) -> _ConvictionComponent:
    margin = item.research.financials.operating_margin_pct
    has_profile = bool(item.research.company.business_description)
    if margin is not None and margin >= 15 and has_profile:
        return _ConvictionComponent(
            "Business quality", 5, "Strong - profitable business with a clear profile."
        )
    if margin is not None and margin > 0 and has_profile:
        return _ConvictionComponent(
            "Business quality", 4, "Good - profitable business with a clear profile."
        )
    if margin is not None and margin > 0:
        return _ConvictionComponent(
            "Business quality", 3, "Profitable, but the business profile is limited."
        )
    if has_profile and margin is None:
        return _ConvictionComponent(
            "Business quality", 3, "Clear business profile, but margin data is missing."
        )
    if margin is not None and margin < 0:
        return _ConvictionComponent(
            "Business quality", 1, "Weak - profitability is not yet proven."
        )
    return _ConvictionComponent(
        "Business quality", 0, "Insufficient business and margin data."
    )


def _valuation_component(item: WatchlistItem) -> _ConvictionComponent:
    financials = item.research.financials
    valuation = assess_valuation_support(item.research)
    attractive = (
        _positive_at_most(financials.pe_ratio, 12)
        or _positive_at_most(financials.price_to_book, 1.2)
        or _positive_at_most(financials.ev_to_ebit, 10)
    )
    reasonable = (
        _positive_at_most(financials.pe_ratio, 20)
        or _positive_at_most(financials.price_to_book, 2.5)
        or _positive_at_most(financials.ev_to_ebit, 16)
    )
    expensive = (
        _positive_above(financials.pe_ratio, 35)
        or _positive_above(financials.price_to_book, 5)
        or _positive_above(financials.ev_to_ebit, 25)
    )
    direct_metric = valuation.primary_kind in {"pe_ratio", "price_to_book", "ev_to_ebit"}
    if attractive:
        return _ConvictionComponent(
            "Valuation", 5, "Attractive valuation on available P/E or P/B metrics."
        )
    if valuation.is_attractive:
        return _ConvictionComponent(
            "Valuation", 5, f"Attractive valuation support: {valuation.summary}"
        )
    if reasonable:
        return _ConvictionComponent(
            "Valuation", 4, "Reasonable valuation on available multiples."
        )
    if valuation.has_support and not direct_metric:
        return _ConvictionComponent(
            "Valuation", 3, f"Valuation proxy available: {valuation.summary}"
        )
    if expensive:
        return _ConvictionComponent(
            "Valuation", 1, "Expensive on available valuation multiples."
        )
    if any(
        metric is not None
        for metric in (financials.pe_ratio, financials.price_to_book, financials.ev_to_ebit)
    ):
        return _ConvictionComponent(
            "Valuation", 2, "Valuation is available but not clearly attractive."
        )
    return _ConvictionComponent("Valuation", 1, "No valuation multiple is available.")


def _growth_component(item: WatchlistItem) -> _ConvictionComponent:
    growth = item.research.financials.revenue_growth_pct
    if growth is None:
        return _ConvictionComponent("Growth", 1, "Revenue growth is not available.")
    if growth >= 20:
        return _ConvictionComponent("Growth", 5, f"Strong revenue growth of {growth:.1f}%.")
    if growth >= 5:
        return _ConvictionComponent("Growth", 4, f"Healthy revenue growth of {growth:.1f}%.")
    if growth > 0:
        return _ConvictionComponent("Growth", 3, f"Modest revenue growth of {growth:.1f}%.")
    return _ConvictionComponent("Growth", 1, f"Revenue declined {abs(growth):.1f}%.")


def _balance_sheet_component(item: WatchlistItem) -> _ConvictionComponent:
    financials = item.research.financials
    net_cash = financials.net_cash_eur_m
    debt_to_equity = financials.debt_to_equity
    has_net_cash = net_cash is not None and net_cash > 0
    conservative_debt = debt_to_equity is not None and debt_to_equity <= 0.5
    if has_net_cash and conservative_debt:
        return _ConvictionComponent(
            "Balance sheet", 5, "Net cash and conservative debt/equity."
        )
    if has_net_cash or conservative_debt:
        return _ConvictionComponent(
            "Balance sheet", 4, "Balance sheet looks conservative on available metrics."
        )
    if debt_to_equity is not None and debt_to_equity <= 1.5:
        return _ConvictionComponent(
            "Balance sheet", 3, "Debt/equity looks manageable on available data."
        )
    if (net_cash is not None and net_cash < 0) or _positive_above(debt_to_equity, 1.5):
        return _ConvictionComponent(
            "Balance sheet", 1, "Leverage or net debt needs close review."
        )
    return _ConvictionComponent("Balance sheet", 1, "Balance sheet data is not available.")


def _momentum_component(item: WatchlistItem) -> _ConvictionComponent:
    financials = item.research.financials
    one_year = financials.one_year_return_pct
    distance = financials.distance_from_52w_high_pct
    if _has_trading_signal(item):
        return _ConvictionComponent(
            "Momentum", 1, "Intraday move is not enough for a long-term thesis."
        )
    if (one_year is not None and one_year <= -25) or (
        distance is not None and distance <= -30
    ):
        return _ConvictionComponent(
            "Momentum", 3, "Contrarian setup; verify why the market discounted it."
        )
    if (one_year is not None and one_year >= 75) or (
        distance is not None and distance >= -5
    ):
        return _ConvictionComponent(
            "Momentum", 2, "Share price looks hot; do not let momentum drive the thesis."
        )
    if one_year is not None or distance is not None:
        return _ConvictionComponent(
            "Momentum", 3, "Price context is available but secondary to fundamentals."
        )
    return _ConvictionComponent("Momentum", 2, "No medium-term price context is available.")


def _risk_component(item: WatchlistItem) -> _ConvictionComponent:
    risks = _public_risk_items((*item.research.risks, *item.score.warnings))
    risk_text = " ".join(risks).lower()
    if "extreme intraday spike" in risk_text or "speculative low-price" in risk_text:
        return _ConvictionComponent(
            "Risk", 1, "Speculative market signal; position sizing would matter."
        )
    if "negative operating margin" in risk_text or "profitability" in risk_text:
        return _ConvictionComponent(
            "Risk", 2, "Profitability risk needs manual confirmation."
        )
    if "low live turnover" in risk_text or "thin liquidity" in risk_text:
        return _ConvictionComponent(
            "Risk", 2, "Liquidity risk could make entry and exit difficult."
        )
    if risks:
        return _ConvictionComponent("Risk", 3, "; ".join(risks[:2]))
    return _ConvictionComponent(
        "Risk", 4, "No specific risk flag surfaced in the current screen."
    )


def _data_confidence_component(item: WatchlistItem) -> _ConvictionComponent:
    financials = item.research.financials
    metric_count = sum(
        metric is not None
        for metric in (
            financials.pe_ratio,
            financials.price_to_book,
            financials.ev_to_ebit,
            financials.revenue_eur_m,
            financials.book_value_eur_m,
            financials.net_income_eur_m,
            financials.net_cash_eur_m,
            financials.debt_to_equity,
            financials.revenue_growth_pct,
            financials.operating_margin_pct,
        )
    )
    has_profile = bool(item.research.company.business_description)
    if metric_count == 0 and not has_profile:
        return _ConvictionComponent(
            "Data confidence", 0, "No useful fundamentals or profile text are available today."
        )
    if item.research.data_quality == DataQuality.GOOD and metric_count >= 4 and has_profile:
        return _ConvictionComponent(
            "Data confidence", 5, "Rich fundamentals and profile text are available."
        )
    if metric_count >= 4 and has_profile:
        return _ConvictionComponent(
            "Data confidence", 4, "Several fundamentals plus profile text are available."
        )
    if metric_count >= 2:
        return _ConvictionComponent(
            "Data confidence", 3, "Some fundamentals are available; verify in reports."
        )
    return _ConvictionComponent(
        "Data confidence", 1, "Only limited fundamentals are available today."
    )


def _positive_at_most(value: float | None, threshold: float) -> bool:
    return value is not None and 0 < value <= threshold


def _positive_above(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _has_trading_signal(item: WatchlistItem) -> bool:
    return any(
        _is_trading_render_signal(signal)
        for signal in (
            *item.research.catalysts,
            *item.research.risks,
            *item.score.reasons,
            *item.score.warnings,
        )
    )


def _is_trading_render_signal(signal: str) -> bool:
    lower = signal.lower()
    return (
        "intraday" in lower
        or "live turnover" in lower
        or "trading strategy" in lower
        or "long-term strategy penalty" in lower
    )


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _company_description(item: WatchlistItem) -> str:
    description = item.research.company.business_description
    if description:
        return description
    return _company_presentation(item)


def _company_presentation(item: WatchlistItem) -> str:
    company = item.research.company
    financials = item.research.financials
    country = _country_name(company.country)
    segment = _segment_label(company.segment)

    sector_part = f" {company.sector}" if company.sector else ""
    base = (
        f"{company.name} is a {country}-listed {segment}{sector_part} company "
        f"on {company.exchange}."
    )

    facts = []
    market_cap = _market_cap_phrase(company.market_cap_eur_m)
    if market_cap is not None:
        facts.append(f"Market cap is about {market_cap}")
    revenue_growth = _percentage_phrase("revenue growth", financials.revenue_growth_pct)
    if revenue_growth is not None:
        facts.append(revenue_growth)
    operating_margin = _percentage_phrase("operating margin", financials.operating_margin_pct)
    if operating_margin is not None:
        facts.append(operating_margin)
    one_year_return = _percentage_phrase("one-year return", financials.one_year_return_pct)
    if one_year_return is not None:
        facts.append(one_year_return)

    if not facts:
        return base
    return f"{base} {_join_sentence_facts(facts)}."


def _country_name(country: str) -> str:
    return {"SE": "Sweden", "FI": "Finland"}.get(country.upper(), country.upper())


def _segment_label(segment) -> str:
    if segment == ListingSegment.FIRST_NORTH:
        return "First North"
    if segment == ListingSegment.MAIN_MARKET:
        return "main market"
    if segment == ListingSegment.SPOTLIGHT:
        return "Spotlight"
    return "public market"


def _market_cap_phrase(value: float | None) -> str | None:
    if value is None:
        return None
    if abs(value) >= 100:
        return f"EUR {value:.0f}m"
    return f"EUR {value:.1f}m"


def _percentage_phrase(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label} is {value:.1f}%"


def _join_sentence_facts(facts: list[str]) -> str:
    if len(facts) == 1:
        return facts[0]
    if len(facts) == 2:
        return f"{facts[0]} and {facts[1]}"
    return f"{', '.join(facts[:-1])}, and {facts[-1]}"


def _metadata_lines(metadata: dict[str, Any]) -> list[str]:
    return [f"- {key}: {_stringify_metadata_value(value)}" for key, value in metadata.items()]


def _stringify_metadata_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if value is None:
        return "None"
    return str(value)


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    return value


def _evidence_lines(evidence_items: tuple[Evidence, ...]) -> list[str]:
    if not evidence_items:
        return ["- None provided."]
    return [
        f"- {evidence.label}: {evidence.url}{_source_suffix(evidence)}"
        for evidence in evidence_items
    ]


def _markdown_evidence_lines(evidence_items: tuple[Evidence, ...]) -> list[str]:
    if not evidence_items:
        return ["- None provided."]
    return [
        f"- [{evidence.label}]({evidence.url}){_source_suffix(evidence)}"
        for evidence in evidence_items
    ]


def _public_reason_lines(items: tuple[str, ...]) -> list[str]:
    return _public_bullet_lines(items, _humanize_reason)


def _public_risk_lines(items: tuple[str, ...]) -> list[str]:
    return _public_bullet_lines(items, _humanize_risk)


def _public_risk_items(items: tuple[str, ...]) -> list[str]:
    return _public_items(items, _humanize_risk)


def _joined_public_risks(items: tuple[str, ...]) -> str:
    formatted = _public_risk_items(items)
    if not formatted:
        return "None provided."
    return "; ".join(formatted)


def _public_bullet_lines(items: tuple[str, ...], formatter) -> list[str]:
    formatted = _public_items(items, formatter)
    if not formatted:
        return ["- None provided."]
    return [f"- {item}" for item in formatted]


def _public_items(items: tuple[str, ...], formatter) -> list[str]:
    formatted = [formatter(item) for item in items]
    return [item for item in formatted if item]


def _humanize_reason(item: str) -> str:
    normalized = item.strip()
    lower = normalized.lower()
    if lower == "trading strategy adjustment applied":
        return (
            "Trading strategy boost: liquidity and momentum signals make this more "
            "relevant for a short-term watchlist."
        )
    if lower == "long-term strategy adjustment applied":
        return (
            "Long-term strategy boost: valuation or balance-sheet signals make this "
            "more relevant for fundamental research."
        )
    if lower == "discovery strategy adjustment applied":
        return "Discovery strategy boost: smaller or less-covered listing profile."
    return _capitalize_first(normalized)


def _humanize_risk(item: str) -> str:
    normalized = item.strip()
    lower = normalized.lower()
    if lower == "sparse live-source data":
        return ""
    if lower == "thin data quality":
        return ""
    if lower == "partial data quality":
        return ""
    if lower == "missing live turnover":
        return ""
    if lower == "1 stated risk(s)":
        return ""
    if lower.endswith(" stated risk(s)"):
        return ""
    if lower.endswith("strategy adjustment applied"):
        return ""
    return _capitalize_first(normalized)


def _capitalize_first(value: str) -> str:
    if not value:
        return value
    return f"{value[0].upper()}{value[1:]}"


def _source_suffix(evidence: Evidence) -> str:
    parts = [part for part in (evidence.source, evidence.timestamp) if part]
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def _bullet_lines(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None provided."]
    return [f"- {item}" for item in items]


def _joined(items: tuple[str, ...]) -> str:
    if not items:
        return "None provided."
    return "; ".join(items)


def _stringify(value: Enum | str | DataQuality) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


# --- Decision-time comparison layout (presentation only) -------------------------------

PERFORMANCE_PAGE_LINK = "../../performance/"
METRIC_DEFINITIONS_LINK = "../../performance/#metric-definitions"
_COMPONENT_LABELS = {
    "value": "Value",
    "discovery": "Discovery",
    "quality_adjustment": "Quality adjustment",
    "catalyst": "Catalyst",
    "risk_penalty": "Risk penalty",
    "data_quality_penalty": "Data-quality penalty",
}
_GATE_TIER_SHORT = {
    LongTermGateTier.HIGH_CONVICTION.value: "High-conviction",
    LongTermGateTier.FUNDAMENTAL_WATCHLIST.value: "Fundamental watchlist",
    LongTermGateTier.SPECULATIVE_MONITOR.value: "Speculative monitor",
    LongTermGateTier.INSUFFICIENT_EVIDENCE.value: "Insufficient evidence",
}
_RISK_CHECKS = (
    "Checked: model risk flags, liquidity, leverage, profitability, valuation extremes, "
    "price weakness, data quality and fundamentals freshness."
)


def _render_compared_watchlist_markdown(
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks,
    comparison: ReportComparison, strategy: str, subtitle: str,
) -> str:
    if len(items) != len(comparison.ideas) or any(
        item.rank != idea.row.rank or item.research.company.ticker != idea.row.ticker
        for item, idea in zip(items, comparison.ideas)
    ):
        raise ValueError("comparison does not describe the selected watchlist items")
    paired = list(zip(items, comparison.ideas))
    lines = [
        f"# {_watchlist_report_title(strategy)}",
        "",
        f"> {DISCLAIMER}",
        "",
        *(["_" + subtitle + "_", ""] if subtitle else []),
        _run_summary_line(metadata, comparison, len(items)),
        "",
        (
            "> **How to read this page.** Rank and score are decision-time ranking signals, "
            "not forecasts or probabilities of outperforming. Peer comparisons use the "
            "fundamentals the ranking used at decision time; *listing peers* share country "
            "and listing venue only and span many industries. "
            f"[What the track record shows so far]({PERFORMANCE_PAGE_LINK}) · "
            f"[Metric definitions]({METRIC_DEFINITIONS_LINK})"
        ),
        "",
    ]
    if paired:
        lines.extend([
            "## Summary",
            "",
            *_compared_summary_table(paired, strategy),
            "",
            "**Relative comparison with listing peers**",
            "",
            *[
                f"- **#{item.rank} {item.research.company.ticker}:** {relative_summary(idea)}"
                for item, idea in paired
            ],
            "",
            "## Watchlist",
            "",
        ])
        if strategy == "long-term":
            lines.extend(_compared_long_term_sections(paired, metadata, comparison))
        else:
            lines.extend(_compared_item_sections(paired, metadata, comparison, strategy))
        lines.append("")
    else:
        lines.extend(["## Watchlist", "", *_empty_watchlist_lines(strategy, comparison), ""])
    lines.extend([
        "## Run Diagnostics",
        "",
        '<details markdown="1">',
        "<summary>Metadata and source checks</summary>",
        "",
        "### Metadata",
        *_metadata_lines(metadata),
        "",
        "### Source Checks",
        *[f"- {check.name}: {check.status} - {check.detail}" for check in source_checks],
        "",
        "</details>",
    ])
    return "\n".join(lines)


def _run_summary_line(metadata: dict[str, Any], comparison: ReportComparison, selected: int) -> str:
    evaluation = metadata.get("evaluation") or {}
    decision_at = evaluation.get("decision_at") or comparison.decision_at or metadata.get("generated_at")
    countries = " · ".join(f"{country} {count}" for country, count in comparison.country_counts.items())
    parts = [
        f"**Decision time:** {_display_timestamp(decision_at)}",
        f"**Eligible universe (X):** {comparison.universe_size} companies"
        + (f" ({countries})" if countries else ""),
        f"**Selected:** {selected}",
    ]
    if evaluation.get("scoring_model_version"):
        parts.append(f"**Model:** `{evaluation['scoring_model_version']}`")
    if evaluation.get("run_id"):
        parts.append(f"**Run:** `{evaluation['run_id']}`")
    return " · ".join(parts)


def _display_timestamp(value: Any) -> str:
    if not value:
        return "not recorded"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        return text
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _empty_watchlist_lines(strategy: str, comparison: ReportComparison) -> list[str]:
    screened = comparison.source_universe_size
    screened_text = f"the {screened} listed companies screened" if screened else "the companies screened"
    if strategy == "trading":
        return [
            (
                f"**No trading candidates at decision time.** None of {screened_text} showed a "
                "qualifying short-term setup (strong momentum, unusual turnover or an "
                "event-style catalyst), so no trading ideas are published today. This is "
                "common when the decision is taken before the market opens and is not a "
                "pipeline failure; the empty universe is still recorded for evaluation."
            ),
        ]
    return [
        (
            f"**No candidates at decision time.** None of {screened_text} passed this "
            "strategy's eligibility filters, so no ideas are published today."
        ),
    ]


def _compared_summary_table(paired, strategy: str) -> list[str]:
    long_term = strategy == "long-term"
    header = ["#", "Company", "Market", "Score", "Score percentile in X"]
    align = ["---:", "---", "---", "---:", "---:"]
    if long_term:
        header.append("Gate tier")
        align.append("---")
    header.extend(["Data", "P/E vs listing peers", "Op. margin vs listing peers", "Main risks"])
    align.extend(["---", "---", "---", "---"])
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    for item, idea in paired:
        company = item.research.company
        risks = _risk_items(item, idea)
        risk_text = "; ".join(short for short, _ in risks[:2]) if risks else "None flagged"
        if len(risks) > 2:
            risk_text += f" (+{len(risks) - 2} more)"
        cells = [
            str(item.rank),
            f"[{_table_cell(company.name)} ({_table_cell(company.ticker)})](#idea-{item.rank})",
            _market_label(idea),
            f"{item.score.total:g}",
            _ordinal_or_na(idea.score_percentile),
        ]
        if long_term:
            cells.append(_GATE_TIER_SHORT.get(idea.row.gate_tier or "", idea.row.gate_tier or "n/a"))
        cells.extend([
            _data_cell(idea),
            _summary_metric_cell(idea.metric("pe_ratio")),
            _summary_metric_cell(idea.metric("operating_margin_pct")),
            _table_cell(risk_text),
        ])
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _market_label(idea: IdeaComparison) -> str:
    return f"{idea.row.country} {_venue_label(idea.row.venue)}"


def _venue_label(venue: str) -> str:
    return {"main_market": "main market", "first_north": "First North",
            "spotlight": "Spotlight"}.get(venue, venue.replace("_", " "))


def _data_cell(idea: IdeaComparison) -> str:
    text = idea.row.data_quality
    if idea.fundamentals_age_days is not None:
        text += f", {idea.fundamentals_age_days} d old"
    if idea.row.cache_state in {"stale", "missing"}:
        text += f" ({idea.row.cache_state})"
    return text


def _summary_metric_cell(item: MetricComparison) -> str:
    if item.value_status == "missing":
        return "Missing"
    if item.value_status == "invalid":
        return "Not meaningful"
    stat = item.level(LISTING_PEERS)
    value = _format_metric(item.spec.unit, item.value)
    if stat is None or stat.status != "ok" or stat.percentile is None:
        return f"{value} (peers unavailable)"
    return f"{value} ({_position_phrase(item, stat.percentile)})"


def _compared_long_term_sections(paired, metadata, comparison) -> list[str]:
    lines: list[str] = []
    research_tiers = {
        LongTermGateTier.HIGH_CONVICTION.value,
        LongTermGateTier.FUNDAMENTAL_WATCHLIST.value,
    }
    if not any(idea.row.gate_tier in research_tiers for _, idea in paired):
        lines.extend([
            (
                "_No long-term research candidates passed the gate today. "
                "Rows below are speculative monitors or evidence-audit rows, "
                "not primary long-term investment ideas._"
            ),
            "",
        ])
    for tier, heading in LONG_TERM_TIER_HEADINGS.items():
        tier_pairs = [pair for pair in paired if pair[1].row.gate_tier == tier.value]
        if not tier_pairs:
            continue
        lines.extend([f"## {heading}", ""])
        if tier == LongTermGateTier.SPECULATIVE_MONITOR:
            lines.extend([
                "_These are not primary long-term investment ideas; they need "
                "valuation or stronger proof before promotion._",
                "",
            ])
        lines.extend(_compared_item_sections(tier_pairs, metadata, comparison, "long-term"))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _compared_item_sections(paired, metadata, comparison, strategy: str) -> list[str]:
    lines: list[str] = []
    for item, idea in paired:
        company = item.research.company
        lines.extend([
            f'<a id="idea-{item.rank}"></a>',
            "",
            f"## #{item.rank} {company.name} ({company.ticker})",
            "",
            f"`{company.country}` | {company.exchange} | `{_stringify(company.segment)}`",
            "",
            f"**What the company does:** {_company_description(item)}",
            "",
            f"**Score:** {item.score.total:g}",
            f"**Data quality:** {_stringify(item.research.data_quality)}",
            "",
            *_why_it_ranks_lines(item, idea, metadata, strategy),
            f"**Relative to listing peers:** {relative_summary(idea)}",
            "",
            "### Risks to weigh",
            *[f"- {detail}" for _, detail in _risk_items(item, idea)],
            f"- {_RISK_CHECKS}",
            "",
            *_evidence_gap_lines(idea, comparison),
            '<details markdown="1">',
            "<summary>Score components and decision-time peer comparison</summary>",
            "",
            *_component_table_lines(idea),
            "",
            *_peer_comparison_lines(idea),
            "</details>",
            "",
        ])
        if strategy == "long-term":
            lines.extend(_long_term_conviction_lines(item))
        lines.extend([
            "### Reasons",
            *_public_reason_lines(item.score.reasons),
            "",
            "### Evidence",
            *_markdown_evidence_lines(item.research.evidence),
            "",
        ])
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _why_it_ranks_lines(item, idea: IdeaComparison, metadata, strategy) -> list[str]:
    total = idea.universe_size
    lines = ["### Why it ranks here"]
    if strategy == "long-term":
        order = "long-term ranking orders companies by gate tier, then score"
    else:
        order = "ranking orders companies by score"
    if idea.included_by_country_minimum:
        minimum = ", ".join(
            f"{country}:{count}" for country, count in (metadata.get("min_country_counts") or {}).items()
        ) or "country minimum"
        lines.append(
            f"- **Selection:** rank {item.rank} of {total}; included by the minimum-country "
            f"rule ({minimum}). Without it the company would rank {idea.base_rank} of {total} "
            f"({order})."
        )
    else:
        lines.append(f"- **Selection:** rank {item.rank} of {total}; {order}.")
    if strategy == "long-term" and idea.row.gate_tier:
        tiers = [tier.value for tier in LONG_TERM_TIER_HEADINGS]
        position = tiers.index(idea.row.gate_tier) + 1 if idea.row.gate_tier in tiers else None
        tier_text = f" (tier {position} of {len(tiers)})" if position else ""
        lines.append(f"- **Gate tier:** {idea.row.gate_tier}{tier_text}.")
    difference = idea.score_minus_median
    score_line = f"- **Score:** {item.score.total:g}"
    if difference is not None and idea.universe_median_score is not None:
        direction = "above" if difference >= 0 else "below"
        score_line += (
            f", {_points(abs(difference))} points {direction} the X median "
            f"({_points(idea.universe_median_score)})"
        )
    if idea.score_percentile is not None:
        score_line += f"; higher than {_whole(idea.score_percentile)}% of the other {total - 1} companies in X"
    lines.append(score_line + ".")
    contributions, deductions = [], []
    for name, label in _COMPONENT_LABELS.items():
        points = idea.row.components.get(name)
        if not points:
            continue
        (deductions if name.endswith("penalty") else contributions).append((points, label))
    if contributions:
        top = sorted(contributions, key=lambda pair: (-pair[0], pair[1]))[:2]
        lines.append("- **Largest contributions:** " + ", ".join(
            f"{label} (+{_points(points)})" for points, label in top) + ".")
    if deductions:
        top = sorted(deductions, key=lambda pair: (-pair[0], pair[1]))[:2]
        lines.append("- **Largest deductions:** " + ", ".join(
            f"{label} (-{_points(points)})" for points, label in top) + ".")
    lines.append("")
    return lines


def _component_table_lines(idea: IdeaComparison) -> list[str]:
    lines = [
        f"Score components (points) and position among the {idea.universe_size} companies in X:",
        "",
        "| Score component | Points | Position in X |",
        "| --- | ---: | --- |",
    ]
    for name, label in _COMPONENT_LABELS.items():
        if name not in idea.row.components:
            continue
        points = idea.row.components[name]
        percentile = idea.component_percentiles.get(name)
        penalty = name.endswith("penalty")
        signed = f"-{_points(points)}" if penalty and points else (f"+{_points(points)}" if points else "0")
        if percentile is None:
            position = "n/a"
        elif penalty:
            position = f"smaller penalty than {_whole(percentile)}% of X"
        else:
            position = f"higher than {_whole(percentile)}% of X"
        lines.append(f"| {label} | {signed} | {position} |")
    return lines


def _peer_comparison_lines(idea: IdeaComparison) -> list[str]:
    lines = [
        (
            f"Listing peers: {_market_label(idea)}, {idea.listing_group_size} other companies "
            f"(mixed industries). All eligible X: {idea.universe_size - 1} other companies. "
            "n = usable observations / peers; invalid multiples and missing values are "
            "excluded and counted."
        ),
        "",
        f"| Metric | Value | Listing peers ({_market_label(idea)}) | All eligible X |",
        "| --- | ---: | --- | --- |",
    ]
    for item in idea.metrics:
        lines.append(
            f"| {item.spec.label} | {_value_cell(item)} | "
            f"{_peer_cell(item, item.level(LISTING_PEERS))} | {_peer_cell(item, item.level(ALL_ELIGIBLE))} |"
        )
    lines.append("")
    return lines


def _value_cell(item: MetricComparison) -> str:
    if item.value_status == "missing":
        return "Missing"
    if item.value_status == "invalid":
        return _table_cell(item.spec.invalid_label)
    return _format_metric(item.spec.unit, item.value)


def _peer_cell(item: MetricComparison, stat: PeerStat | None) -> str:
    if stat is None:
        return "Unavailable"
    extras = []
    if stat.invalid:
        extras.append(f"{stat.invalid} not meaningful")
    if stat.missing:
        extras.append(f"{stat.missing} missing")
    counts = f"n={stat.usable}/{stat.population}" + (f" ({', '.join(extras)})" if extras else "")
    if stat.median is None:
        return f"Unavailable: fewer than {PEER_MINIMUM_OBSERVATIONS} comparable peers · {counts}"
    median = f"median {_format_metric(item.spec.unit, stat.median)}"
    if stat.status == "ok" and stat.percentile is not None:
        return f"{median}; {_position_phrase(item, stat.percentile)} · {counts}"
    return f"{median} · {counts}"


def _position_phrase(item: MetricComparison, percentile: float) -> str:
    return f"{item.spec.favourable_phrase} {_whole(percentile)}%"


def _evidence_gap_lines(idea: IdeaComparison, comparison: ReportComparison) -> list[str]:
    row = idea.row
    lines = ["### Evidence gaps and freshness"]
    if not comparison.cache_recorded:
        lines.append("- Fundamentals freshness was not recorded for this run.")
    elif row.cache_state == "disabled":
        lines.append(
            "- The fundamentals cache was not used in this run, so retrieval dates are not recorded."
        )
    elif row.retrieved_at is None:
        state = row.cache_state or "not recorded"
        lines.append(f"- No cached fundamentals were recorded for this company (cache state: {state}).")
    else:
        lines.append(
            f"- Fundamentals retrieved {row.retrieved_at[:10]}, {idea.fundamentals_age_days} days "
            f"before the decision (cache state: {row.cache_state})."
        )
    if idea.listing_group_fresh_share is not None and row.cache_state != "disabled":
        lines.append(
            f"- {_whole(idea.listing_group_fresh_share)}% of listing peers had fresh fundamentals "
            "at decision time."
        )
    missing = [_INPUT_LABELS.get(key, key) for key in row.missing_inputs]
    lines.append(
        "- Missing inputs: " + ", ".join(missing) + "." if missing
        else "- All compared inputs were available."
    )
    lines.append(f"- Data quality: {row.data_quality}.")
    lines.append("")
    return lines


_INPUT_LABELS = {
    "pe_ratio": "P/E",
    "price_to_book": "P/B",
    "ev_to_ebit": "EV/EBIT",
    "operating_margin_pct": "operating margin",
    "revenue_growth_pct": "revenue growth",
    "debt_to_equity": "debt/equity",
    "market_cap_eur_m": "market cap",
    "average_daily_value_eur": "average daily traded value",
    "one_year_return_pct": "one-year return",
    "distance_from_52w_high_pct": "distance from 52-week high",
}


def _risk_items(item: WatchlistItem, idea: IdeaComparison) -> list[tuple[str, str]]:
    """Negative evidence, most specific first. Uses only existing signals and peer positions."""
    risks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(short: str, detail: str) -> None:
        key = short.lower()
        if key not in seen:
            seen.add(key)
            risks.append((short, detail))

    for signal in _public_risk_items(item.score.warnings):
        if signal.lower().startswith("gate tier: "):
            add(signal, f"{signal} (not a primary research tier).")
        else:
            add(signal, f"{signal} (model warning).")
    for metric in idea.metrics:
        if metric.value_status == "invalid":
            reason = metric.spec.invalid_label.removeprefix("Not meaningful").strip(" ()")
            add(metric.spec.invalid_risk or f"{metric.spec.label} not meaningful",
                f"{metric.spec.label} is not meaningful: {reason or 'invalid value'}; "
                "it is excluded from peer comparisons.")
    margin = idea.metric("operating_margin_pct")
    if (margin.value_status == "valid" and margin.value is not None and margin.value < 0
            and not any("margin" in key for key in seen)):
        add("Negative operating margin", f"Operating margin of {margin.value:.1f}%.")
    financials = item.research.financials
    if financials.one_year_return_pct is not None and financials.one_year_return_pct <= -25:
        add(
            f"One-year return {financials.one_year_return_pct:.1f}%",
            f"One-year share-price return of {financials.one_year_return_pct:.1f}%; the model "
            "counts this as a contrarian discovery signal, so verify why the market discounted it.",
        )
    if financials.distance_from_52w_high_pct is not None and financials.distance_from_52w_high_pct <= -35:
        add(
            f"{abs(financials.distance_from_52w_high_pct):.1f}% below 52-week high",
            f"Share price {abs(financials.distance_from_52w_high_pct):.1f}% below its 52-week "
            "high; the model counts this as a contrarian discovery signal.",
        )
    row = idea.row
    if row.cache_state == "stale":
        add("Stale fundamentals",
            f"Fundamentals are {idea.fundamentals_age_days} days old and were marked stale by "
            "the run's freshness policy.")
    elif row.cache_state == "missing":
        add("No cached fundamentals", "No cached fundamentals were available at decision time.")
    liquidity = idea.metric("average_daily_value_eur").level(LISTING_PEERS)
    if (liquidity is not None and liquidity.status == "ok" and liquidity.percentile is not None
            and liquidity.percentile <= 25 and not any("liquidity" in key for key in seen)):
        add("Low trading volume vs peers",
            f"Less traded than {_whole(100 - liquidity.percentile)}% of listing peers; entry and exit "
            "may be costly.")
    leverage = idea.metric("debt_to_equity").level(LISTING_PEERS)
    if (leverage is not None and leverage.status == "ok" and leverage.percentile is not None
            and leverage.percentile <= 25 and not any("debt" in key for key in seen)):
        add("High leverage vs peers",
            f"More leveraged than {_whole(100 - leverage.percentile)}% of listing peers.")
    stated = [risk.strip() for risk in item.research.risks if risk.strip()]
    if stated:
        penalty = min(len(stated) * 3.0, 15.0)
        add(
            "Stated risks",
            f"{len(stated)} stated risk(s) cost {penalty:g} risk-penalty points: "
            + "; ".join(_capitalize_first(risk) for risk in stated) + ".",
        )
    quality = item.research.data_quality.value
    if quality != DataQuality.GOOD.value:
        add(
            f"{_capitalize_first(quality)} data",
            f"{_capitalize_first(quality)} data quality "
            f"({item.score.data_quality_penalty:g}-point data-quality penalty).",
        )
    return risks


def _format_metric(unit: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "EUR m":
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.1f}"
    if unit == "EUR":
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}m"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.0f}k"
        return f"{value:.0f}"
    if abs(value) < 10:
        return f"{value:.2f}"
    return f"{value:.1f}"


def _points(value: float) -> str:
    return f"{round(value, 2):g}"


def _whole(value: float) -> int:
    return int(math.floor(value + 0.5))


def _ordinal_or_na(value: float | None) -> str:
    if value is None:
        return "n/a"
    number = _whole(value)
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"
