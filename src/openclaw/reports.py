from __future__ import annotations

from openclaw.models import DeepDiveReport, WatchlistItem
from openclaw.providers import ResearchProvider
from openclaw.scoring import score_research


def build_watchlist(
    provider: ResearchProvider,
    countries: tuple[str, ...],
    limit: int,
    include_first_north: bool,
) -> list[WatchlistItem]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    companies = provider.list_companies(countries, include_first_north)
    scored_items: list[WatchlistItem] = []
    for company in companies:
        research = provider.get_research(company.ticker)
        scored_items.append(
            WatchlistItem(rank=0, research=research, score=score_research(research))
        )
    ranked_items = sorted(
        scored_items,
        key=lambda item: (-item.score.total, item.research.company.ticker),
    )[:limit]

    return [
        WatchlistItem(rank=rank, research=item.research, score=item.score)
        for rank, item in enumerate(ranked_items, start=1)
    ]


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

    valuation_view = (
        _metric_sentence("P/E", financials.pe_ratio),
        _metric_sentence("Price/book", financials.price_to_book),
        _net_cash_or_debt_sentence(financials.net_cash_eur_m),
    )

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
