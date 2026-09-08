"""Maturity depends on fixed sessions and a cutoff, never on retrieval progress."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import socket

import pytest
from typer.testing import CliRunner

from investmentagent.cli import app
from investmentagent.evaluation import save_evaluation_snapshot, serialize_evaluation_snapshot
from investmentagent.evaluation_analysis import (
    ANALYSIS_SCHEMA_VERSION, _aggregate_run_metrics, build_performance_v2_analysis,
    render_performance_v2_markdown, save_analysis_json, save_analysis_markdown,
)
from investmentagent.evaluation_outcomes import (
    HorizonDefinition, _initial_outcome, discover_outcome_sets, load_outcome_set,
    refresh_evaluation_outcomes, refresh_outcome_store, save_outcome_set, serialize_outcome_set,
)
from investmentagent.experiments import serialize_experiment_snapshot
from investmentagent.market_calendar import market_session
from investmentagent.market_price_cache import FileHistoricalPriceCache
from investmentagent.market_prices import FixtureHistoricalPriceProvider, EodhdHistoricalPriceProvider
from investmentagent.outcome_status import (
    OUTCOME_STATUS_METHODOLOGY, analysis_view, fixed_sessions, is_mature,
    lifecycle_counts, status_as_of,
)
from investmentagent.price_histories import COHERENT_RETURN_METHOD, LEGACY_RETURN_METHOD
from test_coherent_price_histories import _legacy, _prices, _run
from test_evaluation_outcomes import ONE_SESSION, _snapshot, _observation, _observations_for_snapshots
from test_fixed_decision_membership import production_case


UTC = timezone.utc
EARLY = datetime(2026, 8, 10, 18, tzinfo=UTC)
DUE = datetime(2026, 8, 11, 18, tzinfo=UTC)
LATER = datetime(2026, 8, 12, 18, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("maturity validation must not use the network")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def stale(snapshot):
    provider = FixtureHistoricalPriceProvider({})
    store = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=EARLY, horizons=ONE_SESSION)
    assert not provider.requests
    assert all(o.status == "not_due" for o in store.outcomes)
    return store


def analyze(snapshot, store=None, at=DUE, experiment=None):
    return build_performance_v2_analysis([snapshot], [store] if store else [], generated_at=LATER,
        data_cutoff=at, experiment_snapshots=[experiment] if experiment else None)


@pytest.mark.parametrize("offset,expected", [(-1, "not_due"), (0, "coherent_history_pending"), (1, "coherent_history_pending")])
@pytest.mark.parametrize("country", ["SE", "FI"])
def test_maturity_changes_exactly_at_target_close(country, offset, expected):
    snapshot = _snapshot(1, countries=(country,))
    outcome = _initial_outcome(snapshot, snapshot.rows[0], ONE_SESSION[0], "fixture")
    target = market_session(outcome.target_exit_session, outcome.market)
    cutoff = target.closes_at + timedelta(microseconds=offset)
    assert status_as_of(outcome, cutoff) == expected
    assert is_mature(outcome, cutoff) == (offset >= 0)


def test_stale_not_due_becomes_mature_pending_without_fabricated_return():
    snapshot = _snapshot(100)
    store = stale(snapshot)
    before = serialize_outcome_set(store)
    early, mature = analyze(snapshot, store, EARLY), analyze(snapshot, store)
    assert early["lifecycle"]["not_mature"] == 100
    assert mature["lifecycle"]["mature_pending"] == 100
    run = mature["run_metrics"][0]
    assert run["is_due"] and not run["analysis_eligible"]
    assert run["status_counts"] == {"coherent_history_pending": 100}
    assert run["valid_company_count"] == 0 and run["outcome_coverage_pct"] == 0
    assert run["universe_cohort"]["decision_time_member_count"] == 100
    assert run["universe_equal_weight_return_pct"] is None
    assert mature["groups"][0]["partial_run_count"] == 1
    assert serialize_outcome_set(store) == before


def test_evaluations_with_no_y_are_counted_using_strategy_horizons():
    snapshot = _snapshot(5, strategy="trading")
    result = analyze(snapshot)
    assert result["lifecycle"]["evaluation_runs"] == 1
    assert result["lifecycle"]["evaluations_with_selected_outcomes"] == 0
    assert result["lifecycle"]["total"] == 20
    assert result["lifecycle"]["mature_pending"] == 5
    assert result["lifecycle"]["not_mature"] == 15
    assert [run["horizon"]["sessions"] for run in result["run_metrics"]] == [1, 5, 20, 60]
    assert not any(run["valid_company_count"] for run in result["run_metrics"])


@pytest.mark.parametrize("dry_run", [True, False])
def test_budget_zero_has_explicit_mature_pending_and_no_requests(tmp_path, dry_run):
    snapshot = _snapshot(3, strategy="trading")
    summary, provider, _ = _run(tmp_path, snapshot, {}, at=DUE, budget=0, dry_run=dry_run)
    assert provider.api_call_count == summary.provider_calls_executed == 0
    assert summary.work_deferred_by_budget == 3
    assert summary.lifecycle["mature_budget_deferred"] == 3
    assert summary.lifecycle["not_mature"] == 9
    assert summary.not_due == 9 and summary.unresolved == 3
    if dry_run:
        assert not (tmp_path / "outcomes").exists()
    else:
        records = discover_outcome_sets(tmp_path / "outcomes")[0].outcomes
        assert [o.status for o in records if o.horizon_sessions == 1] == ["coherent_history_pending"] * 3
        assert all(o.raw_forward_return_pct is None for o in records)


def test_preview_planned_but_unfetched_work_is_awaiting_not_due(tmp_path):
    summary, provider, _ = _run(tmp_path, _snapshot(2, strategy="trading"), {}, at=DUE, budget=20, dry_run=True)
    assert summary.provider_calls_planned == 2
    assert summary.provider_calls_executed == 0 and not provider.requests
    assert summary.lifecycle["mature_awaiting_retrieval"] == 2
    assert summary.lifecycle["mature_budget_deferred"] == 0


def test_historical_preview_summary_does_not_count_later_prices(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, _prices(snapshot, 100, 110, LATER), at=LATER)
    before = {str(path): path.read_bytes() for path in (tmp_path / "outcomes").rglob("*.json")}
    summary, provider, _ = _run(tmp_path, snapshot, {}, at=DUE, dry_run=True)
    assert summary.priced == summary.lifecycle["mature_priced"] == 0
    assert summary.unresolved == summary.lifecycle["mature_pending"] == 1
    assert not provider.requests
    assert {str(path): path.read_bytes() for path in (tmp_path / "outcomes").rglob("*.json")} == before


@pytest.mark.parametrize("missing,status", [("entry", "missing_entry"), ("exit", "missing_exit"), (None, "priced")])
def test_mature_endpoint_availability_is_separate(missing, status):
    snapshot = _snapshot(1, strategy="trading")
    prices = _prices(snapshot, None if missing == "entry" else 100, None if missing == "exit" else 110, DUE)
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(prices), retrieved_at=DUE, horizons=ONE_SESSION)
    assert store.outcomes[0].status == status
    counts = lifecycle_counts(store.outcomes, DUE)
    assert counts["mature"] == 1 and counts["not_mature"] == 0
    assert counts["mature_priced"] == int(missing is None)
    assert counts["mature_unavailable"] == int(missing is not None)


@pytest.mark.parametrize("kind,status", [("unresolved", "symbol_unresolved"), ("unsupported", "corporate_action_unsupported"), ("error", "provider_error")])
def test_mature_failed_and_unavailable_states(kind, status):
    snapshot = _snapshot(1)
    key = snapshot.rows[0].company_id
    provider = FixtureHistoricalPriceProvider({}, **({"unresolved": [key]} if kind == "unresolved" else
        {"unsupported_adjustments": [key]} if kind == "unsupported" else {"provider_errors": {key: "synthetic failure"}}))
    store = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=DUE, horizons=ONE_SESSION)
    assert store.outcomes[0].status == status
    counts = lifecycle_counts(store.outcomes, DUE)
    assert counts["mature_failed"] == int(kind == "error")
    assert counts["mature_unavailable"] == int(kind != "error")


def test_later_price_retrieval_preserves_earlier_maturity_and_missingness():
    snapshot = _snapshot(1, strategy="trading")
    initial = stale(snapshot)
    later = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100, 110, LATER)),
                                       retrieved_at=LATER, existing=initial, horizons=ONE_SESSION)
    early = analyze(snapshot, later, EARLY)
    due = analyze(snapshot, later, DUE)
    latest = analyze(snapshot, later, LATER)
    assert early["lifecycle"]["not_mature"] == 1
    assert due["lifecycle"]["mature_pending"] == 1 and due["lifecycle"]["mature_priced"] == 0
    assert latest["lifecycle"]["mature_priced"] == 1
    assert initial.outcomes[0] in later.revisions
    assert due["run_metrics"][0]["universe_equal_weight_return_pct"] is None


def test_future_revision_does_not_leak_into_historical_cutoff():
    snapshot = _snapshot(1, strategy="trading")
    first = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100, 110, DUE)),
                                       retrieved_at=DUE, horizons=ONE_SESSION)
    revised = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 50, 60, LATER)),
        retrieved_at=LATER, horizons=ONE_SESSION, existing=first, reprice=True)
    before = analyze(snapshot, first, DUE)
    reproduced = analyze(snapshot, revised, DUE)
    assert before == reproduced
    assert reproduced["run_metrics"][0]["universe_equal_weight_return_pct"] == pytest.approx(10)
    assert analyze(snapshot, revised, LATER)["run_metrics"][0]["universe_equal_weight_return_pct"] == pytest.approx(20)


def test_report_clock_is_default_cutoff_not_all_future_evidence():
    snapshot = _snapshot(1, strategy="trading")
    later = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100, 110, LATER)),
        retrieved_at=LATER, horizons=ONE_SESSION)
    result = build_performance_v2_analysis([snapshot], [later], generated_at=DUE)
    assert result["lifecycle"]["mature_priced"] == 0
    assert result["lifecycle"]["mature_pending"] == 1


def test_future_evaluation_is_not_in_historical_population():
    snapshot = _snapshot(2)
    result = analyze(snapshot, at=snapshot.decision_at - timedelta(seconds=1))
    assert result["lifecycle"]["total"] == result["lifecycle"]["evaluation_runs"] == 0


def test_future_sidecar_does_not_enter_earlier_analysis():
    _, snapshot, experiment = production_case()
    result = analyze(snapshot, at=snapshot.decision_at - timedelta(seconds=1), experiment=experiment)
    assert result["lifecycle"]["evaluation_runs"] == 0
    assert result["challenger_analysis"]["recorded_sidecar_count"] == 0
    assert result["challenger_analysis"]["run_metrics"] == []


def test_challenger_without_y_keeps_mature_missing_members():
    _, snapshot, experiment = production_case(count=100)
    cutoff = datetime(2026, 9, 8, 18, tzinfo=UTC)
    result = analyze(snapshot, at=cutoff, experiment=experiment)
    run = result["challenger_analysis"]["run_metrics"][0]
    assert run["is_due"] and run["lifecycle"]["mature_pending"] == 100
    assert run["paired_company_count"] == 0 and not run["analysis_eligible"]
    assert run["universe_cohort"]["decision_time_member_count"] == 100


def test_budget_pending_revision_then_priced_retains_earlier_pipeline_state(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, {}, at=DUE, budget=0)
    pending = discover_outcome_sets(tmp_path / "outcomes")[0]
    _run(tmp_path, snapshot, _prices(snapshot, 100, 110, LATER), at=LATER)
    priced = discover_outcome_sets(tmp_path / "outcomes")[0]
    early = analyze(snapshot, priced, DUE)
    assert early["lifecycle"]["mature_budget_deferred"] == 1
    assert early["lifecycle"]["mature_priced"] == 0
    assert pending.outcomes[0] in priced.revisions


def test_nested_challenger_status_version_is_enforced(tmp_path):
    _, snapshot, experiment = production_case()
    result = analyze(snapshot, stale(snapshot), experiment=experiment)
    result["challenger_analysis"].pop("outcome_status_methodology")
    with pytest.raises(ValueError, match="methodology"):
        save_analysis_json(tmp_path / "analysis.json", result)


@pytest.mark.parametrize("decision,market,sessions,entry,exit", [
    ("2026-08-14T08:00:00+00:00", "stockholm", 1, "2026-08-14", "2026-08-17"),
    ("2025-06-05T08:00:00+00:00", "stockholm", 1, "2025-06-05", "2025-06-09"),
    ("2024-12-05T08:00:00+00:00", "helsinki", 1, "2024-12-05", "2024-12-09"),
    ("2026-08-14T08:00:00+00:00", "helsinki", 5, "2026-08-14", "2026-08-21"),
    ("2026-04-01T08:00:00+00:00", "stockholm", 1, "2026-04-01", "2026-04-02"),
    ("2026-04-02T11:00:00+00:00", "stockholm", 1, "2026-04-07", "2026-04-08"),
])
def test_established_session_rules(decision, market, sessions, entry, exit):
    actual_entry, actual_exit = fixed_sessions(datetime.fromisoformat(decision), market, sessions)
    assert actual_entry.day == date.fromisoformat(entry)
    assert actual_exit.day == date.fromisoformat(exit)
    if exit == "2026-04-02":
        assert actual_exit.is_half_day and actual_exit.closes_at.hour == 13


def test_planner_future_skip_mature_due_and_deterministic_budget(tmp_path):
    snapshot = _snapshot(3, strategy="trading")
    early, provider, cache = _run(tmp_path, snapshot, {}, at=EARLY)
    assert early.securities_requiring_prices == 0 and not provider.requests
    due, provider, _ = _run(tmp_path, snapshot, {}, at=DUE, budget=1, cache=cache)
    assert due.provider_calls_executed == 1 and due.work_deferred_by_budget == 2
    assert [task.company_id for task in due.fetch_plan] == sorted(row.company_id for row in snapshot.rows)
    assert due.lifecycle["mature_budget_deferred"] == 2


def test_alternate_symbol_costs_remain_budgeted(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    save_evaluation_snapshot(tmp_path / "x", snapshot)
    calls = []
    provider = EodhdHistoricalPriceProvider("synthetic-key", fetcher=lambda url: calls.append(url) or "[]")
    # A space in a ticker gives the existing provider multiple symbol attempts.
    row = replace(snapshot.rows[0], ticker="TEST B")
    snapshot = replace(snapshot, rows=(row,))
    save_evaluation_snapshot(tmp_path / "altered-x", snapshot)
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    first = refresh_outcome_store(tmp_path / "altered-x", tmp_path / "y", provider, retrieved_at=DUE,
                                 price_cache=cache, max_price_api_calls=1)
    assert first.fetch_plan[0].estimated_api_calls == 2
    assert first.provider_calls_executed == 0 and first.lifecycle["mature_budget_deferred"] == 1
    second = refresh_outcome_store(tmp_path / "altered-x", tmp_path / "y", provider, retrieved_at=LATER,
                                  price_cache=cache, max_price_api_calls=2)
    assert second.provider_calls_executed == len(calls) == 2


def test_completed_and_cached_coherent_histories_are_reused(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    first, _, cache = _run(tmp_path, snapshot, _prices(snapshot, 100, 110, DUE), at=DUE)
    assert first.provider_calls_executed == 1
    repeat, provider, _ = _run(tmp_path, snapshot, {}, at=DUE, budget=0, cache=cache)
    assert not provider.requests and repeat.priced == 1
    reused, provider, _ = _run(tmp_path, snapshot, {}, at=DUE, budget=0, cache=cache, output="reused")
    assert not provider.requests and reused.priced == 1 and reused.cache_hits == 2


@pytest.mark.parametrize("priced_count,eligible", [(69, False), (70, True)])
def test_original_coverage_threshold_and_membership_unchanged(priced_count, eligible):
    _, snapshot, experiment = production_case(count=100)
    before = serialize_evaluation_snapshot(snapshot), serialize_experiment_snapshot(experiment)
    initial = stale(snapshot)
    histories = {row.company_id: [_observation(row, date(2026, 8, 10), 100, retrieved_at=DUE),
                                  _observation(row, date(2026, 8, 11), 110, retrieved_at=DUE)]
                 for row in snapshot.rows[:priced_count]}
    priced = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(histories),
        retrieved_at=DUE, existing=initial, horizons=ONE_SESSION)
    earlier = analyze(snapshot, initial, DUE, experiment)
    later = analyze(snapshot, priced, DUE, experiment)
    run = later["run_metrics"][0]
    assert run["analysis_eligible"] == eligible
    assert run["original_universe_size"] == 100 and run["outcome_coverage_pct"] == priced_count
    assert run["universe_cohort"]["member_ids"] == earlier["run_metrics"][0]["universe_cohort"]["member_ids"]
    paired = later["challenger_analysis"]["run_metrics"][0]
    assert paired["paired_company_count"] == priced_count and paired["analysis_eligible"] == eligible
    assert later["methodology"]["selected_outcomes_hash"] == later["challenger_analysis"]["methodology"]["selected_outcomes_hash"]
    assert before == (serialize_evaluation_snapshot(snapshot), serialize_experiment_snapshot(experiment))


@pytest.mark.parametrize("count,eligible", [(49, False), (50, True)])
def test_overall_minimum_sample_unchanged(count, eligible):
    snapshot = _snapshot(count)
    histories = {row.company_id: [_observation(row, date(2026, 8, 10), 100, retrieved_at=DUE),
                                  _observation(row, date(2026, 8, 11), 110, retrieved_at=DUE)] for row in snapshot.rows}
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(histories), retrieved_at=DUE, horizons=ONE_SESSION)
    assert analyze(snapshot, store)["run_metrics"][0]["analysis_eligible"] == eligible


@pytest.mark.parametrize("country_size,priced,eligible", [(20, 19, False), (20, 20, True), (30, 20, False), (30, 21, True)])
def test_country_minimums_unchanged(country_size, priced, eligible):
    snapshot = _snapshot(country_size * 2, countries=("SE", "FI"))
    rows = [row for row in snapshot.rows if row.country == "FI"][:priced]
    histories = {row.company_id: [_observation(row, date(2026, 8, 10), 100, retrieved_at=DUE),
                                  _observation(row, date(2026, 8, 11), 110, retrieved_at=DUE)] for row in rows}
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(histories), retrieved_at=DUE, horizons=ONE_SESSION)
    metric = next(item for item in analyze(snapshot, store)["run_metrics"][0]["country_metrics"] if item["country"] == "FI")
    assert metric["analysis_eligible"] == eligible
    assert metric["decision_time_member_count"] == country_size


def test_old_outcome_files_roundtrip_without_relabel_or_rewrite(tmp_path):
    snapshot = _snapshot(2)
    for index, store in enumerate((stale(snapshot), _legacy(stale(snapshot)))):
        path = save_outcome_set(tmp_path / f"{index}.json", store)
        before = path.read_bytes()
        restored = load_outcome_set(path)
        result = analyze(snapshot, restored)
        assert result["lifecycle"]["mature_pending"] == 2
        assert path.read_bytes() == before
        assert serialize_outcome_set(restored) == serialize_outcome_set(store)


@pytest.mark.parametrize("kind", ["json", "markdown", "aggregate"])
def test_old_status_semantics_cannot_silently_mix_or_overwrite(tmp_path, kind):
    snapshot = _snapshot(2)
    result = analyze(snapshot, stale(snapshot))
    assert result["schema_version"] == ANALYSIS_SCHEMA_VERSION == 3
    assert result["outcome_status_methodology"] == OUTCOME_STATUS_METHODOLOGY
    if kind == "aggregate":
        old = deepcopy(result["run_metrics"][0])
        old.pop("outcome_status_methodology")
        with pytest.raises(ValueError, match="methodology"):
            _aggregate_run_metrics([old])
    else:
        path = tmp_path / kind
        old = deepcopy(result)
        old["schema_version"] = 2
        old.pop("outcome_status_methodology")
        path.write_text(json.dumps(old) if kind == "json" else "Analysis methodology: fixed-decision-membership-v1\n")
        before = path.read_bytes()
        with pytest.raises(ValueError, match="historical|methodology"):
            (save_analysis_json if kind == "json" else save_analysis_markdown)(path, result)
        assert path.read_bytes() == before


def test_markdown_exposes_maturity_and_pipeline_distinction():
    snapshot = _snapshot(2)
    result = analyze(snapshot, stale(snapshot))
    markdown = render_performance_v2_markdown(result)
    assert "Outcome Lifecycle" in markdown and "Pending retrieval" in markdown
    assert "Maturity does not imply price availability" in markdown


def test_naive_cutoff_and_corrupt_fixed_sessions_fail_closed():
    snapshot = _snapshot(1)
    outcome = stale(snapshot).outcomes[0]
    with pytest.raises(ValueError, match="timezone"):
        status_as_of(outcome, DUE.replace(tzinfo=None))
    with pytest.raises(ValueError, match="decision-time"):
        status_as_of(replace(outcome, target_exit_session=date(2026, 8, 12)), DUE)


def test_direct_analysis_view_cannot_show_future_return():
    snapshot = _snapshot(1, strategy="trading")
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100, 110, LATER)),
        retrieved_at=LATER, horizons=ONE_SESSION)
    view = analysis_view(store.outcomes[0], DUE)
    assert view.status == "coherent_history_pending" and view.raw_forward_return_pct is None
    assert view.history_evidence is None and view.provider_symbol is None


def test_legacy_unavailable_record_cannot_expose_an_old_return_in_metrics():
    snapshot = _snapshot(1, strategy="trading")
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100, 110, DUE)),
        retrieved_at=DUE, horizons=ONE_SESSION)
    legacy = _legacy(store, unsupported=True)
    before = serialize_outcome_set(legacy)
    run = analyze(snapshot, legacy)["run_metrics"][0]
    assert run["valid_company_count"] == 0
    assert run["company_benchmarks"][0]["return_pct"] is None
    assert serialize_outcome_set(legacy) == before


def test_half_day_mixed_markets_keep_original_coverage_denominator():
    decision = datetime(2026, 4, 1, 8, tzinfo=UTC)
    cutoff = datetime(2026, 4, 2, 11, tzinfo=UTC)
    snapshot = _snapshot(100, countries=("SE", "FI"), decision_at=decision)
    histories = {row.company_id: [_observation(row, date(2026, 4, 1), 100, retrieved_at=cutoff),
                                  _observation(row, date(2026, 4, 2), 110, retrieved_at=cutoff)]
                 for row in snapshot.rows if row.country == "SE"}
    provider = FixtureHistoricalPriceProvider(histories)
    store = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=cutoff, horizons=ONE_SESSION)
    result = analyze(snapshot, store, cutoff)
    assert provider.api_call_count == 50
    assert result["lifecycle"]["mature_priced"] == result["lifecycle"]["not_mature"] == 50
    run = result["run_metrics"][0]
    assert run["outcome_coverage_pct"] == 50 and run["original_universe_size"] == 100
    assert not run["analysis_eligible"]


def test_offline_cli_exposes_correct_preview_and_analysis(tmp_path, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    snapshot = _snapshot(2, strategy="trading")
    save_evaluation_snapshot(tmp_path / "x", snapshot)
    # EODHD dry-run works without credentials and executes zero requests.
    preview = CliRunner().invoke(app, ["evaluate", "outcomes", "--evaluation-root", str(tmp_path / "x"),
        "--outcome-root", str(tmp_path / "y"), "--price-cache", str(tmp_path / "cache.json"),
        "--retrieved-at", DUE.isoformat(), "--max-price-api-calls", "0", "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["lifecycle"]["mature_pending"] == 2
    result = CliRunner().invoke(app, ["evaluate", "analyze", "--evaluation-root", str(tmp_path / "x"),
        "--outcome-root", str(tmp_path / "y"), "--experiment-root", str(tmp_path / "experiments"),
        "--generated-at", DUE.isoformat(), "--output-json", str(tmp_path / "analysis.json"),
        "--output-markdown", str(tmp_path / "analysis.md")])
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "analysis.json").read_text())["lifecycle"]["mature_pending"] == 2
