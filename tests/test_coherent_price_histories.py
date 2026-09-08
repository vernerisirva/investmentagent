"""Production-path regressions for adjustment vintages, not arithmetic-only examples."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from investmentagent.cli import app
from investmentagent.evaluation import save_evaluation_snapshot
from investmentagent.evaluation_analysis import build_performance_v2_analysis
from investmentagent.evaluation_outcomes import (
    discover_outcome_sets, load_outcome_set, outcome_store_path, refresh_evaluation_outcomes,
    refresh_outcome_store, save_outcome_set, select_outcome_revisions,
)
from investmentagent.experiments import build_challenger_experiment_snapshot, save_experiment_snapshot
from investmentagent.market_price_cache import FileHistoricalPriceCache
from investmentagent.market_prices import EodhdHistoricalPriceProvider, FixtureHistoricalPriceProvider
from investmentagent.price_histories import (
    COHERENT_RETURN_METHOD, LEGACY_RETURN_METHOD, HistoryArchive, PriceHistoryBatch,
)
from test_evaluation_outcomes import (
    ONE_SESSION, _observation, _snapshot, _store_coherent_fixture, _observations_for_snapshots,
)
from test_challenger_experiment import _manual_run, _research

UTC = timezone.utc
OLD_TIME = datetime(2026, 8, 11, 18, tzinfo=UTC)
NEW_TIME = datetime(2026, 8, 12, 18, tzinfo=UTC)
ENTRY, EXIT = date(2026, 8, 10), date(2026, 8, 11)


def _run(root, snapshot, prices, *, at=NEW_TIME, budget=20, reprice=False,
         cache=None, output="outcomes", dry_run=False):
    save_evaluation_snapshot(root / "evaluations", snapshot)
    provider = FixtureHistoricalPriceProvider(prices)
    cache = cache or FileHistoricalPriceCache(root / "prices.json")
    summary = refresh_outcome_store(
        root / "evaluations", root / output, provider, retrieved_at=at,
        price_cache=cache, max_price_api_calls=budget, reprice=reprice, dry_run=dry_run,
    )
    return summary, provider, cache


def _prices(snapshot, entry, exit, at=NEW_TIME):
    row = snapshot.rows[0]
    return {row.company_id: [
        _observation(row, day, value, retrieved_at=at)
        for day, value in ((ENTRY, entry), (EXIT, exit)) if value is not None
    ]}


def _one(root):
    return next(o for store in discover_outcome_sets(root) for o in store.outcomes
                if o.horizon_label == "1_session")


@pytest.mark.parametrize("new_entry,new_exit,expected", [
    (50.0, 50.0, 0.0),  # split: numeric entry must rebase too
    (99.0, 99.0, 0.0),  # dividend: documented splits-and-dividends adjusted convention
    (50.0, 55.0, 10.0),  # uniform rebasing, ratio invariant
    (90.0, 110.0, 22.222222222222),  # genuine correction; no event type inferred
])
@pytest.mark.parametrize("lose_cache", [False, True])
def test_audit_adjustment_vintages_use_one_response(tmp_path, new_entry, new_exit, expected, lose_cache):
    snapshot = _snapshot(1, strategy="trading")
    _, _, cache = _run(tmp_path, snapshot, _prices(snapshot, 100.0, None, OLD_TIME), at=OLD_TIME)
    before = _one(tmp_path / "outcomes")
    assert before.status == "missing_exit"
    if lose_cache:
        cache = FileHistoricalPriceCache(tmp_path / "lost.json")
    summary, provider, cache = _run(tmp_path, snapshot, _prices(snapshot, new_entry, new_exit), cache=cache)
    after = _one(tmp_path / "outcomes")
    assert after.status == "priced"
    assert after.raw_forward_return_pct == pytest.approx(expected, abs=1e-10)
    assert provider.requests[0][1:3] == (ENTRY, EXIT)
    assert summary.provider_calls_executed == 1
    assert after.entry_session == before.entry_session
    assert after.target_exit_session == before.target_exit_session
    assert after.history_evidence.entry.adjusted_close == new_entry
    assert after.history_evidence.exit.adjusted_close == new_exit
    assert before in discover_outcome_sets(tmp_path / "outcomes")[0].revisions


def test_exit_only_response_cannot_complete_an_older_entry(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, _prices(snapshot, 100.0, None, OLD_TIME), at=OLD_TIME)
    _run(tmp_path, snapshot, _prices(snapshot, None, 50.0))
    outcome = _one(tmp_path / "outcomes")
    assert outcome.status == "missing_entry"
    assert outcome.raw_forward_return_pct is None


def test_unrelated_batches_with_equal_invocation_time_are_not_a_cache_hit(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    row = snapshot.rows[0]
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    first = _store_coherent_fixture(cache, row, _prices(snapshot, 100.0, None)[row.company_id], NEW_TIME)
    second = _store_coherent_fixture(cache, row, _prices(snapshot, None, 50.0)[row.company_id], NEW_TIME)
    assert first.metadata.completed_at == second.metadata.completed_at
    assert first.metadata.batch_id != second.metadata.batch_id
    summary, _, _ = _run(tmp_path, snapshot, {}, cache=cache, budget=0)
    assert summary.cache_hits == 0
    assert summary.work_deferred_by_budget == 1
    assert _one(tmp_path / "outcomes").status == "coherent_history_pending"
    assert _one(tmp_path / "outcomes").raw_forward_return_pct is None
    summary, _, _ = _run(tmp_path, snapshot, _prices(snapshot, 50.0, 50.0), cache=cache)
    assert summary.provider_calls_executed == 1
    assert _one(tmp_path / "outcomes").raw_forward_return_pct == 0.0


def test_coherent_history_reuse_and_shared_windows_across_cohorts(tmp_path):
    snapshots = (
        _snapshot(1, strategy="trading"), _snapshot(1),
        _snapshot(1, decision_at=datetime(2026, 8, 11, 8, tzinfo=UTC)),
    )
    at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots(snapshots, retrieved_at=at)
    for snapshot in snapshots:
        save_evaluation_snapshot(tmp_path / "evaluations", snapshot)
    first, _, cache = _run(tmp_path, snapshots[0], histories, at=at)
    assert first.provider_calls_executed == 1
    assert first.priced == 12
    stores = discover_outcome_sets(tmp_path / "outcomes")
    assert len({o.history_evidence.metadata.batch_id for s in stores for o in s.outcomes}) == 1
    second, _, _ = _run(tmp_path, snapshots[0], {}, at=at, cache=cache, output="reused")
    assert second.provider_calls_executed == 0
    assert second.priced == 12


def test_correction_appends_revision_and_uniform_rebasing_preserves_ratio(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, _prices(snapshot, 100.0, 110.0, OLD_TIME), at=OLD_TIME)
    original = _one(tmp_path / "outcomes")
    # Routine refresh must not reprice an already calculated outcome.
    summary, _, _ = _run(tmp_path, snapshot, _prices(snapshot, 50.0, 55.0))
    assert summary.provider_calls_executed == 0
    assert _one(tmp_path / "outcomes") == original
    _run(tmp_path, snapshot, _prices(snapshot, 50.0, 55.0), reprice=True)
    rebased = _one(tmp_path / "outcomes")
    assert rebased.raw_forward_return_pct == pytest.approx(original.raw_forward_return_pct, abs=1e-10)
    assert rebased.return_difference_pct == pytest.approx(0, abs=1e-10)
    assert rebased.prior_revision_id == original.revision_id
    later = NEW_TIME + timedelta(days=1)
    _run(tmp_path, snapshot, _prices(snapshot, 90.0, 110.0, later), at=later, reprice=True)
    corrected = _one(tmp_path / "outcomes")
    assert corrected.revision_reason == "coherent_endpoint_revision"
    assert corrected.raw_forward_return_pct == pytest.approx(22.222222222222)
    assert corrected.return_difference_pct == pytest.approx(12.222222222222)
    store = discover_outcome_sets(tmp_path / "outcomes")[0]
    assert original in store.revisions and rebased in store.revisions
    assert corrected.prior_revision_id == rebased.revision_id
    assert len(FileHistoricalPriceCache(tmp_path / "prices.json").history_archive.batches) == 3


@pytest.mark.parametrize("conflict", ["symbol", "currency", "market", "provider", "currency_missing"])
def test_conflicting_response_metadata_fails_safely(tmp_path, conflict):
    snapshot = _snapshot(1, strategy="trading")
    prices = _prices(snapshot, 100.0, 110.0)
    rows = prices[snapshot.rows[0].company_id]
    field, value = {"symbol": ("symbol", "WRONG.ST"), "currency": ("currency", "USD"),
                    "market": ("market", "helsinki"), "provider": ("provider", "different"),
                    "currency_missing": ("currency", None)}[conflict]
    rows[1] = replace(rows[1], **{field: value})
    _run(tmp_path, snapshot, prices)
    assert _one(tmp_path / "outcomes").status == "provider_error"
    assert _one(tmp_path / "outcomes").raw_forward_return_pct is None


def test_response_without_batch_provenance_cannot_price(tmp_path):
    snapshot = _snapshot(1, strategy="trading")

    class Unverified(FixtureHistoricalPriceProvider):
        def get_history(self, *args, **kwargs):
            return replace(super().get_history(*args, **kwargs), response_id=None)

    store = refresh_evaluation_outcomes(snapshot, Unverified(_prices(snapshot, 100.0, 110.0)),
                                       retrieved_at=NEW_TIME, horizons=ONE_SESSION)
    assert store.outcomes[0].status == "provider_error"
    assert store.outcomes[0].raw_forward_return_pct is None


def test_raw_only_history_can_be_retried_without_permanent_exclusion(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    row = snapshot.rows[0]
    bad = FixtureHistoricalPriceProvider({}, unsupported_adjustments=[row.company_id])
    first = refresh_evaluation_outcomes(snapshot, bad, retrieved_at=OLD_TIME, horizons=ONE_SESSION)
    assert first.outcomes[0].status == "corporate_action_unsupported"
    second = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 50.0, 50.0)),
                                        retrieved_at=NEW_TIME, existing=first, horizons=ONE_SESSION)
    assert second.outcomes[0].status == "priced"
    assert first.outcomes[0] in second.revisions


def _legacy(store, *, unsupported=False):
    outcomes = tuple(replace(
        o, schema_version=1, return_methodology=LEGACY_RETURN_METHOD, history_evidence=None, history_metadata=None,
        calculated_at=None, prior_revision_id=None, revision_reason=None, return_difference_pct=None,
        status="corporate_action_unsupported" if unsupported else o.status,
    ) for o in store.outcomes)
    return replace(store, schema_version=1, outcomes=outcomes, revisions=())


def test_legacy_files_stay_unchanged_and_explicit_reprocessing_has_dry_run(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    store = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100.0, 110.0)), retrieved_at=NEW_TIME)
    legacy = _legacy(store, unsupported=True)
    path = save_outcome_set(outcome_store_path(tmp_path / "outcomes", snapshot), legacy)
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    cache.store(snapshot.rows[0].company_id, _prices(snapshot, 100.0, 110.0)[snapshot.rows[0].company_id])
    original, cached_bytes = path.read_bytes(), cache.path.read_bytes()
    summary, _, _ = _run(tmp_path, snapshot, {}, cache=cache)
    assert summary.legacy_records_skipped == 4 and summary.provider_calls_executed == 0
    preview, _, _ = _run(tmp_path, snapshot, {}, cache=cache, reprice=True, dry_run=True)
    assert preview.records_requiring_refetch == 1
    assert preview.records_missing_metadata == 1
    assert preview.coherent_records_reusable == 0
    assert preview.provider_calls_executed == 0 and not preview.files_written
    assert path.read_bytes() == original and cache.path.read_bytes() == cached_bytes
    assert not cache.history_archive.batches
    _run(tmp_path, snapshot, _prices(snapshot, 50.0, 50.0), cache=cache, reprice=True)
    assert path.read_bytes() == original and cache.path.read_bytes() == cached_bytes
    stores = discover_outcome_sets(tmp_path / "outcomes")
    assert len(stores) == 2
    repaired = next(s for s in stores if s.schema_version == 2)
    assert repaired.outcomes[0].status == "priced"
    assert repaired.outcomes[0].raw_forward_return_pct == 0.0
    assert legacy.outcomes[0] in repaired.revisions
    with pytest.raises(ValueError, match="mixed return methodologies"):
        build_performance_v2_analysis([snapshot], stores, generated_at=NEW_TIME)
    selected, info = select_outcome_revisions(stores, return_methodology=COHERENT_RETURN_METHOD)
    assert len(selected) == 1 and info["adjustment_basis_verified"]


def test_analysis_cutoff_and_paired_analysis_select_identical_revisions(tmp_path):
    _, result, snapshot = _manual_run([_research(i) for i in range(50)], list(range(50, 0, -1)))
    experiment = build_challenger_experiment_snapshot(result, snapshot)
    evaluation_path = save_evaluation_snapshot(tmp_path / "evaluations", snapshot)
    experiment_path = save_experiment_snapshot(tmp_path / "experiments", experiment)
    original_eval, original_sidecar = evaluation_path.read_bytes(), experiment_path.read_bytes()

    def prices(at, reverse=False):
        return {row.company_id: [
            _observation(row, ENTRY, 100.0, retrieved_at=at),
            _observation(row, EXIT, 100.0 + (50 - i if reverse else i), retrieved_at=at),
        ] for i, row in enumerate(snapshot.rows)}

    first = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(prices(OLD_TIME)),
                                       retrieved_at=OLD_TIME, horizons=ONE_SESSION)
    revised = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(prices(NEW_TIME, True)),
                                         retrieved_at=NEW_TIME, existing=first, horizons=ONE_SESSION, reprice=True)
    path = save_outcome_set(tmp_path / "outcomes.json", first)
    save_outcome_set(path, revised)
    revised = load_outcome_set(path)
    early = build_performance_v2_analysis([snapshot], [revised], generated_at=NEW_TIME,
        data_cutoff=OLD_TIME, return_methodology=COHERENT_RETURN_METHOD, experiment_snapshots=[experiment])
    latest = build_performance_v2_analysis([snapshot], [revised], generated_at=NEW_TIME,
        data_cutoff=NEW_TIME, return_methodology=COHERENT_RETURN_METHOD, experiment_snapshots=[experiment])
    assert early["run_metrics"][0]["valid_company_count"] == 50
    assert early["run_metrics"][0]["universe_equal_weight_return_pct"] == pytest.approx(24.5)
    assert latest["run_metrics"][0]["universe_equal_weight_return_pct"] == pytest.approx(25.5)
    for analysis in (early, latest):
        paired = analysis["challenger_analysis"]
        assert analysis["methodology"]["selected_outcomes_hash"] == paired["methodology"]["selected_outcomes_hash"]
        assert paired["methodology"]["return_methodology"] == COHERENT_RETURN_METHOD
    selected, _ = select_outcome_revisions([revised], data_cutoff=OLD_TIME)
    assert selected[0].outcomes == first.outcomes
    before_prices, _ = select_outcome_revisions([revised], data_cutoff=OLD_TIME - timedelta(hours=1))
    assert all(o.raw_forward_return_pct is None for o in before_prices[0].outcomes)
    assert evaluation_path.read_bytes() == original_eval
    assert experiment_path.read_bytes() == original_sidecar


def test_archive_roundtrip_idempotency_distinct_retrievals_and_atomic_failure(tmp_path, monkeypatch):
    snapshot = _snapshot(1, strategy="trading")
    row = snapshot.rows[0]
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    batch = _store_coherent_fixture(cache, row, _prices(snapshot, 100, 110)[row.company_id], NEW_TIME)
    archive = HistoryArchive(cache.history_archive.path)
    assert archive.batches == (batch,)
    original = archive.path.read_bytes()
    assert not archive.store(batch)
    assert archive.path.read_bytes() == original
    # Same time and same content, genuinely different retrieval ID: retain both.
    fresh = replace(batch, metadata=replace(batch.metadata, response_id="another-retrieval"))
    assert fresh.metadata.content_hash == batch.metadata.content_hash
    assert fresh.metadata.batch_id != batch.metadata.batch_id
    with monkeypatch.context() as patch:
        patch.setattr("investmentagent.price_histories.os.replace", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
        with pytest.raises(OSError, match="disk failure"):
            archive.store(fresh)
    assert archive.path.read_bytes() == original
    assert archive.batches == (batch,)
    assert not list(tmp_path.glob("*.tmp"))
    assert archive.store(fresh)
    assert len(HistoryArchive(archive.path).batches) == 2
    with pytest.raises(ValueError, match="cannot mutate"):
        archive.store(replace(batch, metadata=replace(batch.metadata, currency_provenance="changed")))


@pytest.mark.parametrize("damage", ["schema", "hash", "price", "batch_id", "timestamp", "raw_close"])
def test_corrupted_histories_are_rejected(tmp_path, damage):
    snapshot = _snapshot(1, strategy="trading")
    _, _, cache = _run(tmp_path, snapshot, _prices(snapshot, 100.0, 110.0))
    path = cache.history_archive.path
    payload = json.loads(path.read_text())
    history = payload["histories"][0]
    if damage == "schema":
        payload["schema_version"] = 999
    elif damage == "hash":
        history["metadata"]["content_hash"] = "0" * 64
    elif damage == "price":
        history["observations"][0]["adjusted_close"] = -1
    elif damage == "raw_close":
        history["observations"][0]["close"] = 999
    elif damage == "batch_id":
        history["batch_id"] = "invented"
    else:
        history["metadata"]["completed_at"] = "2026-08-12T18:00:00"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid coherent history"):
        HistoryArchive(path)


def test_outcomes_self_contained_and_cannot_drop_prior_revisions(tmp_path, monkeypatch):
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, _prices(snapshot, 100.0, 110.0, OLD_TIME), at=OLD_TIME)
    path = outcome_store_path(tmp_path / "outcomes", snapshot)
    original = path.read_bytes()
    first = load_outcome_set(path)
    later = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 90.0, 110.0)),
                                       retrieved_at=NEW_TIME, existing=first, reprice=True)
    with monkeypatch.context() as patch:
        patch.setattr("investmentagent.evaluation_outcomes.os.replace", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
        with pytest.raises(OSError):
            save_outcome_set(path, later)
    assert path.read_bytes() == original
    save_outcome_set(path, later)
    with pytest.raises(ValueError, match="retaining prior"):
        save_outcome_set(path, first)
    # Evict the operational archive; the existing result and endpoint arithmetic survive.
    FileHistoricalPriceCache(tmp_path / "prices.json").history_archive.path.unlink()
    saved_bytes = path.read_bytes()
    summary, _, _ = _run(tmp_path, snapshot, {})
    assert summary.provider_calls_executed == 0 and path.read_bytes() == saved_bytes
    outcome = load_outcome_set(path).outcomes[0]
    evidence = outcome.history_evidence
    assert outcome.raw_forward_return_pct == pytest.approx((evidence.exit.adjusted_close / evidence.entry.adjusted_close - 1) * 100)
    payload = json.loads(path.read_text())
    assert "observations" not in payload["outcomes"][0]["history_evidence"]
    payload["outcomes"][0]["history_evidence"]["entry"]["adjusted_close"] = 45
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_outcome_set(path)


def test_eodhd_records_actual_completion_and_calculation_clocks():
    snapshot = _snapshot(1, strategy="trading")
    times = iter((NEW_TIME, NEW_TIME + timedelta(seconds=2)))
    provider = EodhdHistoricalPriceProvider("secret", clock=lambda: next(times),
        fetcher=lambda url: json.dumps([
            {"date": "2026-08-10", "close": 100, "adjusted_close": 50},
            {"date": "2026-08-11", "close": 50, "adjusted_close": 50},
        ]))
    store = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=OLD_TIME, horizons=ONE_SESSION)
    outcome = store.outcomes[0]
    assert outcome.entry_retrieved_at == NEW_TIME
    assert outcome.exit_retrieved_at == NEW_TIME
    assert outcome.calculated_at == NEW_TIME + timedelta(seconds=2)
    assert outcome.history_evidence.metadata.currency_provenance == "security_reference_country_inference"
    selected, _ = select_outcome_revisions([store], data_cutoff=OLD_TIME)
    assert selected[0].outcomes[0].status == "not_due"
    assert "secret" not in json.dumps(store.as_payload())


def test_cli_dry_run_needs_no_key_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    snapshot = _snapshot(1, strategy="trading")
    save_evaluation_snapshot(tmp_path / "evaluations", snapshot)
    args = ["evaluate", "outcomes", "--evaluation-root", str(tmp_path / "evaluations"),
            "--outcome-root", str(tmp_path / "outcomes"), "--price-cache", str(tmp_path / "prices.json"),
            "--retrieved-at", NEW_TIME.isoformat(), "--reprice", "--dry-run"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["provider_calls_executed"] == 0
    assert not (tmp_path / "outcomes").exists()
    assert not (tmp_path / "prices.histories-v2.json").exists()


def test_replaying_recorded_response_does_not_duplicate_outcome_revision():
    snapshot = _snapshot(1, strategy="trading")

    class Replay(FixtureHistoricalPriceProvider):
        recorded = None

        def get_history(self, *args, **kwargs):
            if self.recorded is None:
                self.recorded = super().get_history(*args, **kwargs)
            return self.recorded

    provider = Replay(_prices(snapshot, 100.0, 110.0))
    first = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=NEW_TIME, horizons=ONE_SESSION)
    replay = refresh_evaluation_outcomes(snapshot, provider, retrieved_at=NEW_TIME + timedelta(days=1),
                                        horizons=ONE_SESSION, existing=first, reprice=True)
    assert replay == first


def test_later_retrieval_with_backdated_invocation_is_not_visible_at_old_cutoff():
    snapshot = _snapshot(1, strategy="trading")
    first = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100.0, 110.0, OLD_TIME)),
                                       retrieved_at=OLD_TIME, horizons=ONE_SESSION)
    later = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 50.0, 50.0, NEW_TIME)),
                                       retrieved_at=OLD_TIME, horizons=ONE_SESSION, existing=first, reprice=True)
    assert later.outcomes[0].entry_retrieved_at == NEW_TIME
    selected, _ = select_outcome_revisions([later], data_cutoff=OLD_TIME)
    assert selected[0].outcomes == first.outcomes


def test_all_changed_provider_symbols_do_not_replace_established_security():
    snapshot = _snapshot(1, strategy="trading")
    first = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(_prices(snapshot, 100.0, 110.0, OLD_TIME)),
                                       retrieved_at=OLD_TIME, horizons=ONE_SESSION)

    class WrongSymbol(FixtureHistoricalPriceProvider):
        def get_history(self, *args, **kwargs):
            history = super().get_history(*args, **kwargs)
            return replace(history, symbol="WRONG.ST", observations=tuple(
                replace(row, symbol="WRONG.ST") for row in history.observations))

    revised = refresh_evaluation_outcomes(snapshot, WrongSymbol(_prices(snapshot, 50.0, 50.0)),
                                         retrieved_at=NEW_TIME, existing=first, horizons=ONE_SESSION, reprice=True)
    assert revised.outcomes[0].status == "provider_error"
    assert first.outcomes[0] in revised.revisions


def test_cache_hit_retains_history_completion_but_records_new_calculation(tmp_path):
    snapshot = _snapshot(1, strategy="trading")
    _, _, cache = _run(tmp_path, snapshot, _prices(snapshot, 100.0, 110.0, OLD_TIME), at=OLD_TIME)
    summary, _, _ = _run(tmp_path, snapshot, {}, cache=cache, output="new-outcomes")
    outcome = _one(tmp_path / "new-outcomes")
    assert summary.provider_calls_executed == 0
    assert outcome.entry_retrieved_at == OLD_TIME
    assert outcome.calculated_at == NEW_TIME


def test_cli_requires_bounded_repricing_and_rejects_public_history_location(tmp_path):
    runner = CliRunner()
    unbounded = runner.invoke(app, ["evaluate", "outcomes", "--reprice"])
    assert unbounded.exit_code != 0 and "requires --run-id" in unbounded.output
    public = runner.invoke(app, ["evaluate", "outcomes", "--price-cache", "data/prices.json", "--dry-run"])
    assert public.exit_code != 0 and "complete vendor histories" in public.output
