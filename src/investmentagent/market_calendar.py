from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class MarketDayStatus:
    market: str
    day: date
    is_open: bool
    reason: str | None = None


_MARKET_ALIASES = {
    "stockholm": "stockholm",
    "sto": "stockholm",
    "se": "stockholm",
    "sweden": "stockholm",
    "nasdaq-stockholm": "stockholm",
    "nasdaq stockholm": "stockholm",
    "helsinki": "helsinki",
    "hel": "helsinki",
    "fi": "helsinki",
    "finland": "helsinki",
    "nasdaq-helsinki": "helsinki",
    "nasdaq helsinki": "helsinki",
}


def normalize_market(raw_market: str) -> str:
    normalized = raw_market.strip().lower()
    try:
        return _MARKET_ALIASES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted({"stockholm", "helsinki"}))
        raise ValueError(f"unsupported market {raw_market!r}; supported markets: {supported}") from exc


def market_day_status(day: date, market: str) -> MarketDayStatus:
    normalized_market = normalize_market(market)
    reason = _closed_reason(day, normalized_market)
    return MarketDayStatus(
        market=normalized_market,
        day=day,
        is_open=reason is None,
        reason=reason,
    )


def are_markets_open(day: date, markets: Iterable[str]) -> bool:
    return all(market_day_status(day, market).is_open for market in markets)


def _closed_reason(day: date, market: str) -> str | None:
    if day.weekday() >= 5:
        return "Weekend"

    closed_dates = _common_closed_dates(day.year)
    closed_dates.update(_market_specific_closed_dates(day.year, market))
    return closed_dates.get(day)


def _common_closed_dates(year: int) -> dict[date, str]:
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1): "New Year's Day",
        date(year, 1, 6): "Epiphany",
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday",
        date(year, 5, 1): "May Day",
        easter + timedelta(days=39): "Ascension Day",
        _midsummer_eve(year): "Midsummer Eve",
        date(year, 12, 24): "Christmas Eve",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 26): "Boxing Day",
        date(year, 12, 31): "New Year's Eve",
    }


def _market_specific_closed_dates(year: int, market: str) -> dict[date, str]:
    if market == "stockholm":
        return {
            date(year, 6, 6): "Swedish National Day",
        }
    if market == "helsinki":
        return {
            date(year, 12, 6): "Finnish Independence Day",
        }
    return {}


def _midsummer_eve(year: int) -> date:
    for day in range(19, 26):
        midsummer_candidate = date(year, 6, day)
        if midsummer_candidate.weekday() == 4:
            return midsummer_candidate
    raise AssertionError("Midsummer Eve must fall between June 19 and June 25")


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)
