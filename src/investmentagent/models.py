from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class DataQuality(str, Enum):
    GOOD = "good"
    PARTIAL = "partial"
    THIN = "thin"


class ObservationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReportingPeriodType(str, Enum):
    TTM = "ttm"
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    MRQ = "mrq"
    FORWARD = "forward"
    POINT_IN_TIME = "point_in_time"


class ListingSegment(str, Enum):
    MAIN_MARKET = "main_market"
    FIRST_NORTH = "first_north"
    SPOTLIGHT = "spotlight"
    OTHER_PUBLIC = "other_public"


@dataclass(frozen=True)
class Evidence:
    label: str
    url: str
    source: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class FinancialObservation:
    canonical_field: str
    normalized_value: float | None
    provider: str
    source_metric: str
    as_of: str | None = None
    reporting_period: str | None = None
    period_type: ReportingPeriodType | None = None
    original_currency: str | None = None
    normalized_currency: str | None = None
    is_derived: bool = False
    derivation: str | None = None
    confidence: ObservationConfidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "normalized_value", _finite_number_or_none(self.normalized_value)
        )
        if self.original_currency is not None:
            object.__setattr__(
                self, "original_currency", self.original_currency.strip().upper() or None
            )
        if self.normalized_currency is not None:
            object.__setattr__(
                self,
                "normalized_currency",
                self.normalized_currency.strip().upper() or None,
            )


@dataclass(frozen=True)
class Company:
    name: str
    ticker: str
    country: str
    exchange: str
    segment: ListingSegment
    isin: str | None = None
    sector: str | None = None
    market_cap_eur_m: float | None = None
    currency: str | None = None
    ir_url: str | None = None
    business_description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "country", self.country.strip().upper())
        if self.isin is not None:
            object.__setattr__(self, "isin", self.isin.strip().upper() or None)
        object.__setattr__(
            self,
            "market_cap_eur_m",
            _finite_number_or_none(self.market_cap_eur_m),
        )


_FINANCIAL_NUMERIC_FIELDS = (
    "price",
    "pe_ratio",
    "price_to_book",
    "ev_to_ebit",
    "revenue_eur_m",
    "book_value_eur_m",
    "net_income_eur_m",
    "net_cash_eur_m",
    "debt_to_equity",
    "revenue_growth_pct",
    "operating_margin_pct",
    "one_year_return_pct",
    "distance_from_52w_high_pct",
    "average_daily_value_eur",
)


@dataclass(frozen=True)
class FinancialSnapshot:
    price: float | None = None
    currency: str | None = None
    pe_ratio: float | None = None
    price_to_book: float | None = None
    ev_to_ebit: float | None = None
    revenue_eur_m: float | None = None
    book_value_eur_m: float | None = None
    net_income_eur_m: float | None = None
    net_cash_eur_m: float | None = None
    debt_to_equity: float | None = None
    revenue_growth_pct: float | None = None
    operating_margin_pct: float | None = None
    one_year_return_pct: float | None = None
    distance_from_52w_high_pct: float | None = None
    average_daily_value_eur: float | None = None
    data_quality: DataQuality = DataQuality.THIN
    observations: tuple[FinancialObservation, ...] = ()

    def __post_init__(self) -> None:
        for field_name in _FINANCIAL_NUMERIC_FIELDS:
            object.__setattr__(
                self,
                field_name,
                _finite_number_or_none(getattr(self, field_name)),
            )

        observations_by_field: dict[str, FinancialObservation] = {}
        for observation in self.observations:
            if not isinstance(observation, FinancialObservation):
                continue
            if observation.canonical_field not in _FINANCIAL_NUMERIC_FIELDS:
                continue
            field_value = getattr(self, observation.canonical_field)
            if field_value is None or observation.normalized_value is None:
                continue
            if not math.isclose(
                field_value,
                observation.normalized_value,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                continue
            observations_by_field[observation.canonical_field] = observation
        object.__setattr__(self, "observations", tuple(observations_by_field.values()))

    def observation_for(self, canonical_field: str) -> FinancialObservation | None:
        return next(
            (
                observation
                for observation in self.observations
                if observation.canonical_field == canonical_field
            ),
            None,
        )


def _finite_number_or_none(value: float | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class FundamentalsSnapshot:
    symbol: str
    market_cap_eur_m: float | None = None
    business_description: str | None = None
    ir_url: str | None = None
    financials: FinancialSnapshot = field(
        default_factory=lambda: FinancialSnapshot(data_quality=DataQuality.PARTIAL)
    )
    evidence: Evidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self, "market_cap_eur_m", _finite_number_or_none(self.market_cap_eur_m)
        )


@dataclass(frozen=True)
class CompanyResearch:
    company: Company
    financials: FinancialSnapshot
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    data_quality: DataQuality = DataQuality.THIN

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalysts", tuple(self.catalysts))
        object.__setattr__(self, "risks", tuple(self.risks))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class ScoreBreakdown:
    value: float
    discovery: float
    catalyst: float
    risk_penalty: float
    data_quality_penalty: float
    total: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class WatchlistItem:
    rank: int
    research: CompanyResearch
    score: ScoreBreakdown


@dataclass(frozen=True)
class DeepDiveReport:
    research: CompanyResearch
    score: ScoreBreakdown
    business_summary: str = ""
    why_it_appeared: tuple[str, ...] = ()
    valuation_view: tuple[str, ...] = ()
    bull_case: tuple[str, ...] = ()
    base_case: tuple[str, ...] = ()
    bear_case: tuple[str, ...] = ()
    next_manual_checks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "why_it_appeared", tuple(self.why_it_appeared))
        object.__setattr__(self, "valuation_view", tuple(self.valuation_view))
        object.__setattr__(self, "bull_case", tuple(self.bull_case))
        object.__setattr__(self, "base_case", tuple(self.base_case))
        object.__setattr__(self, "bear_case", tuple(self.bear_case))
        object.__setattr__(self, "next_manual_checks", tuple(self.next_manual_checks))


@dataclass(frozen=True)
class SourceCheck:
    name: str
    status: str
    detail: str
