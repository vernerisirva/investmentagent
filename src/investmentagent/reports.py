from __future__ import annotations

from investmentagent.models import (
    Company,
    CompanyResearch,
    DeepDiveReport,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    WatchlistItem,
)
from investmentagent.providers import ResearchProvider
from investmentagent.scoring import score_research


WATCHLIST_STRATEGIES = ("balanced", "long-term", "trading", "momentum", "discovery")


def normalize_watchlist_strategy(strategy: str) -> str:
    normalized = strategy.strip().lower()
    if normalized not in WATCHLIST_STRATEGIES:
        allowed = ", ".join(WATCHLIST_STRATEGIES)
        raise ValueError(f"strategy must be one of: {allowed}")
    return normalized


def build_watchlist(
    provider: ResearchProvider,
    countries: tuple[str, ...],
    limit: int,
    include_first_north: bool,
    min_market_cap: float | None = None,
    max_market_cap: float | None = None,
    sector: str | None = None,
    strategy: str = "balanced",
) -> list[WatchlistItem]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    strategy = normalize_watchlist_strategy(strategy)

    companies = provider.list_companies(countries, include_first_north)
    scored_items: list[WatchlistItem] = []
    for company in companies:
        if not _company_matches_filters(company, min_market_cap, max_market_cap, sector):
            continue
        try:
            research = _get_base_company_research(provider, company)
        except Exception:
            continue
        score = _score_for_strategy(research, strategy)
        scored_items.append(
            WatchlistItem(rank=0, research=research, score=score)
        )

    enrichment_candidates = _watchlist_enrichment_candidates(provider, scored_items)
    if enrichment_candidates:
        _prepare_watchlist_enrichment(provider, enrichment_candidates)
        enriched_keys = {
            (company.ticker, company.country) for company in enrichment_candidates
        }
        rescored_items: list[WatchlistItem] = []
        for item in scored_items:
            company = item.research.company
            if (company.ticker, company.country) not in enriched_keys:
                rescored_items.append(item)
                continue
            try:
                research = _get_company_research(provider, company)
            except Exception:
                rescored_items.append(item)
                continue
            rescored_items.append(
                WatchlistItem(
                    rank=0,
                    research=research,
                    score=_score_for_strategy(research, strategy),
                )
            )
        scored_items = rescored_items

    ranked_items = sorted(
        scored_items,
        key=lambda item: (-item.score.total, item.research.company.ticker),
    )[:limit]

    return [
        WatchlistItem(rank=rank, research=item.research, score=item.score)
        for rank, item in enumerate(ranked_items, start=1)
    ]


def _get_company_research(provider: ResearchProvider, company: Company) -> CompanyResearch:
    get_company_research = getattr(provider, "get_company_research", None)
    if callable(get_company_research):
        return get_company_research(company)
    return provider.get_research(company.ticker)


def _get_base_company_research(provider: ResearchProvider, company: Company) -> CompanyResearch:
    get_base_company_research = getattr(provider, "get_base_company_research", None)
    if callable(get_base_company_research):
        return get_base_company_research(company)
    return _get_company_research(provider, company)


def _watchlist_enrichment_candidates(
    provider: ResearchProvider, scored_items: list[WatchlistItem]
) -> tuple[Company, ...]:
    budget = getattr(provider, "max_enrichments", None)
    if budget is None or budget < 1:
        return ()
    ranked_items = sorted(
        scored_items,
        key=lambda item: (-item.score.total, item.research.company.ticker),
    )
    return tuple(item.research.company for item in ranked_items[:budget])


def _prepare_watchlist_enrichment(
    provider: ResearchProvider, companies: tuple[Company, ...]
) -> None:
    prepare_watchlist_enrichment = getattr(provider, "prepare_watchlist_enrichment", None)
    if callable(prepare_watchlist_enrichment):
        prepare_watchlist_enrichment(companies)


def _score_for_strategy(research: CompanyResearch, strategy: str) -> ScoreBreakdown:
    score = score_research(research)
    positive_adjustment, negative_adjustment = _strategy_adjustments(research, strategy)
    catalyst = round(score.catalyst + positive_adjustment, 2)
    risk_penalty = round(score.risk_penalty + negative_adjustment, 2)
    total = (
        score.value
        + score.discovery
        + catalyst
        - risk_penalty
        - score.data_quality_penalty
    )
    reasons = score.reasons
    warnings = score.warnings
    if positive_adjustment:
        reasons = (*reasons, f"{strategy} strategy adjustment applied")
    if negative_adjustment:
        warnings = (*warnings, f"{strategy} strategy adjustment applied")
    return ScoreBreakdown(
        value=score.value,
        discovery=score.discovery,
        catalyst=catalyst,
        risk_penalty=risk_penalty,
        data_quality_penalty=score.data_quality_penalty,
        total=round(total, 2),
        reasons=reasons,
        warnings=warnings,
    )


