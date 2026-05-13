from __future__ import annotations

import re

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
    min_country_counts: dict[str, int] | None = None,
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

    enrichment_candidates = _watchlist_enrichment_candidates(
        provider,
        scored_items,
        limit=limit,
        min_country_counts=min_country_counts or {},
    )
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

    ranked_candidates = _rank_watchlist_items(_deduplicate_company_ideas(scored_items))
    ranked_items = _apply_min_country_counts(
        ranked_candidates,
        limit=limit,
        min_country_counts=min_country_counts or {},
    )

    return [
        WatchlistItem(rank=rank, research=item.research, score=item.score)
        for rank, item in enumerate(ranked_items, start=1)
    ]


def _apply_min_country_counts(
    ranked_items: list[WatchlistItem],
    limit: int,
    min_country_counts: dict[str, int],
) -> list[WatchlistItem]:
    selected = list(ranked_items[:limit])
    selected_keys = {_watchlist_item_key(item) for item in selected}

    for country, required_count in min_country_counts.items():
        normalized_country = country.upper()
        if required_count <= 0:
            continue
        current_count = sum(
            item.research.company.country == normalized_country for item in selected
        )
        missing_count = required_count - current_count
        if missing_count <= 0:
            continue

        replacements = [
            item
            for item in ranked_items[limit:]
            if item.research.company.country == normalized_country
            and _watchlist_item_key(item) not in selected_keys
        ][:missing_count]
        for replacement in replacements:
            removable_index = _lowest_ranked_removable_index(
                selected, min_country_counts
            )
            if removable_index is None:
                break
            removed = selected.pop(removable_index)
            selected_keys.remove(_watchlist_item_key(removed))
            selected.append(replacement)
            selected_keys.add(_watchlist_item_key(replacement))

    return _rank_watchlist_items(selected)


def _lowest_ranked_removable_index(
    selected: list[WatchlistItem], min_country_counts: dict[str, int]
) -> int | None:
    protected_counts = {country.upper(): count for country, count in min_country_counts.items()}
    country_counts: dict[str, int] = {}
    for item in selected:
        country = item.research.company.country
        country_counts[country] = country_counts.get(country, 0) + 1

    for index in range(len(selected) - 1, -1, -1):
        country = selected[index].research.company.country
        if country_counts[country] > protected_counts.get(country, 0):
            return index
    return None


def _watchlist_item_key(item: WatchlistItem) -> tuple[str, str]:
    company = item.research.company
    return (company.ticker, company.country)


def _deduplicate_company_ideas(items: list[WatchlistItem]) -> list[WatchlistItem]:
    selected_by_company: dict[str, WatchlistItem] = {}
    for item in items:
        company_key = _company_idea_key(item.research.company)
        selected = selected_by_company.get(company_key)
        if selected is None or _watchlist_rank_key(item) < _watchlist_rank_key(
            selected
        ):
            selected_by_company[company_key] = item
    return list(selected_by_company.values())


def _company_idea_key(company: Company) -> str:
    normalized_name = _normalize_company_name(company.name)
    if normalized_name:
        return normalized_name
    return f"{company.ticker}|{company.country}"


def _normalize_company_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    legal_suffixes = {
        "ab",
        "ag",
        "corp",
        "corporation",
        "inc",
        "limited",
        "ltd",
        "oy",
        "oyj",
        "plc",
        "publ",
    }
    share_classes = {"a", "b"}
    words = normalized.split()
    removable_suffixes = legal_suffixes | share_classes
    while words and words[-1] in removable_suffixes:
        words.pop()
    return " ".join(words)


def _rank_watchlist_items(items: list[WatchlistItem]) -> list[WatchlistItem]:
    return sorted(items, key=_watchlist_rank_key)


def _watchlist_rank_key(item: WatchlistItem) -> tuple[float, str]:
    company = item.research.company
    return (-item.score.total, company.ticker)


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
    provider: ResearchProvider,
    scored_items: list[WatchlistItem],
    limit: int,
    min_country_counts: dict[str, int],
) -> tuple[Company, ...]:
    budget = getattr(provider, "max_enrichments", None)
    if budget is None or budget < 1:
        return ()
    ranked_items = _rank_watchlist_items(_deduplicate_company_ideas(scored_items))
    constrained_items = _apply_min_country_counts(
        ranked_items,
        limit=limit,
        min_country_counts=min_country_counts,
    )
    return tuple(item.research.company for item in constrained_items[:budget])


