from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataQuality(str, Enum):
    GOOD = "good"
    PARTIAL = "partial"
    THIN = "thin"


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
class Company:
    name: str
    ticker: str
    country: str
    exchange: str
    segment: ListingSegment
    sector: str | None = None
    market_cap_eur_m: float | None = None
    currency: str | None = None
    ir_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "country", self.country.strip().upper())


@dataclass(frozen=True)
class FinancialSnapshot:
    price: float | None = None
    currency: str | None = None
    pe_ratio: float | None = None
    price_to_book: float | None = None
    ev_to_ebit: float | None = None
    net_cash_eur_m: float | None = None
    debt_to_equity: float | None = None
    revenue_growth_pct: float | None = None
    operating_margin_pct: float | None = None
    one_year_return_pct: float | None = None
    distance_from_52w_high_pct: float | None = None
    average_daily_value_eur: float | None = None
    data_quality: DataQuality = DataQuality.THIN


@dataclass(frozen=True)
class CompanyResearch:
    company: Company
    financials: FinancialSnapshot
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    data_quality: DataQuality = DataQuality.THIN


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


@dataclass(frozen=True)
class SourceCheck:
    name: str
    status: str
    detail: str
