from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketDayStatus:
    market: str
    day: date
    is_open: bool
    reason: str | None = None


@dataclass(frozen=True)
class MarketSession:
    market: str
    day: date
    opens_at: datetime
    closes_at: datetime
    is_half_day: bool


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

_MARKET_TIME_ZONES = {
    "stockholm": ZoneInfo("Europe/Stockholm"),
    "helsinki": ZoneInfo("Europe/Helsinki"),
}

_REGULAR_TRADING_HOURS = {
    "stockholm": (time(9, 0), time(17, 30)),
    "helsinki": (time(10, 0), time(18, 30)),
}

_STOCKHOLM_HALF_DAY_CLOSE = time(13, 0)


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


def market_session(day: date, market: str) -> MarketSession | None:
    normalized_market = normalize_market(market)
    if not market_day_status(day, normalized_market).is_open:
        return None
    open_time, regular_close = _REGULAR_TRADING_HOURS[normalized_market]
    is_half_day = day in _half_days(day.year, normalized_market)
    close_time = (
        _STOCKHOLM_HALF_DAY_CLOSE
        if normalized_market == "stockholm" and is_half_day
        else regular_close
    )
    time_zone = _MARKET_TIME_ZONES[normalized_market]
    return MarketSession(
        market=normalized_market,
        day=day,
        opens_at=datetime.combine(day, open_time, tzinfo=time_zone),
        closes_at=datetime.combine(day, close_time, tzinfo=time_zone),
        is_half_day=is_half_day,
    )


def first_session_closing_after(decision_at: datetime, market: str) -> MarketSession:
    if decision_at.tzinfo is None:
        raise ValueError("decision timestamp must be timezone-aware")
    normalized_market = normalize_market(market)
    local_day = decision_at.astimezone(_MARKET_TIME_ZONES[normalized_market]).date()
    candidate = local_day
    while True:
        session = market_session(candidate, normalized_market)
        if session is not None and session.closes_at > decision_at:
            return session
        candidate += timedelta(days=1)


def advance_market_sessions(day: date, session_count: int, market: str) -> MarketSession:
    if (
        isinstance(session_count, bool)
        or not isinstance(session_count, int)
        or session_count < 0
    ):
        raise ValueError("session count must be a non-negative integer")
    normalized_market = normalize_market(market)
    if market_session(day, normalized_market) is None:
        raise ValueError("starting day must be an open market session")
    remaining = session_count
    candidate = day
    while remaining:
        candidate += timedelta(days=1)
        if market_session(candidate, normalized_market) is not None:
            remaining -= 1
    result = market_session(candidate, normalized_market)
    if result is None:  # pragma: no cover - protected by the loop invariants
        raise AssertionError("market-session calculation produced a closed day")
    return result


def market_for_country(country: str) -> str:
    normalized = country.strip().upper()
    if normalized == "SE":
        return "stockholm"
    if normalized == "FI":
        return "helsinki"
    raise ValueError(f"unsupported Nordic country: {country!r}")


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


def _half_days(year: int, market: str) -> set[date]:
    if market != "stockholm":
        return set()
    easter = _easter_sunday(year)
    ascension_day = easter + timedelta(days=39)
    candidates = {
        date(year, 1, 5),
        easter - timedelta(days=3),
        date(year, 4, 30),
        ascension_day - timedelta(days=1),
        _all_saints_eve(year),
    }
    # Nasdaq Stockholm's equity calendar uses these recurring half-day rules.
    # A candidate that falls on a weekend or full holiday is not a session.
    return {
        day
        for day in candidates
        if day.weekday() < 5 and _closed_reason(day, market) is None
    }


def _all_saints_eve(year: int) -> date:
    for day in range(31, 38):
        candidate = date(year, 10, 31) + timedelta(days=day - 31)
        if candidate.weekday() == 5:
            return candidate - timedelta(days=1)
    raise AssertionError("All Saints' Day must fall between October 31 and November 6")


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
