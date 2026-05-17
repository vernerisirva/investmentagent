from datetime import date

from investmentagent.market_calendar import (
    are_markets_open,
    market_day_status,
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
