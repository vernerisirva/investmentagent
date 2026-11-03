"""Price-fetch scheduling: failures back off, ties are identity-neutral, the budget is never exceeded."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import socket

import pytest

from investmentagent.evaluation import save_evaluation_snapshot
from investmentagent.evaluation_outcomes import (
    DEFAULT_STRATEGY_HORIZONS, RETRY_BACKOFF_CAP_DAYS, _retry_backoff_until, fetch_tie_break, refresh_outcome_store,
)
from investmentagent.market_calendar import (
    advance_market_sessions, first_session_closing_after, market_for_country,
)
from investmentagent.market_price_cache import FileHistoricalPriceCache
from investmentagent.market_prices import (
    EODHD_CIRCUIT_DETAIL_PREFIX, EODHD_MISSING_KEY_DETAIL, EodhdHistoricalPriceProvider,
    FixtureHistoricalPriceProvider,
)
from test_evaluation_outcomes import _observations_for_snapshots, _snapshot


UTC = timezone.utc
# Decisions are on 2026-08-10, so 1-session outcomes mature on 2026-08-11 and 5-session ones on 2026-08-17.
FIRST = datetime(2026, 8, 11, 18, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("fetch scheduling tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def refresh(root, snapshot, at, provider, *, budget=20, dry_run=False):
    save_evaluation_snapshot(root / "evaluations", snapshot)
    return refresh_outcome_store(
        root / "evaluations", root / "outcomes", provider, retrieved_at=at,
        price_cache=FileHistoricalPriceCache(root / "prices.json"), max_price_api_calls=budget, dry_run=dry_run,
    )


def requested(provider):
    return [company_id for company_id, *_ in provider.requests]


def day(offset, hour=18):
    return FIRST.replace(hour=hour) + timedelta(days=offset)


def test_backoff_doubles_each_unproductive_fetch_day_up_to_the_cap():
    last = date(2026, 8, 11)
    at = lambda days: datetime.combine(last + timedelta(days=days), datetime.min.time(), UTC)
    assert _retry_backoff_until(None, at(0)) is None
    assert _retry_backoff_until((0, last), at(0)) is None
    assert _retry_backoff_until((1, last), at(0)) == last + timedelta(days=1)
    assert _retry_backoff_until((1, last), at(1)) is None
    assert _retry_backoff_until((3, last), at(3)) == last + timedelta(days=4)
    assert _retry_backoff_until((3, last), at(4)) is None
    for failures in (6, 7, 40):
        assert _retry_backoff_until((failures, last), at(31)) == last + timedelta(days=RETRY_BACKOFF_CAP_DAYS)
        assert _retry_backoff_until((failures, last), at(RETRY_BACKOFF_CAP_DAYS)) is None


def test_a_failing_security_backs_off_while_its_records_stay_budget_deferred(tmp_path):
    snapshot = _snapshot(3, strategy="trading")
    failing = snapshot.rows[0].company_id
    prices = {k: v for k, v in _observations_for_snapshots((snapshot,), retrieved_at=FIRST).items() if k != failing}
    calls, plans = [], []
    for offset in range(5):
        provider = FixtureHistoricalPriceProvider(prices, provider_errors={failing: "HTTP Error 404: Not Found"})
        summary = refresh(tmp_path, snapshot, day(offset), provider)
        calls.append(requested(provider))
        plans.append({item.company_id: item for item in summary.fetch_plan})
    # Fails on day 0 and 1 (two days), waits 2 days, fails on day 3, then waits 4 days.
    assert calls[0] == sorted(calls[0], key=lambda c: fetch_tie_break(c, "stockholm")) and failing in calls[0]
    assert len(calls[0]) == 3
    assert [failing in day_calls for day_calls in calls] == [True, True, False, True, False]
    assert plans[2][failing].retry_backoff_until == date(2026, 8, 14)
    assert plans[4][failing].retry_backoff_until == date(2026, 8, 18)
    assert plans[2][failing].deferred_by_budget
    assert summary.work_deferred_by_retry_backoff == 1
    assert summary.lifecycle["mature_budget_deferred"] == 1
    assert summary.lifecycle["mature_priced"] == 2


def test_a_priced_fetch_ends_the_backoff(tmp_path):
    snapshot = _snapshot(3, strategy="trading")
    failing = snapshot.rows[0].company_id
    prices = _observations_for_snapshots((snapshot,), retrieved_at=FIRST)
    others = {k: v for k, v in prices.items() if k != failing}
    for offset in (0, 1):
        refresh(tmp_path, snapshot, day(offset), FixtureHistoricalPriceProvider(
            others, provider_errors={failing: "HTTP Error 404: Not Found"}))
    recovered = FixtureHistoricalPriceProvider(prices)
    refresh(tmp_path, snapshot, day(3), recovered)
    assert requested(recovered) == [failing]
    later = FixtureHistoricalPriceProvider(_observations_for_snapshots((snapshot,), retrieved_at=day(6)))
    summary = refresh(tmp_path, snapshot, day(6), later)
    assert failing in requested(later) and len(requested(later)) == 3
    assert all(item.retry_backoff_until is None for item in summary.fetch_plan)


@pytest.mark.parametrize("detail,backs_off", [
    ("HTTP Error 404: Not Found", True),
    (EODHD_MISSING_KEY_DETAIL, False),
    (f"{EODHD_CIRCUIT_DETAIL_PREFIX} after three consecutive provider errors; last error: x", False),
])
def test_only_requests_that_were_sent_start_a_backoff(tmp_path, detail, backs_off):
    snapshot = _snapshot(1, strategy="trading")
    company = snapshot.rows[0].company_id
    refresh(tmp_path, snapshot, day(0), FixtureHistoricalPriceProvider({}, provider_errors={company: detail}))
    again = FixtureHistoricalPriceProvider({}, provider_errors={company: detail})
    summary = refresh(tmp_path, snapshot, day(0, hour=21), again)
    assert (requested(again) == []) is backs_off
    assert (summary.fetch_plan[0].retry_backoff_until is not None) is backs_off


def test_an_open_error_circuit_cannot_use_more_than_the_budget(tmp_path):
    snapshot = _snapshot(10, strategy="trading")

    def unavailable(url):
        raise OSError("HTTP Error 503: Service Unavailable")

    provider = EodhdHistoricalPriceProvider("synthetic-key", fetcher=unavailable)
    summary = refresh(tmp_path, snapshot, day(0), provider, budget=5)
    assert provider.api_call_count == summary.provider_calls_executed == 3
    assert sum(not item.deferred_by_budget for item in summary.fetch_plan) == 5
    assert summary.work_deferred_by_budget == 5 and summary.provider_errors == 5


def _payload(snapshot):
    row = snapshot.rows[0]
    market = market_for_country(row.country)
    entry = first_session_closing_after(snapshot.decision_at, market).day
    sessions = [entry, *(advance_market_sessions(entry, d.sessions, market).day
                         for d in DEFAULT_STRATEGY_HORIZONS[snapshot.strategy])]
    return json.dumps([{"date": s.isoformat(), "close": 100.0 + i, "adjusted_close": 100.0 + i}
                       for i, s in enumerate(sessions)])


@pytest.mark.parametrize("first_candidate_has_data,executed,deferred", [(True, 3, 0), (False, 3, 1)])
def test_unused_multi_candidate_estimates_go_to_later_tasks(tmp_path, first_candidate_has_data, executed, deferred):
    base = _snapshot(3, strategy="trading")
    first = min(base.rows, key=lambda row: fetch_tie_break(row.company_id, "stockholm"))
    snapshot = replace(base, rows=tuple(replace(row, ticker="AB C") if row is first else row for row in base.rows))
    payload = _payload(snapshot)
    calls = []

    def fetch(url):
        calls.append(url)
        return payload if first_candidate_has_data or "AB-C.ST" not in url else "[]"

    summary = refresh(tmp_path, snapshot, day(0), EodhdHistoricalPriceProvider("synthetic-key", fetcher=fetch), budget=3)
    assert summary.fetch_plan[0].company_id == first.company_id and summary.fetch_plan[0].estimated_api_calls == 2
    assert summary.provider_calls_executed == len(calls) == executed <= 3
    assert summary.work_deferred_by_budget == deferred


def test_equal_priority_tasks_are_not_ordered_by_country_or_isin(tmp_path):
    snapshot = _snapshot(20, strategy="trading", countries=("FI", "SE"))
    summary = refresh(tmp_path, snapshot, day(0), FixtureHistoricalPriceProvider({}), budget=10, dry_run=True)
    order = [item.company_id for item in summary.fetch_plan]
    assert order == sorted(order, key=lambda c: fetch_tie_break(c, market_for_country(c[5:7])))
    assert order != sorted(order)
    assert {company[5:7] for company in order[:10]} == {"FI", "SE"}
    assert summary.provider_calls_executed == 0 and summary.work_deferred_by_budget == 10