def _prepare_watchlist_enrichment(
    provider: ResearchProvider, companies: tuple[Company, ...]
) -> None:
    prepare_watchlist_enrichment = getattr(provider, "prepare_watchlist_enrichment", None)
    if callable(prepare_watchlist_enrichment):
        prepare_watchlist_enrichment(companies)


def _score_for_strategy(research: CompanyResearch, strategy: str) -> ScoreBreakdown:
    score = score_research(research)
    if strategy == "long-term":
        return _long_term_score(research, score)

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


def _long_term_score(research: CompanyResearch, score: ScoreBreakdown) -> ScoreBreakdown:
    financials = research.financials
    reasons = tuple(
        reason for reason in score.reasons if not _is_trading_only_signal(reason)
    )
    catalyst = round(
        min(
            sum(
                8.0
                for catalyst_reason in research.catalysts
                if not _is_trading_only_signal(catalyst_reason)
            ),
            16.0,
        ),
        2,
    )

    quality_adjustment = 0.0
    quality_reasons: list[str] = []
    if financials.operating_margin_pct is not None and financials.operating_margin_pct > 0:
        quality_adjustment += 8.0
        quality_reasons.append(
            f"Positive operating margin ({financials.operating_margin_pct:.1f}%)"
        )
    if financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0:
        quality_adjustment += 6.0
        quality_reasons.append(f"Revenue growth ({financials.revenue_growth_pct:.1f}%)")
    if financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5:
        quality_adjustment += 4.0
        quality_reasons.append("Conservative debt/equity")
    if research.company.business_description:
        quality_adjustment += 3.0
        quality_reasons.append("Business description available from profile data")

    trading_penalty = 0.0
    has_intraday_signal = any(
        _is_intraday_signal(signal)
        for signal in (*research.catalysts, *research.risks)
    )
    if has_intraday_signal:
        trading_penalty += 18.0
    if any(
        _has_signal((signal.lower(),), "Extreme intraday spike")
        for signal in research.risks
    ):
        trading_penalty += 18.0
    missing_anchor_penalty = (
        12.0
        if has_intraday_signal and not _has_long_term_fundamental_anchor(financials)
        else 0.0
    )

    risk_penalty = round(
        score.risk_penalty + trading_penalty + missing_anchor_penalty, 2
    )
    total = (
        score.value
        + score.discovery
        + catalyst
        + quality_adjustment
        - risk_penalty
        - score.data_quality_penalty
    )
    warnings = score.warnings
    if trading_penalty:
        warnings = (*warnings, "long-term strategy penalty applied")
    if missing_anchor_penalty:
        warnings = (*warnings, "missing long-term fundamental support")

    return ScoreBreakdown(
        value=score.value,
        discovery=score.discovery,
        catalyst=round(catalyst + quality_adjustment, 2),
        risk_penalty=risk_penalty,
        data_quality_penalty=score.data_quality_penalty,
        total=round(total, 2),
        reasons=(*reasons, *quality_reasons),
        warnings=warnings,
    )


def _has_long_term_fundamental_anchor(financials: FinancialSnapshot) -> bool:
    return any(
        (
            financials.pe_ratio is not None and financials.pe_ratio <= 18,
            financials.price_to_book is not None and financials.price_to_book <= 2.0,
            financials.net_cash_eur_m is not None and financials.net_cash_eur_m > 0,
            financials.operating_margin_pct is not None
            and financials.operating_margin_pct > 0,
            financials.revenue_growth_pct is not None and financials.revenue_growth_pct > 0,
            financials.debt_to_equity is not None and financials.debt_to_equity <= 0.5,
        )
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


def _is_trading_only_signal(signal: str) -> bool:
    return (
        _is_intraday_signal(signal)
        or signal
        in {
            "Live price available from Nasdaq Nordic",
            "High live turnover",
            "Moderate live turnover",
        }
    )


def _is_intraday_signal(signal: str) -> bool:
    return "intraday momentum" in signal.lower()


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
