from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
)


REQUIRED_UNIVERSE_FIELDS = (
    "provider_symbol",
    "ticker",
    "country",
    "currency",
    "name",
    "exchange",
    "sector",
    "ai_category",
    "ai_thesis",
)
HIGH_RELEVANCE_CATEGORIES = {
    "AI compute semiconductors",
    "AI compute manufacturing",
    "Semiconductor equipment",
    "Cloud AI platform",
}
MEDIUM_HIGH_RELEVANCE_CATEGORIES = {
    "AI infrastructure hardware",
    "Model/application platform",
    "Data and analytics platform",
}


@dataclass(frozen=True)
class GlobalAIUniverseEntry:
    name: str
    ticker: str
    provider_symbol: str
    country: str
    exchange: str
    currency: str
    sector: str
    ai_category: str
    ai_thesis: str


@dataclass(frozen=True)
class GlobalAIScoreBreakdown:
    valuation: float
    quality: float
    growth: float
    ai_relevance: float
    risk_penalty: float
    data_quality_penalty: float
    total: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class GlobalAIReportItem:
    rank: int
    entry: GlobalAIUniverseEntry
    research: CompanyResearch
    score: GlobalAIScoreBreakdown
    valuation_summary: str
    quality_summary: str
    growth_summary: str
    risk_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_flags", tuple(self.risk_flags))


@dataclass(frozen=True)
class GlobalAIReport:
    items: tuple[GlobalAIReportItem, ...]
    metadata: dict[str, object]
    source_checks: tuple[SourceCheck, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "source_checks", tuple(self.source_checks))


def load_global_ai_universe(
    path: Path | None = None,
) -> tuple[GlobalAIUniverseEntry, ...]:
    if path is None:
        resource = resources.files("investmentagent").joinpath(
            "data/global_ai_universe.json"
        )
        raw_entries = json.loads(resource.read_text(encoding="utf-8"))
    else:
        raw_entries = json.loads(Path(path).read_text(encoding="utf-8"))

    if not isinstance(raw_entries, list):
        raise ValueError("global AI universe must be a JSON array")

    entries: list[GlobalAIUniverseEntry] = []
    seen_tickers: set[str] = set()
    seen_symbols: set[str] = set()
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"global AI universe entry {index} must be an object")
        entry = _parse_universe_entry(raw_entry, index)
        if entry.ticker in seen_tickers:
            raise ValueError(f"duplicate ticker in global AI universe: {entry.ticker}")
        if entry.provider_symbol in seen_symbols:
            raise ValueError(
                "duplicate provider_symbol in global AI universe: "
                f"{entry.provider_symbol}"
            )
        seen_tickers.add(entry.ticker)
        seen_symbols.add(entry.provider_symbol)
        entries.append(entry)
    return tuple(entries)


