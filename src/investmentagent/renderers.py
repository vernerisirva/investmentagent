from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from investmentagent.models import (
    Company,
    DataQuality,
    DeepDiveReport,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)


DISCLAIMER = "Research triage only. Not financial advice."


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
                f"Risks: {_joined((*item.research.risks, *item.score.warnings))}",
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
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks
) -> str:
    strategy = str(metadata.get("strategy") or "").strip().lower()
    lines = [
        "# InvestmentAgent Watchlist",
        "",
        f"> {DISCLAIMER}",
        "",
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
        payloads.append(payload)
    return payloads


def _financials_payload(financials: FinancialSnapshot) -> dict[str, Any]:
    return {
        "price": financials.price,
        "currency": financials.currency,
        "pe_ratio": financials.pe_ratio,
        "price_to_book": financials.price_to_book,
        "ev_to_ebit": financials.ev_to_ebit,
        "net_cash_eur_m": financials.net_cash_eur_m,
        "debt_to_equity": financials.debt_to_equity,
        "revenue_growth_pct": financials.revenue_growth_pct,
        "operating_margin_pct": financials.operating_margin_pct,
        "one_year_return_pct": financials.one_year_return_pct,
        "distance_from_52w_high_pct": financials.distance_from_52w_high_pct,
        "average_daily_value_eur": financials.average_daily_value_eur,
        "data_quality": _stringify(financials.data_quality),
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


def _watchlist_markdown_sections(
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
    scores = {component.name: component.score for component in components}
    bucket = _long_term_bucket(item, scores)
    return _LongTermConviction(
        bucket=bucket,
        thesis=_long_term_thesis(item, bucket),
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
    if attractive:
        return _ConvictionComponent(
            "Valuation", 5, "Attractive valuation on available P/E or P/B metrics."
        )
    if reasonable:
        return _ConvictionComponent(
            "Valuation", 4, "Reasonable valuation on available multiples."
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


def _long_term_bucket(item: WatchlistItem, scores: dict[str, int]) -> str:
    if _has_trading_signal(item) and scores["Data confidence"] <= 1:
        return "Trading-only mover"
    if scores["Data confidence"] == 0:
        return "Excluded due to weak data"
    if (
        scores["Business quality"] >= 4
        and scores["Valuation"] >= 4
        and scores["Growth"] >= 3
    ):
        if (
            scores["Balance sheet"] >= 3
            and scores["Risk"] >= 3
            and scores["Data confidence"] >= 3
        ):
            return "High conviction candidate"
    if (
        scores["Business quality"] <= 1
        or scores["Growth"] <= 1
        or scores["Risk"] <= 2
        or scores["Data confidence"] <= 1
    ):
        return "Speculative / needs more proof"
    return "Fundamental watchlist candidate"


def _long_term_thesis(item: WatchlistItem, bucket: str) -> str:
    company = item.research.company
    financials = item.research.financials
    sector = (company.sector or "business").lower()
    if bucket == "High conviction candidate":
        margin = _metric_or_unknown("operating margin", financials.operating_margin_pct)
        return (
            f"{company.name} has a profitable {sector} profile "
            f"({margin}) "
            f"with {_growth_fragment(financials)} and {_balance_fragment(financials)}; "
            f"{_valuation_fragment(financials)}."
        )
    if bucket == "Trading-only mover":
        return (
            f"{company.name} is mainly showing market activity today; without enough "
            "fundamental support, treat it as a trading idea rather than a long-term "
            "candidate."
        )
    if bucket == "Excluded due to weak data":
        return (
            f"{company.name} lacks enough business and fundamental data for a long-term "
            "thesis today; wait for profile, report, or valuation evidence."
        )
    if bucket == "Speculative / needs more proof":
        return (
            f"{company.name} is worth monitoring, but the long-term case needs more "
            f"proof because {_weakest_long_term_issue(item)}."
        )
    return (
        f"{company.name} has enough fundamental evidence for the research queue, "
        "but valuation, growth, and risks should be checked manually before it "
        "moves into a conviction list."
    )


def _growth_fragment(financials: FinancialSnapshot) -> str:
    if financials.revenue_growth_pct is None:
        return "revenue growth still needs verification"
    return f"revenue growth of {financials.revenue_growth_pct:.1f}%"


def _balance_fragment(financials: FinancialSnapshot) -> str:
    if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
        return "a net cash balance sheet"
    if financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        return "conservative debt/equity"
    return "a balance sheet that still needs review"


def _valuation_fragment(financials: FinancialSnapshot) -> str:
    if (
        _positive_at_most(financials.pe_ratio, 12)
        or _positive_at_most(financials.price_to_book, 1.2)
        or _positive_at_most(financials.ev_to_ebit, 10)
    ):
        return "Valuation looks attractive on the available multiples"
    if (
        _positive_at_most(financials.pe_ratio, 20)
        or _positive_at_most(financials.price_to_book, 2.5)
        or _positive_at_most(financials.ev_to_ebit, 16)
    ):
        return "Valuation looks reasonable on the available multiples"
    return "Valuation needs manual comparison with Nordic peers"


def _weakest_long_term_issue(item: WatchlistItem) -> str:
    financials = item.research.financials
    if financials.operating_margin_pct is not None and financials.operating_margin_pct < 0:
        return "profitability is not yet proven"
    if not item.research.company.business_description:
        return "the business profile is still limited"
    if financials.revenue_growth_pct is None:
        return "revenue growth is not available"
    if financials.revenue_growth_pct < 0:
        return "revenue is declining"
    return "the evidence is not strong enough yet"


def _metric_or_unknown(label: str, value: float | None) -> str:
    if value is None:
        return f"{label} unavailable"
    return f"{label} {value:.1f}%"


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
