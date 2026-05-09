from __future__ import annotations

import json
from enum import Enum
from typing import Any

from openclaw.models import (
    Company,
    DataQuality,
    DeepDiveReport,
    Evidence,
    FinancialSnapshot,
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
        "items": [
            {
                "rank": item.rank,
                "company": _company_payload(item.research.company),
                "financials": _financials_payload(item.research.financials),
                "score": _score_payload(item.score),
                "risks": list(item.research.risks),
                "catalysts": list(item.research.catalysts),
                "evidence": [_evidence_payload(evidence) for evidence in item.research.evidence],
                "data_quality": _stringify(item.research.data_quality),
            }
            for item in items
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


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
