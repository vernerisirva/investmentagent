"""Decision-time comparisons for public idea reports (presentation only).

Everything here describes the ranked universe X of the run that is being reported. It never
feeds ranking, selection, benchmarks or analysis, and it never reads fundamentals from any
other point in time: rows are built from the in-memory universe of the same scoring run that
writes X, so historical reports cannot be recomputed with later data.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from investmentagent.benchmarks import MIN_ALTERNATIVES
from investmentagent.fundamentals_cache import company_cache_identity
from investmentagent.long_term_quality import assess_long_term_gate, assess_long_term_quality
from investmentagent.selection import gate_order


PEER_MINIMUM_OBSERVATIONS = MIN_ALTERNATIVES
CLEARLY_FAVOURABLE_PERCENTILE = 75.0
CLEARLY_UNFAVOURABLE_PERCENTILE = 25.0
LISTING_PEERS = "listing peers"
ALL_ELIGIBLE = "all eligible X"


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    direction: str  # "lower" or "higher" is better; "neutral" only positions the value
    unit: str
    valid: Callable[[float], bool]
    invalid_label: str
    favourable_phrase: str
    unfavourable_phrase: str
    sentence_label: str = ""
    invalid_risk: str = ""

    @property
    def noun(self) -> str:
        return self.sentence_label or self.label


def _positive(value: float) -> bool:
    return value > 0


def _non_negative(value: float) -> bool:
    return value >= 0


def _any_finite(value: float) -> bool:
    return True


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("pe_ratio", "P/E", "lower", "x", _positive,
               "Not meaningful (zero or negative earnings)", "cheaper than", "more expensive than",
               invalid_risk="Zero or negative earnings"),
    MetricSpec("price_to_book", "P/B", "lower", "x", _positive,
               "Not meaningful (zero or negative book value)", "cheaper than", "more expensive than",
               invalid_risk="Zero or negative book value"),
    MetricSpec("ev_to_ebit", "EV/EBIT", "lower", "x", _positive,
               "Not meaningful (zero or negative EBIT)", "cheaper than", "more expensive than",
               invalid_risk="Zero or negative EBIT"),
    MetricSpec("operating_margin_pct", "Operating margin", "higher", "%", _any_finite,
               "Not meaningful", "higher than", "lower than", sentence_label="operating margin"),
    MetricSpec("revenue_growth_pct", "Revenue growth", "higher", "%", _any_finite,
               "Not meaningful", "higher than", "lower than", sentence_label="revenue growth"),
    MetricSpec("debt_to_equity", "Debt/equity", "lower", "x", _non_negative,
               "Not meaningful (negative equity)", "less leveraged than", "more leveraged than",
               sentence_label="debt/equity", invalid_risk="Negative equity"),
    MetricSpec("market_cap_eur_m", "Market cap (EUR m)", "neutral", "EUR m", _positive,
               "Not meaningful", "larger than", "smaller than", sentence_label="market cap"),
    MetricSpec("average_daily_value_eur", "Avg. daily traded value (EUR)", "neutral", "EUR",
               _non_negative, "Not meaningful", "more traded than", "less traded than",
               sentence_label="trading volume"),
)
METRICS_BY_KEY = {spec.key: spec for spec in METRICS}


@dataclass(frozen=True)
class ComparisonRow:
    """One member of X with the decision-time values a report may compare."""

    company_id: str
    ticker: str
    name: str
    country: str
    venue: str
    rank: int
    score_total: float
    components: Mapping[str, float]
    gate_tier: str | None
    metrics: Mapping[str, float | None]
    data_quality: str
    cache_state: str | None = None
    retrieved_at: str | None = None
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PeerStat:
    level: str
    group: str
    population: int
    usable: int
    invalid: int
    missing: int
    median: float | None
    percentile: float | None
    status: str  # "ok", "unavailable", "not_meaningful", "missing"


@dataclass(frozen=True)
class MetricComparison:
    spec: MetricSpec
    value: float | None
    value_status: str  # "valid", "invalid", "missing"
    levels: tuple[PeerStat, ...]

    def level(self, name: str) -> PeerStat | None:
        return next((stat for stat in self.levels if stat.level == name), None)


@dataclass(frozen=True)
class IdeaComparison:
    row: ComparisonRow
    universe_size: int
    universe_median_score: float | None
    score_percentile: float | None
    component_percentiles: Mapping[str, float | None]
    base_rank: int
    included_by_country_minimum: bool
    metrics: tuple[MetricComparison, ...]
    fundamentals_age_days: int | None
    listing_group: str
    listing_group_size: int
    listing_group_fresh_share: float | None

    @property
    def score_minus_median(self) -> float | None:
        if self.universe_median_score is None:
            return None
        return self.row.score_total - self.universe_median_score

    def metric(self, key: str) -> MetricComparison:
        return next(item for item in self.metrics if item.spec.key == key)


@dataclass(frozen=True)
class ReportComparison:
    strategy: str
    decision_at: str | None
    universe_size: int
    country_counts: Mapping[str, int]
    public_limit: int
    ideas: tuple[IdeaComparison, ...]
    cache_recorded: bool
    source_universe_size: int | None = None


CONTEXT_FIELDS = ("one_year_return_pct", "distance_from_52w_high_pct")


def comparison_rows(ranked_items: Sequence[Any], *, strategy: str,
                    evaluation_rows: Sequence[Any] | None = None) -> tuple[ComparisonRow, ...]:
    """Rows for X from the same run's ranked items, joined to X records when persisted.

    `ranked_items` are the run's in-memory `WatchlistItem`s (the universe X is written from).
    `evaluation_rows` are that run's `EvaluationCompanyRow`s; they supply the recorded cache
    state, gate tier and long-term quality adjustment. Without them freshness is unknown.
    """
    recorded = {row.company_id: row for row in evaluation_rows or ()}
    rows = []
    for item in ranked_items:
        research, score = item.research, item.score
        company, financials = research.company, research.financials
        company_id = company_cache_identity(company)
        evaluation_row = recorded.get(company_id)
        if evaluation_rows is not None and evaluation_row is None:
            raise ValueError(f"ranked company missing from the evaluation snapshot: {company_id}")
        if evaluation_row is not None and evaluation_row.rank != item.rank:
            raise ValueError(f"ranked company disagrees with the evaluation snapshot: {company_id}")
        components = {
            "value": score.value, "discovery": score.discovery, "catalyst": score.catalyst,
            "risk_penalty": score.risk_penalty, "data_quality_penalty": score.data_quality_penalty,
        }
        gate_tier = None
        if strategy == "long-term":
            long_term = evaluation_row.long_term if evaluation_row is not None else None
            if long_term is not None:
                gate_tier, quality = long_term["gate_tier"], long_term["quality_adjustment"]
            else:
                gate_tier = assess_long_term_gate(research).tier.value
                quality = assess_long_term_quality(research).quality_adjustment
            components["quality_adjustment"] = quality
            components["catalyst"] = round(score.catalyst - quality, 2)
        metrics = {spec.key: getattr(financials, spec.key, None) for spec in METRICS}
        metrics["market_cap_eur_m"] = company.market_cap_eur_m
        missing = tuple(key for key in (*metrics, *CONTEXT_FIELDS)
                        if (metrics[key] if key in metrics else getattr(financials, key)) is None)
        cache = evaluation_row.cache if evaluation_row is not None else {}
        rows.append(ComparisonRow(
            company_id=company_id, ticker=company.ticker, name=company.name,
            country=company.country, venue=company.segment.value, rank=item.rank,
            score_total=score.total, components=components, gate_tier=gate_tier,
            metrics=metrics, data_quality=research.data_quality.value,
            cache_state=cache.get("state"), retrieved_at=cache.get("retrieved_at"),
            missing_inputs=missing,
        ))
    return tuple(rows)


def mid_rank_percentile(value: float, others: Sequence[float]) -> float | None:
    """Share of `others` strictly below `value`, counting ties as half, in percent."""
    if not others:
        return None
    below = sum(other < value for other in others)
    ties = sum(other == value for other in others)
    return 100.0 * (below + 0.5 * ties) / len(others)


def favourable_percentile(value: float, peers: Sequence[float], direction: str) -> float | None:
    """Share of peers that are less favourable than `value` (ties half), in percent.

    For lower-is-better metrics a peer is less favourable when it is higher, so the
    interpretation is never reversed. Neutral metrics position the value from below.
    """
    if direction == "lower":
        return mid_rank_percentile(-value, [-peer for peer in peers])
    if direction in ("higher", "neutral"):
        return mid_rank_percentile(value, peers)
    raise ValueError(f"unknown metric direction: {direction}")


def median_or_none(values: Iterable[float]) -> float | None:
    values = list(values)
    return statistics.median(values) if values else None


def classify_value(spec: MetricSpec, value: Any) -> str:
    if not _finite(value):
        return "missing"
    return "valid" if spec.valid(float(value)) else "invalid"


def peer_stat(spec: MetricSpec, value: float | None, value_status: str,
              peers: Sequence[ComparisonRow], *, level: str, group: str) -> PeerStat:
    usable: list[float] = []
    invalid = missing = 0
    for peer in peers:
        peer_value = peer.metrics.get(spec.key)
        status = classify_value(spec, peer_value)
        if status == "valid":
            usable.append(float(peer_value))
        elif status == "invalid":
            invalid += 1
        else:
            missing += 1
    median = median_or_none(usable)
    if value_status == "missing":
        status, percentile = "missing", None
    elif value_status == "invalid":
        status, percentile = "not_meaningful", None
    elif len(usable) < PEER_MINIMUM_OBSERVATIONS:
        status, percentile = "unavailable", None
    else:
        status, percentile = "ok", favourable_percentile(float(value), usable, spec.direction)
    return PeerStat(level=level, group=group, population=len(peers), usable=len(usable),
                    invalid=invalid, missing=missing,
                    median=median if len(usable) >= PEER_MINIMUM_OBSERVATIONS else None,
                    percentile=percentile, status=status)


def base_order_key(row: ComparisonRow, strategy: str) -> tuple:
    """The documented production ordering without the country minimum."""
    if strategy == "long-term":
        return (gate_order(row.gate_tier), -row.score_total, row.ticker)
    return (-row.score_total, row.ticker)


def compare_ideas(rows: Sequence[ComparisonRow], selected_ids: Sequence[str], *, strategy: str,
                  public_limit: int, decision_at: str | None, cache_recorded: bool,
                  source_universe_size: int | None = None) -> ReportComparison:
    by_id = {row.company_id: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate company identity in comparison universe")
    missing_selected = [company_id for company_id in selected_ids if company_id not in by_id]
    if missing_selected:
        raise ValueError(f"selected company missing from comparison universe: {missing_selected[0]}")
    scores = [row.score_total for row in rows]
    universe_median = median_or_none(scores)
    component_names = sorted({name for row in rows for name in row.components})
    base_keys = sorted(base_order_key(row, strategy) for row in rows)
    decision_time = _parse_timestamp(decision_at) if decision_at else None
    ideas = []
    for company_id in selected_ids:
        row = by_id[company_id]
        others = [other for other in rows if other.company_id != company_id]
        listing = [other for other in others
                   if (other.country, other.venue) == (row.country, row.venue)]
        group = f"{row.country} {row.venue.replace('_', ' ')}"
        metrics = []
        for spec in METRICS:
            value = row.metrics.get(spec.key)
            value_status = classify_value(spec, value)
            numeric = float(value) if value_status != "missing" else None
            metrics.append(MetricComparison(
                spec=spec, value=numeric, value_status=value_status,
                levels=(
                    peer_stat(spec, numeric, value_status, listing, level=LISTING_PEERS, group=group),
                    peer_stat(spec, numeric, value_status, others, level=ALL_ELIGIBLE, group="all eligible X"),
                ),
            ))
        component_percentiles = {}
        for name in component_names:
            own = row.components.get(name)
            values = [other.components[name] for other in others if name in other.components]
            if own is None or not values:
                component_percentiles[name] = None
            elif name.endswith("penalty"):
                component_percentiles[name] = favourable_percentile(own, values, "lower")
            else:
                component_percentiles[name] = mid_rank_percentile(own, values)
        own_key = base_order_key(row, strategy)
        base_rank = 1 + sum(key < own_key for key in base_keys)
        fresh_share = None
        if cache_recorded and listing:
            fresh_share = 100.0 * sum(peer.cache_state == "fresh" for peer in listing) / len(listing)
        ideas.append(IdeaComparison(
            row=row, universe_size=len(rows), universe_median_score=universe_median,
            score_percentile=mid_rank_percentile(row.score_total, [o.score_total for o in others]),
            component_percentiles=component_percentiles, base_rank=base_rank,
            included_by_country_minimum=base_rank > public_limit,
            metrics=tuple(metrics),
            fundamentals_age_days=_age_days(row.retrieved_at, decision_time),
            listing_group=group, listing_group_size=len(listing),
            listing_group_fresh_share=fresh_share,
        ))
    country_counts: dict[str, int] = {}
    for row in rows:
        country_counts[row.country] = country_counts.get(row.country, 0) + 1
    return ReportComparison(strategy=strategy, decision_at=decision_at, universe_size=len(rows),
                            country_counts=dict(sorted(country_counts.items())),
                            public_limit=public_limit, ideas=tuple(ideas),
                            cache_recorded=cache_recorded,
                            source_universe_size=source_universe_size)


def relative_summary(idea: IdeaComparison) -> str:
    """One factual sentence from available listing-peer percentiles; no thesis text."""
    favourable, unfavourable, neutral = [], [], []
    for item in idea.metrics:
        stat = item.level(LISTING_PEERS)
        if stat is None or stat.status != "ok" or stat.percentile is None:
            continue
        spec = item.spec
        if spec.direction == "neutral":
            if stat.percentile >= CLEARLY_FAVOURABLE_PERCENTILE:
                neutral.append(f"{spec.favourable_phrase} {_whole(stat.percentile)}% of peers "
                               f"on {spec.noun}")
            elif stat.percentile <= CLEARLY_UNFAVOURABLE_PERCENTILE:
                neutral.append(f"{spec.unfavourable_phrase} {_whole(100 - stat.percentile)}% of "
                               f"peers on {spec.noun}")
            continue
        if stat.percentile >= CLEARLY_FAVOURABLE_PERCENTILE:
            favourable.append(f"{spec.noun} ({spec.favourable_phrase} "
                              f"{_whole(stat.percentile)}% of peers)")
        elif stat.percentile <= CLEARLY_UNFAVOURABLE_PERCENTILE:
            unfavourable.append(f"{spec.noun} ({spec.unfavourable_phrase} "
                                f"{_whole(100 - stat.percentile)}% of peers)")
    parts = []
    if favourable:
        parts.append("stronger than most listing peers on " + _join(favourable))
    if unfavourable:
        parts.append("weaker than most listing peers on " + _join(unfavourable))
    if neutral:
        parts.append(_join(neutral))
    if not parts:
        return ("No clear relative strength or weakness among listing peers on the "
                "metrics with enough comparable data.")
    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _whole(value: float) -> int:
    return int(math.floor(value + 0.5))


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _finite(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("comparison timestamps must be timezone-aware")
    return parsed


def _age_days(retrieved_at: str | None, decision_time: datetime | None) -> int | None:
    if retrieved_at is None or decision_time is None:
        return None
    retrieved = _parse_timestamp(retrieved_at)
    if retrieved > decision_time:
        raise ValueError("fundamentals retrieved after the decision cannot be compared")
    return (decision_time - retrieved).days