def _strategy_adjustments(research: CompanyResearch, strategy: str) -> tuple[float, float]:
    if strategy == "momentum":
        return 0.0, 0.0

    catalysts = tuple(item.lower() for item in research.catalysts)
    risks = tuple(item.lower() for item in research.risks)
    all_signals = catalysts + risks

    positive_adjustment = 0.0
    negative_adjustment = 0.0
    if _has_signal(all_signals, "Extreme intraday spike"):
        negative_adjustment += 18.0
    if _has_signal(all_signals, "Missing live turnover"):
        negative_adjustment += 12.0
    if _has_signal(all_signals, "Low live turnover"):
        negative_adjustment += 10.0
    if _has_signal(all_signals, "Speculative low-price share"):
        negative_adjustment += 8.0

    financials = research.financials
    if strategy == "long-term":
        if _has_signal(catalysts, "intraday momentum"):
            negative_adjustment += 10.0
        if financials.pe_ratio is not None and financials.pe_ratio <= 12:
            positive_adjustment += 6.0
        if financials.price_to_book is not None and financials.price_to_book <= 1.2:
            positive_adjustment += 4.0
        if financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0:
            positive_adjustment += 4.0
    elif strategy == "trading":
        if _has_signal(catalysts, "High live turnover"):
            positive_adjustment += 6.0
        if _has_signal(catalysts, "Moderate live turnover"):
            positive_adjustment += 3.0
        if _has_signal(catalysts, "Strong intraday momentum"):
            positive_adjustment += 5.0
        if _has_signal(all_signals, "Extreme intraday spike"):
            negative_adjustment += 8.0
    elif strategy == "discovery":
        if research.company.segment == ListingSegment.FIRST_NORTH:
            positive_adjustment += 4.0
        if _has_signal(all_signals, "Extreme intraday spike") or _has_signal(
            all_signals, "Missing live turnover"
        ):
            negative_adjustment += 10.0
    return positive_adjustment, negative_adjustment


def _has_signal(signals: tuple[str, ...], needle: str) -> bool:
    normalized = needle.lower()
    return any(normalized in signal for signal in signals)


def _company_matches_filters(
    company: Company,
    min_market_cap: float | None,
    max_market_cap: float | None,
    sector: str | None,
) -> bool:
    if min_market_cap is not None and (
        company.market_cap_eur_m is None or company.market_cap_eur_m < min_market_cap
    ):
        return False
    if max_market_cap is not None and (
        company.market_cap_eur_m is None or company.market_cap_eur_m > max_market_cap
    ):
        return False
    if sector is not None:
        company_sector = (company.sector or "").strip().lower()
        if company_sector != sector.strip().lower():
            return False
    return True


def build_deep_dive(provider: ResearchProvider, ticker: str) -> DeepDiveReport:
    research = provider.get_research(ticker)
    score = score_research(research)
    company = research.company
    financials = research.financials

    sector = company.sector or "unknown sector"
    business_summary = (
        f"{company.name} is a {company.country}-listed {sector} company on "
        f"{company.exchange}."
    )

    valuation_view = _valuation_view(financials, research.evidence)

    return DeepDiveReport(
        research=research,
        score=score,
        business_summary=business_summary,
        why_it_appeared=score.reasons
        or ("Scoring did not surface a specific reason; manual triage is needed.",),
        valuation_view=valuation_view,
        bull_case=research.catalysts
        or ("No explicit catalyst is available in the current research fixture.",),
        base_case=(
            "The evidence is triage-level only, so this is a watchlist candidate rather "
            "than an investment conclusion.",
        ),
        bear_case=research.risks
        or ("No explicit risk is available in the current research fixture.",),
        next_manual_checks=(
            "Review the latest annual and interim reports.",
            "Check company announcements plus insider and ownership disclosures.",
            "Verify liquidity, trading volume, and bid/ask spread.",
            "Compare valuation against Nordic peers.",
        ),
    )


def _valuation_view(
    financials: FinancialSnapshot, evidence_items: tuple[Evidence, ...]
) -> tuple[str, ...]:
    valuation_items: list[str] = []
    if financials.price is not None and financials.currency:
        if any(evidence.source == "nasdaq" for evidence in evidence_items):
            valuation_items.append(
                f"Live price is {financials.price:g} {financials.currency} from Nasdaq Nordic."
            )
        else:
            valuation_items.append(f"Price is {financials.price:g} {financials.currency}.")
    valuation_items.extend(
        (
            _metric_sentence("P/E", financials.pe_ratio),
            _metric_sentence("Price/book", financials.price_to_book),
            _net_cash_or_debt_sentence(financials.net_cash_eur_m),
        )
    )
    return tuple(valuation_items)


def _metric_sentence(label: str, value: float | None) -> str:
    if value is None or (label == "P/E" and value <= 0):
        return f"{label} is unavailable in the current dataset."
    return f"{label} is {value:g}."


def _net_cash_or_debt_sentence(net_cash_eur_m: float | None) -> str:
    if net_cash_eur_m is None:
        return "Net cash or net debt is unavailable in the current dataset."
    if net_cash_eur_m >= 0:
        return f"Net cash is EUR {net_cash_eur_m:g}m."
    return f"Net debt is EUR {abs(net_cash_eur_m):g}m."
