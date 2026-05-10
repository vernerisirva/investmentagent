from __future__ import annotations

import json
import math
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
    payload = {
        "disclaimer": DISCLAIMER,
        "metadata": metadata,
        "source_checks": [_source_check_payload(check) for check in source_checks],
        "items": _watchlist_items_payload(items),
    }
    return json.dumps(_normalize_json_value(payload), allow_nan=False, indent=2, sort_keys=True)


def render_watchlist_report_markdown(
    items: list[WatchlistItem], metadata: dict[str, Any], source_checks
) -> str:
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
        render_watchlist_text(items),
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
    }


def _watchlist_items_payload(items: list[WatchlistItem]) -> list[dict[str, Any]]:
    return [
        {
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
        for item in items
    ]


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
