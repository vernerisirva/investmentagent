from datetime import date, datetime, timezone

from investmentagent.market_calendar import (
    advance_market_sessions,
    are_markets_open,
    first_session_closing_after,
    market_day_status,
    market_session,
)


def test_nasdaq_stockholm_and_helsinki_are_closed_on_ascension_day_2026():
    statuses = [
        market_day_status(date(2026, 5, 14), "stockholm"),
        market_day_status(date(2026, 5, 14), "helsinki"),
    ]

    assert [status.is_open for status in statuses] == [False, False]
    assert {status.reason for status in statuses} == {"Ascension Day"}
    assert not are_markets_open(date(2026, 5, 14), ("stockholm", "helsinki"))


def test_nasdaq_stockholm_and_helsinki_are_open_on_regular_weekday():
    statuses = [
        market_day_status(date(2026, 5, 15), "stockholm"),
        market_day_status(date(2026, 5, 15), "helsinki"),
    ]

    assert [status.is_open for status in statuses] == [True, True]
    assert {status.reason for status in statuses} == {None}
    assert are_markets_open(date(2026, 5, 15), ("stockholm", "helsinki"))


def test_market_calendar_handles_country_specific_holidays():
    stockholm = market_day_status(date(2025, 6, 6), "stockholm")
    helsinki = market_day_status(date(2025, 6, 6), "helsinki")

    assert stockholm.is_open is False
    assert stockholm.reason == "Swedish National Day"
    assert helsinki.is_open

    stockholm_on_finnish_independence = market_day_status(
        date(2027, 12, 6), "stockholm"
    )
    helsinki_on_finnish_independence = market_day_status(
        date(2027, 12, 6), "helsinki"
    )
    assert stockholm_on_finnish_independence.is_open
    assert helsinki_on_finnish_independence.is_open is False
    assert helsinki_on_finnish_independence.reason == "Finnish Independence Day"


def test_first_entry_can_use_same_day_close_only_when_strictly_after_decision():
    before_close = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
    at_close = datetime(2026, 8, 10, 15, 30, tzinfo=timezone.utc)

    assert first_session_closing_after(before_close, "stockholm").day == date(2026, 8, 10)
    assert first_session_closing_after(at_close, "stockholm").day == date(2026, 8, 11)


def test_weekend_decision_uses_next_open_market_session():
    decision = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)

    assert first_session_closing_after(decision, "helsinki").day == date(2026, 8, 10)


def test_exchange_holiday_is_not_counted_as_a_session():
    entry = date(2026, 5, 13)

    assert advance_market_sessions(entry, 1, "stockholm").day == date(2026, 5, 15)
    assert advance_market_sessions(entry, 1, "helsinki").day == date(2026, 5, 15)


def test_stockholm_and_helsinki_use_market_local_close_times():
    stockholm = market_session(date(2026, 1, 7), "stockholm")
    helsinki = market_session(date(2026, 1, 7), "helsinki")

    assert stockholm is not None and stockholm.closes_at.hour == 17
    assert stockholm.closes_at.utcoffset().total_seconds() == 3600
    assert helsinki is not None and helsinki.closes_at.hour == 18
    assert helsinki.closes_at.utcoffset().total_seconds() == 7200
    assert stockholm.closes_at.astimezone(timezone.utc) == helsinki.closes_at.astimezone(timezone.utc)


def test_stockholm_recurring_half_day_changes_entry_boundary():
    session = market_session(date(2026, 4, 2), "stockholm")

    assert session is not None
    assert session.is_half_day is True
    assert session.closes_at.hour == 13
    decision_after_half_day = datetime(2026, 4, 2, 11, 30, tzinfo=timezone.utc)
    assert first_session_closing_after(decision_after_half_day, "stockholm").day == date(2026, 4, 7)


def test_horizon_counts_valid_sessions_instead_of_calendar_days():
    entry = date(2026, 4, 30)

    assert advance_market_sessions(entry, 2, "helsinki").day == date(2026, 5, 5)
