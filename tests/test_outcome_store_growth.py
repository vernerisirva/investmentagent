"""Repeated budget deferrals add no outcome revisions and change no analysis value."""
from datetime import datetime, timedelta, timezone
import socket

import pytest

from investmentagent import evaluation_outcomes
from investmentagent.benchmark_analysis import build_benchmark_analysis
from investmentagent.evaluation import save_evaluation_snapshot
from investmentagent.evaluation_outcomes import (
    discover_outcome_sets, outcome_store_path, refresh_outcome_store,
)
from investmentagent.market_price_cache import FileHistoricalPriceCache
from investmentagent.market_prices import FixtureHistoricalPriceProvider
from investmentagent.outcome_status import BUDGET_DEFERRED_DETAIL
from test_evaluation_outcomes import _observations_for_snapshots, _snapshot


UTC = timezone.utc
DAYS = [datetime(2026, 8, 11, 18, tzinfo=UTC) + timedelta(days=offset) for offset in range(4)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("outcome store tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def refresh(root, snapshot, at, budget, prices=None):
    save_evaluation_snapshot(root / "evaluations", snapshot)
    return refresh_outcome_store(
        root / "evaluations", root / "outcomes", FixtureHistoricalPriceProvider(prices or {}),
        retrieved_at=at, price_cache=FileHistoricalPriceCache(root / "prices.json"),
        max_price_api_calls=budget,
    )


def store(root, snapshot):
    return discover_outcome_sets(root / "outcomes")[0], outcome_store_path(root / "outcomes", snapshot)


def test_repeated_budget_deferral_leaves_the_store_byte_identical(tmp_path):
    snapshot = _snapshot(3, strategy="trading")
    refresh(tmp_path, snapshot, DAYS[0], budget=0)
    first, path = store(tmp_path, snapshot)
    before = path.read_bytes()
    assert {o.detail for o in first.outcomes if o.horizon_sessions == 1} == {BUDGET_DEFERRED_DETAIL}
    for at in DAYS[1:]:
        summary = refresh(tmp_path, snapshot, at, budget=0)
        assert summary.work_deferred_by_budget == 3
        assert summary.lifecycle["mature_budget_deferred"] == 3
    assert path.read_bytes() == before


def scenario(root, snapshot):
    prices = _observations_for_snapshots((snapshot,), retrieved_at=DAYS[2])
    failing = snapshot.rows[0].company_id
    without_failing = {key: value for key, value in prices.items() if key != failing}
    summaries = [
        refresh(root, snapshot, DAYS[0], budget=0),
        refresh(root, snapshot, DAYS[1], budget=0),
        # Every security is fetched; one has no prices and fails.
        refresh(root, snapshot, DAYS[2], budget=20, prices=without_failing),
        # The failed security is deferred, so its status returns to pending.
        refresh(root, snapshot, DAYS[3], budget=0, prices=without_failing),
    ]
    return summaries, discover_outcome_sets(root / "outcomes")


def comparable(analysis):
    # Only the digest of selected revision identities may differ; it names records, not values.
    methodology = {k: v for k, v in analysis["methodology"].items() if k != "selected_outcomes_hash"}
    return {**analysis, "methodology": methodology}


def test_deferral_suppression_changes_no_status_coverage_or_return(tmp_path, monkeypatch):
    snapshot = _snapshot(6, strategy="trading", countries=("SE", "FI"))
    new_summaries, new_stores = scenario(tmp_path / "new", snapshot)
    monkeypatch.setattr(evaluation_outcomes, "_unchanged_by_deferral", lambda outcome: outcome.status == "priced")
    old_summaries, old_stores = scenario(tmp_path / "old", snapshot)
    assert [s.lifecycle for s in new_summaries] == [s.lifecycle for s in old_summaries]
    assert len(new_stores[0].revisions) < len(old_stores[0].revisions)
    current = {o.company_id: o.status for o in new_stores[0].outcomes if o.horizon_sessions == 1}
    assert current[snapshot.rows[0].company_id] == "coherent_history_pending"
    assert sum(status == "priced" for status in current.values()) == 5
    cutoffs = [DAYS[0] - timedelta(hours=1), *DAYS, *(day + timedelta(hours=6) for day in DAYS)]
    for cutoff in cutoffs:
        new, old = (build_benchmark_analysis([snapshot], stores, generated_at=cutoff, data_cutoff=cutoff)
                    for stores in (new_stores, old_stores))
        assert comparable(new) == comparable(old), cutoff