def score_global_ai_candidate(
    research: CompanyResearch, entry: GlobalAIUniverseEntry
) -> GlobalAIScoreBreakdown:
    financials = research.financials
    reasons: list[str] = []
    warnings: list[str] = []

    valuation = _valuation_score(financials, reasons, warnings)
    quality = _quality_score(research, reasons, warnings)
    growth = _growth_score(financials, reasons, warnings)
    ai_relevance = _ai_relevance_score(entry, reasons)

    risk_penalty = 0.0
    if _missing_direct_valuation(financials):
        risk_penalty += 8.0
        warnings.append("missing valuation support")
    if financials.pe_ratio is not None and financials.pe_ratio > 55:
        risk_penalty += 12.0
        warnings.append("valuation risk: high P/E")
    if financials.price_to_book is not None and financials.price_to_book > 10:
        risk_penalty += 6.0
        warnings.append("valuation risk: high P/B")
    if financials.ev_to_ebit is not None and financials.ev_to_ebit > 35:
        risk_penalty += 8.0
        warnings.append("valuation risk: high EV/EBIT")
    if financials.debt_to_equity is not None and financials.debt_to_equity > 1.5:
        risk_penalty += 8.0
        warnings.append("high debt/equity")
    if (
        financials.operating_margin_pct is not None
        and financials.operating_margin_pct < 0
    ):
        risk_penalty += 10.0
        warnings.append("negative operating margin")

    data_quality_penalty = {
        DataQuality.GOOD: 0.0,
        DataQuality.PARTIAL: 4.0,
        DataQuality.THIN: 14.0,
    }[research.data_quality]

    total = max(
        valuation + quality + growth + ai_relevance - risk_penalty - data_quality_penalty,
        0.0,
    )
    return GlobalAIScoreBreakdown(
        valuation=round(valuation, 2),
        quality=round(quality, 2),
        growth=round(growth, 2),
        ai_relevance=round(ai_relevance, 2),
        risk_penalty=round(risk_penalty, 2),
        data_quality_penalty=round(data_quality_penalty, 2),
        total=round(total, 2),
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def build_global_ai_top5(
    fundamentals_provider,
    *,
    entries: tuple[GlobalAIUniverseEntry, ...] | None = None,
    limit: int = 5,
    generated_at: str | None = None,
) -> GlobalAIReport:
    universe = entries or load_global_ai_universe()
    items = [_candidate_item(entry, fundamentals_provider) for entry in universe]
    ranked_items = sorted(
        items,
        key=lambda item: (
            -item.score.total,
            -item.score.quality,
            -item.score.valuation,
            item.entry.ticker,
        ),
    )[:limit]
    ranked_items = [
        replace(item, rank=rank) for rank, item in enumerate(ranked_items, start=1)
    ]

    source_checks = [
        SourceCheck(
            "global ai universe",
            "ok",
            f"{len(universe)} curated global AI companies loaded",
        )
    ]
    source_check = getattr(fundamentals_provider, "source_check", None)
    if callable(source_check):
        source_checks.append(source_check())

    return GlobalAIReport(
        items=tuple(ranked_items),
        metadata={
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "report_type": "global-ai",
            "limit": limit,
            "universe_size": len(universe),
            "fundamentals": "finimpulse",
        },
        source_checks=tuple(source_checks),
    )


def valuation_summary(research: CompanyResearch) -> str:
    financials = research.financials
    metrics = [
        _metric("P/E", financials.pe_ratio),
        _metric("P/B", financials.price_to_book),
        _metric("EV/EBIT", financials.ev_to_ebit),
    ]
    summary = "; ".join(metric for metric in metrics if metric)
    if summary:
        return summary
    return "No direct valuation multiple available"


def quality_summary(research: CompanyResearch) -> str:
    financials = research.financials
    metrics = [
        _percentage_metric("Operating margin", financials.operating_margin_pct),
        _metric("debt/equity", financials.debt_to_equity),
    ]
    summary = "; ".join(metric for metric in metrics if metric)
    if summary:
        return summary
    return "Operating margin and balance-sheet leverage unavailable"


def growth_summary(research: CompanyResearch) -> str:
    growth = _percentage_metric("Revenue growth", research.financials.revenue_growth_pct)
    return growth or "Revenue growth unavailable"


def _parse_universe_entry(
    raw_entry: dict[str, Any], index: int
) -> GlobalAIUniverseEntry:
    values: dict[str, str] = {}
    for field_name in REQUIRED_UNIVERSE_FIELDS:
        value = raw_entry.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"global AI universe entry {index} missing {field_name}"
            )
        values[field_name] = " ".join(value.split())
    return GlobalAIUniverseEntry(
        name=values["name"],
        ticker=values["ticker"].upper(),
        provider_symbol=values["provider_symbol"].upper(),
        country=values["country"].upper(),
        exchange=values["exchange"],
        currency=values["currency"].upper(),
        sector=values["sector"],
        ai_category=values["ai_category"],
        ai_thesis=values["ai_thesis"],
    )


def _candidate_item(
    entry: GlobalAIUniverseEntry, fundamentals_provider
) -> GlobalAIReportItem:
    research = _base_research(entry)
    snapshot = fundamentals_provider.get_fundamentals_for_symbol(
        entry.provider_symbol, fallback_currency=entry.currency
    )
    if snapshot is None:
        research = replace(
            research,
            risks=("missing FinImpulse fundamentals",),
            data_quality=DataQuality.THIN,
        )
    else:
        research = _merge_snapshot(research, snapshot)
    score = score_global_ai_candidate(research, entry)
    return GlobalAIReportItem(
        rank=0,
        entry=entry,
        research=research,
        score=score,
        valuation_summary=valuation_summary(research),
        quality_summary=quality_summary(research),
        growth_summary=growth_summary(research),
        risk_flags=(*research.risks, *score.warnings),
    )


def _base_research(entry: GlobalAIUniverseEntry) -> CompanyResearch:
    return CompanyResearch(
        company=Company(
            name=entry.name,
            ticker=entry.ticker,
            country=entry.country,
            exchange=entry.exchange,
            segment=ListingSegment.OTHER_PUBLIC,
            sector=entry.sector,
            currency=entry.currency,
            business_description=entry.ai_thesis,
        ),
        financials=FinancialSnapshot(data_quality=DataQuality.THIN),
        data_quality=DataQuality.THIN,
    )


def _merge_snapshot(
    research: CompanyResearch, snapshot
) -> CompanyResearch:
    company = research.company
    if snapshot.market_cap_eur_m is not None:
        company = replace(company, market_cap_eur_m=snapshot.market_cap_eur_m)
    if snapshot.business_description is not None:
        company = replace(company, business_description=snapshot.business_description)
    if snapshot.ir_url is not None:
        company = replace(company, ir_url=snapshot.ir_url)

    evidence = research.evidence
    if snapshot.evidence is not None:
        evidence = (*evidence, snapshot.evidence)

    return replace(
        research,
        company=company,
        financials=snapshot.financials,
        evidence=evidence,
        data_quality=snapshot.financials.data_quality,
    )


def _valuation_score(
    financials: FinancialSnapshot, reasons: list[str], warnings: list[str]
) -> float:
    score = 0.0
    pe = financials.pe_ratio
    if pe is not None:
        if 0 < pe <= 20:
            score += 14.0
            reasons.append("reasonable P/E")
        elif pe <= 35:
            score += 9.0
            reasons.append("reasonable P/E")
        elif pe <= 55:
            score += 4.0
        else:
            warnings.append("valuation risk: high P/E")

    pb = financials.price_to_book
    if pb is not None:
        if 0 < pb <= 5:
            score += 6.0
        elif pb <= 10:
            score += 3.0
        else:
            warnings.append("valuation risk: high P/B")

    ev = financials.ev_to_ebit
    if ev is not None:
        if 0 < ev <= 20:
            score += 10.0
        elif ev <= 35:
            score += 5.0
        else:
            warnings.append("valuation risk: high EV/EBIT")

    if (
        _missing_direct_valuation(financials)
        and (financials.revenue_eur_m is not None or financials.net_income_eur_m is not None)
    ):
        score += 5.0
        reasons.append("valuation proxy available")

    return min(score, 30.0)


def _quality_score(
    research: CompanyResearch, reasons: list[str], warnings: list[str]
) -> float:
    financials = research.financials
    score = 0.0
    margin = financials.operating_margin_pct
    if margin is not None:
        if margin >= 30:
            score += 18.0
            reasons.append("profitable AI-exposed business")
        elif margin >= 15:
            score += 13.0
            reasons.append("profitable AI-exposed business")
        elif margin >= 0:
            score += 7.0
        else:
            warnings.append("negative operating margin")

    debt_to_equity = financials.debt_to_equity
    if debt_to_equity is not None:
        if debt_to_equity <= 0.5:
            score += 7.0
            reasons.append("conservative balance sheet")
        elif debt_to_equity <= 1.5:
            score += 4.0

    if research.company.business_description:
        score += 5.0
    return min(score, 30.0)


def _growth_score(
    financials: FinancialSnapshot, reasons: list[str], warnings: list[str]
) -> float:
    growth = financials.revenue_growth_pct
    if growth is None:
        return 0.0
    if growth >= 25:
        reasons.append("strong revenue growth")
        return 20.0
    if growth >= 15:
        reasons.append("strong revenue growth")
        return 16.0
    if growth >= 5:
        return 10.0
    if growth >= 0:
        return 5.0
    warnings.append("revenue declined")
    return 0.0


def _ai_relevance_score(entry: GlobalAIUniverseEntry, reasons: list[str]) -> float:
    if entry.ai_category in HIGH_RELEVANCE_CATEGORIES:
        reasons.append("direct AI infrastructure exposure")
        return 10.0
    if entry.ai_category in MEDIUM_HIGH_RELEVANCE_CATEGORIES:
        reasons.append("strong AI platform exposure")
        return 8.0
    if entry.ai_category == "Enterprise AI software":
        reasons.append("enterprise AI software exposure")
        return 7.0
    if entry.ai_category:
        return 5.0
    return 0.0


def _missing_direct_valuation(financials: FinancialSnapshot) -> bool:
    return all(
        value is None
        for value in (financials.pe_ratio, financials.price_to_book, financials.ev_to_ebit)
    )


def _metric(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label} {value:g}"


def _percentage_metric(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label} {value:.1f}%"
