import json
import math
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investmentagent.analysis_eligibility import (
    AnalysisEligibilityCriteria,
    assess_analysis_eligibility,
)
from investmentagent.cli import app
from investmentagent.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EvaluationCompanyRow,
    EvaluationSnapshot,
    evaluation_run_id,
    save_evaluation_snapshot,
)
from investmentagent.evaluation_analysis import (
    build_performance_v2_analysis,
    render_performance_v2_markdown,
    spearman_rank_correlation,
)
from investmentagent.evaluation_outcomes import (
    DEFAULT_STRATEGY_HORIZONS,
    OUTCOME_SCHEMA_VERSION,
    EvaluationOutcomeSet,
    HorizonDefinition,
    discover_outcome_sets,
    load_outcome_set,
    outcome_store_path,
    refresh_evaluation_outcomes,
    refresh_outcome_store,
    save_outcome_set,
)
from investmentagent.market_calendar import (
    advance_market_sessions,
    first_session_closing_after,
    market_for_country,
)
from investmentagent.market_prices import (
    ADJUSTED_PRICE_TYPE,
    EodhdHistoricalPriceProvider,
    FixtureHistoricalPriceProvider,
    HistoricalPriceObservation,
    SecurityReference,
)
from investmentagent.market_price_cache import FileHistoricalPriceCache


UTC = timezone.utc
RUNNER = CliRunner()
ONE_SESSION = (HorizonDefinition("1_session", 1),)
TEST_ANALYSIS_ELIGIBILITY = AnalysisEligibilityCriteria(0.0, 2)


def _timestamp(day: int = 10, hour: int = 8) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def _snapshot(
    count: int,
    *,
    strategy: str = "long-term",
    decision_at: datetime | None = None,
    model_version: str = "nordic-ranking-v1",
    countries: tuple[str, ...] = ("SE",),
    scores: list[float] | None = None,
) -> EvaluationSnapshot:
    decision = decision_at or _timestamp()
    configuration = {"provider": "fixture", "test": "performance-v2"}
    report_date = decision.date()
    rows = []
    gate_tiers = (
        "High-conviction candidate",
        "Fundamental watchlist",
        "Speculative monitor",
        "Insufficient evidence",
    )
    for index in range(count):
        rank = index + 1
        country = countries[index % len(countries)]
        score = scores[index] if scores is not None else float(count - index)
        rows.append(
            EvaluationCompanyRow(
                company_id=f"isin:{country}{index:010d}",
                isin=f"{country}{index:010d}",
                ticker=f"C{index:03d}",
                country=country,
                name=f"Company {index:03d}",
                exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
                segment="first_north" if index % 2 else "main_market",
                sector="Software",
                eligible_universe_member=True,
                rank=rank,
                score={
                    "total": score,
                    "value": score,
                    "discovery": 0.0,
                    "catalyst": 0.0,
                    "risk_penalty": 0.0,
                    "data_quality_penalty": 0.0,
                },
                long_term=(
                    {"gate_tier": gate_tiers[index % len(gate_tiers)]}
                    if strategy == "long-term"
                    else None
                ),
                data_quality="good",
                cache={
                    "enabled": False,
                    "participated": False,
                    "state": "disabled",
                    "refreshed_this_run": False,
                    "retrieved_at": None,
                    "providers": [],
                },
                model_inputs={"available_financial_fields": [], "threshold_flags": {}},
            )
        )
    run_id = evaluation_run_id(
        strategy=strategy,
        decision_at=decision,
        report_date=report_date,
        countries=countries,
        scoring_model_version=model_version,
        configuration=configuration,
    )
    return EvaluationSnapshot(
        schema_version=EVALUATION_SCHEMA_VERSION,
        run_id=run_id,
        strategy=strategy,
        decision_at=decision,
        report_date=report_date,
        universe_size=count,
        countries=countries,
        scoring_model_version=model_version,
        configuration=configuration,
        diagnostics={"fixture": True},
        rows=tuple(rows),
    )


def _observation(
    row: EvaluationCompanyRow,
    session_date: date,
    adjusted_close: float,
    *,
    retrieved_at: datetime,
    close: float | None = None,
) -> HistoricalPriceObservation:
    market = market_for_country(row.country)
    return HistoricalPriceObservation(
        provider="fixture",
        symbol=f"{row.ticker}.{'ST' if row.country == 'SE' else 'HE'}",
        market=market,
        session_date=session_date,
        close=close,
        adjusted_close=adjusted_close,
        currency="SEK" if row.country == "SE" else "EUR",
        retrieved_at=retrieved_at,
    )


def _priced_store(
    snapshot: EvaluationSnapshot,
    returns_pct: list[float],
    *,
    horizon: tuple[HorizonDefinition, ...] = ONE_SESSION,
) -> EvaluationOutcomeSet:
    retrieved_at = snapshot.decision_at + timedelta(days=20)
    histories = {}
    for row, forward_return in zip(snapshot.rows, returns_pct, strict=True):
        market = market_for_country(row.country)
        entry = first_session_closing_after(snapshot.decision_at, market).day
        observations = [_observation(row, entry, 100.0, retrieved_at=retrieved_at)]
        for definition in horizon:
            exit_day = advance_market_sessions(entry, definition.sessions, market).day
            observations.append(
                _observation(
                    row,
                    exit_day,
                    100.0 * (1.0 + forward_return / 100.0),
                    retrieved_at=retrieved_at,
                )
            )
        histories[row.company_id] = observations
    return refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
        horizons=horizon,
    )


def _partially_priced_store(
    snapshot: EvaluationSnapshot,
    priced_rows: list[EvaluationCompanyRow],
    returns_pct: list[float],
) -> EvaluationOutcomeSet:
    retrieved_at = snapshot.decision_at + timedelta(days=20)
    histories = {}
    for row, forward_return in zip(priced_rows, returns_pct, strict=True):
        market = market_for_country(row.country)
        entry = first_session_closing_after(snapshot.decision_at, market).day
        exit_day = advance_market_sessions(entry, 1, market).day
        histories[row.company_id] = (
            _observation(row, entry, 100.0, retrieved_at=retrieved_at),
            _observation(
                row,
                exit_day,
                100.0 * (1.0 + forward_return / 100.0),
                retrieved_at=retrieved_at,
            ),
        )
    return refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
        horizons=ONE_SESSION,
    )


def test_adjusted_price_is_used_instead_of_raw_close_for_split():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    retrieved_at = _timestamp(12, 18)
    provider = FixtureHistoricalPriceProvider(
        {
            row.company_id: (
                _observation(row, entry, 50.0, close=100.0, retrieved_at=retrieved_at),
                _observation(row, exit_day, 50.0, close=50.0, retrieved_at=retrieved_at),
            )
        }
    )

    outcome = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=retrieved_at, horizons=ONE_SESSION
    ).outcomes[0]

    assert outcome.status == "priced"
    assert outcome.raw_forward_return_pct == 0.0
    assert outcome.price_type == ADJUSTED_PRICE_TYPE
    assert outcome.entry_price == 50.0


def test_previous_close_can_never_become_post_decision_entry():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    previous = advance_market_sessions(date(2026, 8, 7), 0, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    retrieved_at = _timestamp(12, 18)
    provider = FixtureHistoricalPriceProvider(
        {
            row.company_id: (
                _observation(row, previous, 10.0, retrieved_at=retrieved_at),
                _observation(row, entry, 100.0, retrieved_at=retrieved_at),
                _observation(row, exit_day, 110.0, retrieved_at=retrieved_at),
            )
        }
    )

    outcome = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=retrieved_at, horizons=ONE_SESSION
    ).outcomes[0]

    assert previous < outcome.entry_session
    assert outcome.entry_price == 100.0
    assert outcome.raw_forward_return_pct == pytest.approx(10.0)


def test_dividend_adjusted_prices_do_not_create_a_fake_loss():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    retrieved_at = _timestamp(12, 18)
    provider = FixtureHistoricalPriceProvider(
        {
            row.company_id: (
                _observation(row, entry, 95.0, close=100.0, retrieved_at=retrieved_at),
                _observation(row, exit_day, 95.0, close=95.0, retrieved_at=retrieved_at),
            )
        }
    )

    outcome = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=retrieved_at, horizons=ONE_SESSION
    ).outcomes[0]

    assert outcome.raw_forward_return_pct == 0.0


def test_eodhd_provider_parses_adjusted_close_and_explicit_metadata():
    payload = json.dumps(
        [
            {
                "date": "2026-08-10",
                "close": 100.0,
                "adjusted_close": 98.5,
            }
        ]
    )
    provider = EodhdHistoricalPriceProvider("secret", fetcher=lambda url: payload)
    security = SecurityReference("isin:1", "SE1", "ABC", "SE", "Nasdaq Stockholm", "SEK")

    history = provider.get_history(
        security,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
        market="stockholm",
        retrieved_at=_timestamp(12),
    )

    assert history.status == "ok"
    assert history.symbol == "ABC.ST"
    assert history.observations[0].adjusted_close == 98.5
    assert history.observations[0].close == 100.0
    assert history.observations[0].is_adjusted is True
    assert history.observations[0].currency == "SEK"


def test_eodhd_provider_never_substitutes_raw_close_for_missing_adjusted_close():
    provider = EodhdHistoricalPriceProvider(
        "secret",
        fetcher=lambda url: json.dumps([{"date": "2026-08-10", "close": 100.0}]),
    )
    security = SecurityReference("isin:1", "SE1", "ABC", "SE", "Nasdaq Stockholm", "SEK")

    history = provider.get_history(
        security,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
        market="stockholm",
        retrieved_at=_timestamp(12),
    )

    assert history.status == "corporate_action_unsupported"
    assert not history.observations


def test_eodhd_provider_stops_network_calls_after_repeated_provider_failures():
    calls = []

    def failing_fetcher(url):
        calls.append(url)
        raise TimeoutError("provider unavailable")

    provider = EodhdHistoricalPriceProvider("secret", fetcher=failing_fetcher)
    security = SecurityReference("isin:1", "SE1", "ABC", "SE", "Nasdaq Stockholm", "SEK")
    histories = [
        provider.get_history(
            security,
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 11),
            market="stockholm",
            retrieved_at=_timestamp(12),
        )
        for _ in range(5)
    ]

    assert len(calls) == 3
    assert all(history.status == "provider_error" for history in histories)
    assert "circuit opened" in histories[-1].detail


def test_outcome_is_not_due_until_target_session_has_closed():
    snapshot = _snapshot(1)
    provider = FixtureHistoricalPriceProvider({})

    store = refresh_evaluation_outcomes(
        snapshot,
        provider,
        retrieved_at=_timestamp(10, 12),
        horizons=ONE_SESSION,
    )

    assert store.outcomes[0].status == "not_due"
    assert store.outcomes[0].retrieved_at is None


def test_missing_entry_is_explicit():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    retrieved_at = _timestamp(12, 18)
    provider = FixtureHistoricalPriceProvider(
        {row.company_id: [_observation(row, exit_day, 101.0, retrieved_at=retrieved_at)]}
    )

    outcome = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=retrieved_at, horizons=ONE_SESSION
    ).outcomes[0]

    assert outcome.status == "missing_entry"
    assert outcome.entry_price is None


def test_missing_exit_preserves_a_valid_entry_for_later_refresh():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    first_retrieval = _timestamp(12, 18)
    first = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(
            {row.company_id: [_observation(row, entry, 100.0, retrieved_at=first_retrieval)]}
        ),
        retrieved_at=first_retrieval,
        horizons=ONE_SESSION,
    )
    assert first.outcomes[0].status == "missing_exit"

    second_retrieval = _timestamp(13, 18)
    second = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(
            {
                row.company_id: (
                    _observation(row, entry, 100.0, retrieved_at=second_retrieval),
                    _observation(row, exit_day, 110.0, retrieved_at=second_retrieval),
                )
            }
        ),
        retrieved_at=second_retrieval,
        existing=first,
        horizons=ONE_SESSION,
    )

    outcome = second.outcomes[0]
    assert outcome.status == "priced"
    assert outcome.entry_price == 100.0
    assert outcome.entry_retrieved_at == first_retrieval
    assert outcome.raw_forward_return_pct == pytest.approx(10.0)


def test_provider_revision_never_replaces_established_entry():
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
    exit_day = advance_market_sessions(entry, 1, "stockholm").day
    first_retrieval = _timestamp(12, 18)
    first = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(
            {row.company_id: [_observation(row, entry, 100.0, retrieved_at=first_retrieval)]}
        ),
        retrieved_at=first_retrieval,
        horizons=ONE_SESSION,
    )
    second_retrieval = _timestamp(13, 18)
    revised = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(
            {
                row.company_id: (
                    _observation(row, entry, 50.0, retrieved_at=second_retrieval),
                    _observation(row, exit_day, 55.0, retrieved_at=second_retrieval),
                )
            }
        ),
        retrieved_at=second_retrieval,
        existing=first,
        horizons=ONE_SESSION,
    ).outcomes[0]

    assert revised.status == "corporate_action_unsupported"
    assert revised.entry_price == 100.0
    assert "revised" in revised.detail


def test_unresolved_symbol_and_provider_error_are_visible():
    snapshot = _snapshot(2)
    provider = FixtureHistoricalPriceProvider(
        {},
        unresolved=[snapshot.rows[0].company_id],
        provider_errors={snapshot.rows[1].company_id: "quota exhausted"},
    )

    store = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=_timestamp(12, 18), horizons=ONE_SESSION
    )

    assert [outcome.status for outcome in store.outcomes] == [
        "symbol_unresolved",
        "provider_error",
    ]


def test_outcome_serialization_round_trip_and_schema_version(tmp_path):
    snapshot = _snapshot(3)
    store = _priced_store(snapshot, [3.0, 2.0, 1.0])
    path = save_outcome_set(tmp_path / "outcomes.json", store)

    restored = load_outcome_set(path)

    assert restored == store
    assert restored.outcomes[0].schema_version == OUTCOME_SCHEMA_VERSION
    assert restored.outcomes[0].raw_forward_return_pct == pytest.approx(3.0)


def test_outcome_save_is_idempotent(tmp_path):
    store = _priced_store(_snapshot(2), [2.0, 1.0])
    path = tmp_path / "outcomes.json"

    save_outcome_set(path, store)
    first_bytes = path.read_bytes()
    save_outcome_set(path, store)

    assert path.read_bytes() == first_bytes


def test_unsupported_outcome_store_schema_is_rejected(tmp_path):
    path = tmp_path / "unsupported.json"
    path.write_text(json.dumps({"schema_version": 99}))

    with pytest.raises(ValueError, match="unsupported outcome-store schema: 99"):
        load_outcome_set(path)


def test_refreshing_outcomes_does_not_mutate_evaluation_snapshot(tmp_path):
    snapshot = _snapshot(2)
    evaluation_path = save_evaluation_snapshot(tmp_path / "evaluations", snapshot)
    original = evaluation_path.read_bytes()

    _priced_store(snapshot, [2.0, 1.0])

    assert evaluation_path.read_bytes() == original


def test_perfect_positive_and_negative_spearman_ic():
    assert spearman_rank_correlation([4, 3, 2, 1], [40, 30, 20, 10]) == pytest.approx(1.0)
    assert spearman_rank_correlation([4, 3, 2, 1], [10, 20, 30, 40]) == pytest.approx(-1.0)


def test_spearman_handles_tied_scores_with_average_ranks():
    value = spearman_rank_correlation([3, 3, 1, 1], [4, 3, 2, 1])

    assert value == pytest.approx(0.8944271909999159)


def test_central_positive_signal_and_inverted_signal_regression():
    snapshot = _snapshot(100)
    positive_returns = [float(101 - rank) / 10 for rank in range(1, 101)]
    positive = build_performance_v2_analysis(
        (snapshot,),
        (_priced_store(snapshot, positive_returns),),
        generated_at=_timestamp(20),
    )
    positive_run = positive["run_metrics"][0]
    positive_group = positive["groups"][0]

    assert positive_run["score_return_spearman_ic"] == pytest.approx(1.0)
    assert positive_run["final_rank_return_spearman_ic"] == pytest.approx(1.0)
    assert positive_run["top_vs_universe"]["top_decile_minus_universe_pct"] > 0
    assert positive_run["top_vs_universe"]["top_decile_minus_bottom_decile_pct"] > 0
    assert positive_group["bucket_schemes"][0]["bucket_count"] == 10
    assert positive_group["bucket_schemes"][0]["monotonic_run_count"] == 1

    inverted_returns = list(reversed(positive_returns))
    inverted = build_performance_v2_analysis(
        (snapshot,),
        (_priced_store(snapshot, inverted_returns),),
        generated_at=_timestamp(20),
    )
    inverted_run = inverted["run_metrics"][0]
    assert inverted_run["score_return_spearman_ic"] == pytest.approx(-1.0)
    assert inverted_run["final_rank_return_spearman_ic"] == pytest.approx(-1.0)
    assert inverted_run["top_vs_universe"]["top_decile_minus_universe_pct"] < 0
    assert inverted_run["top_vs_universe"]["top_decile_minus_bottom_decile_pct"] < 0


def test_benchmark_uses_valid_members_of_original_evaluation_universe():
    snapshot = _snapshot(3)
    retrieved_at = _timestamp(12, 18)
    histories = {}
    for row, forward_return in zip(snapshot.rows[:2], (10.0, 20.0), strict=True):
        entry = first_session_closing_after(snapshot.decision_at, "stockholm").day
        exit_day = advance_market_sessions(entry, 1, "stockholm").day
        histories[row.company_id] = (
            _observation(row, entry, 100.0, retrieved_at=retrieved_at),
            _observation(row, exit_day, 100 + forward_return, retrieved_at=retrieved_at),
        )
    store = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
        horizons=ONE_SESSION,
    )

    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )
    run = analysis["run_metrics"][0]

    assert run["original_universe_size"] == 3
    assert run["valid_company_count"] == 2
    assert run["universe_equal_weight_return_pct"] == pytest.approx(15.0)
    assert run["status_counts"]["symbol_unresolved"] == 1


def test_same_country_benchmarks_and_country_specific_ic_are_reported():
    snapshot = _snapshot(4, countries=("SE", "FI"))
    store = _priced_store(snapshot, [8.0, 4.0, 2.0, 0.0])

    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )
    run = analysis["run_metrics"][0]
    company = run["company_benchmarks"][0]

    assert company["same_country_equal_weight_return_pct"] == pytest.approx(5.0)
    assert company["excess_vs_country_pct"] == pytest.approx(3.0)
    assert {row["country"] for row in run["country_metrics"]} == {"SE", "FI"}
    assert all(row["score_return_spearman_ic"] == pytest.approx(1.0) for row in run["country_metrics"])


def test_long_term_gate_tier_statistics_keep_sample_sizes():
    snapshot = _snapshot(8)
    store = _priced_store(snapshot, [8, 7, 6, 5, 4, 3, 2, 1])

    analysis = build_performance_v2_analysis(
        (snapshot,),
        (store,),
        generated_at=_timestamp(20),
        eligibility_criteria=TEST_ANALYSIS_ELIGIBILITY,
    )
    tiers = analysis["groups"][0]["gate_tiers"]

    assert {tier["tier"] for tier in tiers} == {
        "High-conviction candidate",
        "Fundamental watchlist",
        "Speculative monitor",
        "Insufficient evidence",
    }
    assert sum(tier["observations"] for tier in tiers) == 8


def test_model_versions_are_never_aggregated_together():
    first = _snapshot(4, model_version="nordic-ranking-v1")
    second = _snapshot(
        4,
        decision_at=_timestamp(11),
        model_version="nordic-ranking-v2-challenger",
    )

    analysis = build_performance_v2_analysis(
        (first, second),
        (_priced_store(first, [4, 3, 2, 1]), _priced_store(second, [4, 3, 2, 1])),
        generated_at=_timestamp(25),
    )

    assert len(analysis["groups"]) == 2
    assert {group["scoring_model_version"] for group in analysis["groups"]} == {
        "nordic-ranking-v1",
        "nordic-ranking-v2-challenger",
    }


def test_repeated_companies_aggregate_ic_by_run_before_summary():
    large = _snapshot(100)
    small = _snapshot(2, decision_at=_timestamp(11))
    large_store = _priced_store(large, [float(100 - index) for index in range(100)])
    small_store = _priced_store(small, [0.0, 1.0])

    analysis = build_performance_v2_analysis(
        (large, small), (large_store, small_store), generated_at=_timestamp(25)
    )
    group = analysis["groups"][0]

    assert analysis["run_metrics"][0]["analysis_eligible"] is True
    assert analysis["run_metrics"][1]["analysis_eligible"] is False
    assert group["score_ic"]["mean"] == pytest.approx(1.0)
    assert group["evaluated_run_count"] == 1
    assert group["due_run_count"] == 2
    assert group["partial_run_count"] == 1
    assert group["unique_company_count"] == 100


@pytest.mark.parametrize(
    ("valid_count", "original_count", "expected"),
    [
        (2, 900, False),
        (20, 900, False),
        (600, 900, False),
        (650, 900, True),
        (35, 40, False),
    ],
)
def test_default_cross_sectional_analysis_eligibility(
    valid_count: int, original_count: int, expected: bool
):
    result = assess_analysis_eligibility(valid_count, original_count)

    assert result.eligible is expected
    assert result.coverage_pct == pytest.approx(valid_count / original_count * 100)
    assert result.minimum_coverage_pct == 70.0
    assert result.minimum_valid_companies == 50


def test_two_of_nine_hundred_run_is_retained_as_descriptive_only():
    snapshot = _snapshot(900)
    store = _partially_priced_store(
        snapshot,
        list(snapshot.rows[:2]),
        [2.0, 1.0],
    )

    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )
    run = analysis["run_metrics"][0]
    group = analysis["groups"][0]

    assert run["valid_company_count"] == 2
    assert run["outcome_coverage_pct"] == pytest.approx(2 / 900 * 100)
    assert run["score_return_spearman_ic"] == pytest.approx(1.0)
    assert run["analysis_eligible"] is False
    assert run["metric_scope"] == "descriptive_partial"
    assert "outcome coverage 0.2% is below 70%" in run[
        "analysis_ineligibility_reasons"
    ]
    assert run["status_counts"]["symbol_unresolved"] == 898
    assert group["due_run_count"] == 1
    assert group["evaluated_run_count"] == 0
    assert group["partial_run_count"] == 1
    assert group["score_ic"]["mean"] is None
    assert group["bucket_schemes"] == []


def test_artificial_perfect_partial_ic_is_descriptive_until_coverage_is_sufficient():
    snapshot = _snapshot(100)
    partial_rows = list(snapshot.rows[:10])
    partial_store = _partially_priced_store(
        snapshot,
        partial_rows,
        [float(10 - index) for index in range(10)],
    )

    partial = build_performance_v2_analysis(
        (snapshot,), (partial_store,), generated_at=_timestamp(20)
    )
    partial_run = partial["run_metrics"][0]
    partial_group = partial["groups"][0]

    assert [row.ticker for row in partial_rows] == sorted(
        row.ticker for row in partial_rows
    )
    assert partial_run["score_return_spearman_ic"] == pytest.approx(1.0)
    assert partial_run["analysis_eligible"] is False
    assert partial_run["metric_scope"] == "descriptive_partial"
    assert partial_run["buckets"]
    assert partial_group["score_ic"]["mean"] is None
    assert partial_group["bucket_schemes"] == []
    assert partial_group["evaluated_run_count"] == 0
    assert partial_group["due_run_count"] == 1
    assert partial_group["partial_run_count"] == 1

    eligible_rows = list(snapshot.rows[:70])
    eligible_store = _partially_priced_store(
        snapshot,
        eligible_rows,
        [float(70 - index) for index in range(70)],
    )
    eligible = build_performance_v2_analysis(
        (snapshot,), (eligible_store,), generated_at=_timestamp(20)
    )

    assert eligible["run_metrics"][0]["analysis_eligible"] is True
    assert eligible["groups"][0]["score_ic"]["mean"] == pytest.approx(1.0)
    assert eligible["groups"][0]["evaluated_run_count"] == 1
    assert eligible["groups"][0]["bucket_schemes"]


def test_country_partial_ic_requires_country_level_coverage_and_sample():
    snapshot = _snapshot(100, countries=("SE", "FI"))
    swedish_rows = [row for row in snapshot.rows if row.country == "SE"]
    finnish_rows = [row for row in snapshot.rows if row.country == "FI"][:2]
    priced_rows = sorted(swedish_rows + finnish_rows, key=lambda row: row.rank)
    store = _partially_priced_store(
        snapshot,
        priced_rows,
        [float(len(priced_rows) - index) for index in range(len(priced_rows))],
    )

    analysis = build_performance_v2_analysis(
        (snapshot,),
        (store,),
        generated_at=_timestamp(20),
        eligibility_criteria=AnalysisEligibilityCriteria(50.0, 50),
    )
    run_countries = {
        row["country"]: row for row in analysis["run_metrics"][0]["country_metrics"]
    }
    group_countries = {
        row["country"]: row for row in analysis["groups"][0]["countries"]
    }

    assert run_countries["FI"]["score_return_spearman_ic"] is not None
    assert run_countries["FI"]["analysis_eligible"] is False
    assert run_countries["FI"]["valid_company_count"] == 2
    assert group_countries["FI"]["analysis_eligible_run_count"] == 0
    assert group_countries["FI"]["score_ic"]["mean"] is None
    assert group_countries["SE"]["analysis_eligible_run_count"] == 1


def test_sufficiently_covered_sweden_and_finland_contribute_to_country_aggregates():
    snapshot = _snapshot(100, countries=("SE", "FI"))
    priced_rows = sorted(
        [row for row in snapshot.rows if row.country == "SE"][:35]
        + [row for row in snapshot.rows if row.country == "FI"][:35],
        key=lambda row: row.rank,
    )
    store = _partially_priced_store(
        snapshot,
        priced_rows,
        [float(len(priced_rows) - index) for index in range(len(priced_rows))],
    )

    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )
    countries = {row["country"]: row for row in analysis["groups"][0]["countries"]}

    assert analysis["run_metrics"][0]["analysis_eligible"] is True
    assert set(countries) == {"SE", "FI"}
    assert all(row["analysis_eligible_run_count"] == 1 for row in countries.values())
    assert all(row["score_ic"]["mean"] is not None for row in countries.values())
    assert all(row["observations"] == 35 for row in countries.values())


def test_markdown_makes_partial_coverage_and_absent_headline_ic_explicit():
    snapshot = _snapshot(100)
    store = _partially_priced_store(
        snapshot,
        list(snapshot.rows[:10]),
        [float(10 - index) for index in range(10)],
    )
    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )

    markdown = render_performance_v2_markdown(analysis)

    assert "| Evaluations | Due | Eligible | Partial |" in markdown
    assert "No sufficiently covered evaluation dates are available yet" in markdown
    assert "No eligible-run bucket analysis is available" in markdown
    assert "| 1 | 1 | 0 | 1 |" in markdown
    assert "| n/a | n/a | n/a | n/a | n/a |" in markdown
    assert "Required coverage" in markdown
    assert "systematically related to symbol resolution" in markdown


def test_missing_outcome_diagnostics_cover_country_segment_and_rank_bucket():
    snapshot = _snapshot(10, countries=("SE", "FI"))
    retrieved_at = _timestamp(12, 18)
    provider = FixtureHistoricalPriceProvider(
        {}, unresolved=[row.company_id for row in snapshot.rows]
    )
    store = refresh_evaluation_outcomes(
        snapshot, provider, retrieved_at=retrieved_at, horizons=ONE_SESSION
    )

    analysis = build_performance_v2_analysis(
        (snapshot,), (store,), generated_at=_timestamp(20)
    )

    assert analysis["missingness"]["by_country"]
    assert analysis["missingness"]["by_segment"]
    assert analysis["missingness"]["by_rank_decile"]
    assert all(
        row["status_counts"].get("symbol_unresolved")
        for row in analysis["missingness"]["by_country"]
    )


def test_fixture_cli_outcomes_and_analysis_are_fully_offline(tmp_path):
    snapshot = _snapshot(2)
    evaluation_root = tmp_path / "evaluations"
    outcome_root = tmp_path / "outcomes"
    analysis_root = tmp_path / "analysis"
    save_evaluation_snapshot(evaluation_root, snapshot)
    retrieved_at = datetime(2027, 9, 1, 18, tzinfo=UTC)
    histories = {}
    for row in snapshot.rows:
        market = market_for_country(row.country)
        entry = first_session_closing_after(snapshot.decision_at, market).day
        sessions = [entry]
        for count in (20, 60, 126, 252):
            sessions.append(advance_market_sessions(entry, count, market).day)
        histories[row.company_id] = [
            {
                "symbol": f"{row.ticker}.ST",
                "market": market,
                "session_date": session.isoformat(),
                "close": 100.0 + index,
                "adjusted_close": 100.0 + index,
                "currency": "SEK",
                "retrieved_at": retrieved_at.isoformat(),
            }
            for index, session in enumerate(sessions)
        ]
    fixture = tmp_path / "prices.json"
    fixture.write_text(json.dumps({"histories": histories}))

    outcome_result = RUNNER.invoke(
        app,
        [
            "evaluate",
            "outcomes",
            "--evaluation-root",
            str(evaluation_root),
            "--outcome-root",
            str(outcome_root),
            "--price-provider",
            "fixture",
            "--price-fixture",
            str(fixture),
            "--price-cache",
            str(tmp_path / "market-price-cache.json"),
            "--retrieved-at",
            retrieved_at.isoformat(),
        ],
    )
    assert outcome_result.exit_code == 0, outcome_result.output
    outcome_diagnostics = json.loads(outcome_result.output)
    assert outcome_diagnostics["provider_calls_executed"] == 2
    assert outcome_diagnostics["api_budget"] == 20
    assert outcome_diagnostics["work_deferred_by_budget"] == 0
    assert outcome_diagnostics["cache_coverage"]["observations"] == 10

    analysis_result = RUNNER.invoke(
        app,
        [
            "evaluate",
            "analyze",
            "--evaluation-root",
            str(evaluation_root),
            "--outcome-root",
            str(outcome_root),
            "--output-json",
            str(analysis_root / "performance-v2.json"),
            "--output-markdown",
            str(analysis_root / "performance-v2.md"),
            "--generated-at",
            retrieved_at.isoformat(),
        ],
    )

    assert analysis_result.exit_code == 0, analysis_result.output
    payload = json.loads((analysis_root / "performance-v2.json").read_text())
    markdown = (analysis_root / "performance-v2.md").read_text()
    assert len(payload["groups"]) == 4
    assert all(group["scoring_model_version"] == "nordic-ranking-v1" for group in payload["groups"])
    assert "Insufficient history for reliable inference" in markdown
    assert "Gross adjusted-close returns" in markdown


def _observations_for_snapshots(
    snapshots: tuple[EvaluationSnapshot, ...],
    *,
    retrieved_at: datetime,
) -> dict[str, tuple[HistoricalPriceObservation, ...]]:
    sessions_by_company: dict[str, set[date]] = {}
    rows_by_company: dict[str, EvaluationCompanyRow] = {}
    for snapshot in snapshots:
        definitions = DEFAULT_STRATEGY_HORIZONS[snapshot.strategy]
        for row in snapshot.rows:
            rows_by_company[row.company_id] = row
            market = market_for_country(row.country)
            entry = first_session_closing_after(snapshot.decision_at, market).day
            sessions = sessions_by_company.setdefault(row.company_id, set())
            sessions.add(entry)
            sessions.update(
                advance_market_sessions(entry, definition.sessions, market).day
                for definition in definitions
            )
    return {
        company_id: tuple(
            _observation(
                rows_by_company[company_id],
                session,
                100.0
                + int(rows_by_company[company_id].ticker[1:])
                + (session.toordinal() % 100) / 100.0,
                retrieved_at=retrieved_at,
            )
            for session in sorted(sessions)
        )
        for company_id, sessions in sessions_by_company.items()
    }


def _save_snapshots(root: Path, snapshots: tuple[EvaluationSnapshot, ...]) -> None:
    for snapshot in snapshots:
        save_evaluation_snapshot(root, snapshot)


def test_market_price_cache_round_trip_and_revision_audit(tmp_path):
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    session = first_session_closing_after(
        snapshot.decision_at, market_for_country(row.country)
    ).day
    first = _observation(row, session, 100.0, retrieved_at=_timestamp(12, 18))
    same_adjusted = _observation(
        row,
        session,
        100.0,
        close=101.0,
        retrieved_at=_timestamp(13, 12),
    )
    revised = _observation(row, session, 50.0, retrieved_at=_timestamp(13, 18))
    path = tmp_path / "market-price-cache.json"
    cache = FileHistoricalPriceCache(path)

    stored = cache.store(row.company_id, (first,))
    reused = cache.store(row.company_id, (same_adjusted,))
    revision = cache.store(row.company_id, (revised,))
    restored = FileHistoricalPriceCache(path)

    assert stored.observations_stored == 1
    assert reused.observations_reused == 1
    assert reused.revisions_detected == 0
    assert revision.revisions_detected == 1
    assert restored.get_observation(
        row.company_id,
        provider="fixture",
        market="stockholm",
        session_date=session,
        symbol=first.symbol,
    ) == first
    assert restored.revisions[0].cached_adjusted_close == 100.0
    assert restored.revisions[0].observed_adjusted_close == 50.0
    assert restored.coverage().observations == 1
    assert restored.coverage().revisions == 1


def test_market_price_cache_rejects_non_adjusted_persisted_rows(tmp_path):
    path = tmp_path / "market-price-cache.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "price_type": ADJUSTED_PRICE_TYPE,
                "observations": [
                    {
                        "schema_version": 1,
                        "record_id": "invalid",
                        "company_id": "isin:SE0000000000",
                        "provider": "fixture",
                        "provider_symbol": "AAA.ST",
                        "market": "stockholm",
                        "session_date": "2026-08-10",
                        "close": 100.0,
                        "adjusted_close": 100.0,
                        "currency": "SEK",
                        "retrieved_at": "2026-08-10T18:00:00Z",
                        "price_type": ADJUSTED_PRICE_TYPE,
                        "is_adjusted": False,
                    }
                ],
                "revisions": [],
            }
        )
    )

    with pytest.raises(ValueError, match="adjusted closes only"):
        FileHistoricalPriceCache(path)


def test_complete_cache_hit_makes_zero_provider_calls(tmp_path):
    snapshot = _snapshot(1)
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    cache.store(snapshot.rows[0].company_id, histories[snapshot.rows[0].company_id])
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, (snapshot,))
    provider = FixtureHistoricalPriceProvider({})

    summary = refresh_outcome_store(
        evaluation_root,
        tmp_path / "outcomes",
        provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=20,
    )

    assert summary.provider_calls_executed == 0
    assert summary.cache_hits == 5
    assert summary.cache_misses == 0
    assert summary.priced == 4
    assert provider.api_call_count == 0


def test_partial_cache_fetches_only_smallest_missing_range(tmp_path):
    snapshot = _snapshot(1)
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    company_id = snapshot.rows[0].company_id
    rows = histories[company_id]
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    cache.store(company_id, rows[:-1])
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, (snapshot,))
    provider = FixtureHistoricalPriceProvider(histories)

    summary = refresh_outcome_store(
        evaluation_root,
        tmp_path / "outcomes",
        provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=20,
    )

    assert summary.cache_hits == 4
    assert summary.cache_misses == 1
    assert provider.requests == [(company_id, rows[-1].session_date, rows[-1].session_date, rows[0].symbol)]
    assert summary.priced == 4


def test_global_plan_deduplicates_same_security_across_evaluation_runs(tmp_path):
    snapshots = (
        _snapshot(1, decision_at=datetime(2026, 8, 10, 8, tzinfo=UTC)),
        _snapshot(1, decision_at=datetime(2026, 8, 11, 8, tzinfo=UTC)),
    )
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots(snapshots, retrieved_at=retrieved_at)
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, snapshots)
    provider = FixtureHistoricalPriceProvider(histories)

    summary = refresh_outcome_store(
        evaluation_root,
        tmp_path / "outcomes",
        provider,
        retrieved_at=retrieved_at,
        price_cache=FileHistoricalPriceCache(tmp_path / "prices.json"),
        max_price_api_calls=20,
    )

    assert summary.evaluation_runs == 2
    assert summary.securities_requiring_prices == 1
    assert summary.provider_calls_executed == 1
    assert summary.priced == 8


def test_global_plan_deduplicates_across_trading_and_long_term(tmp_path):
    decision = datetime(2026, 8, 10, 8, tzinfo=UTC)
    snapshots = (
        _snapshot(1, strategy="trading", decision_at=decision),
        _snapshot(1, strategy="long-term", decision_at=decision),
    )
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots(snapshots, retrieved_at=retrieved_at)
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, snapshots)
    provider = FixtureHistoricalPriceProvider(histories)

    summary = refresh_outcome_store(
        evaluation_root,
        tmp_path / "outcomes",
        provider,
        retrieved_at=retrieved_at,
        price_cache=FileHistoricalPriceCache(tmp_path / "prices.json"),
        max_price_api_calls=20,
    )

    assert summary.evaluation_runs == 2
    assert summary.provider_calls_executed == 1
    assert summary.priced == 8
    assert len(provider.requests) == 1


def test_api_budget_defers_deterministically_and_backlog_remains_refreshable(tmp_path):
    snapshot = _snapshot(3)
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    evaluation_root = tmp_path / "evaluations"
    outcome_root = tmp_path / "outcomes"
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    _save_snapshots(evaluation_root, (snapshot,))
    first_provider = FixtureHistoricalPriceProvider(histories)

    first = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        first_provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=1,
    )

    assert first.provider_calls_executed == 1
    assert first.work_deferred_by_budget == 2
    assert first.deferred_security_ids == tuple(
        row.company_id for row in snapshot.rows[1:]
    )
    assert [item.company_id for item in first.fetch_plan] == [
        row.company_id for row in snapshot.rows
    ]
    assert first.fetch_plan[0].deferred_by_budget is False
    assert all(item.deferred_by_budget for item in first.fetch_plan[1:])
    assert first.provider_errors == 0

    second_provider = FixtureHistoricalPriceProvider(histories)
    second = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        second_provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=2,
    )

    assert second.provider_calls_executed == 2
    assert second.work_deferred_by_budget == 0
    assert second.priced == 12


def test_eodhd_multiple_symbol_candidates_cannot_exceed_api_budget(tmp_path):
    original = _snapshot(1)
    row = replace(original.rows[0], ticker="ABC-B")
    snapshot = replace(original, rows=(row,))
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    market = market_for_country(row.country)
    entry = first_session_closing_after(snapshot.decision_at, market).day
    sessions = [entry]
    sessions.extend(
        advance_market_sessions(entry, definition.sessions, market).day
        for definition in DEFAULT_STRATEGY_HORIZONS[snapshot.strategy]
    )
    payload = json.dumps(
        [
            {
                "date": session.isoformat(),
                "close": 100.0 + index,
                "adjusted_close": 100.0 + index,
            }
            for index, session in enumerate(sessions)
        ]
    )
    evaluation_root = tmp_path / "evaluations"
    outcome_root = tmp_path / "outcomes"
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    _save_snapshots(evaluation_root, (snapshot,))
    deferred_provider = EodhdHistoricalPriceProvider(
        "secret", fetcher=lambda url: payload
    )

    deferred = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        deferred_provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=1,
    )

    assert deferred.provider_calls_executed == 0
    assert deferred.provider_calls_planned == 0
    assert deferred.work_deferred_by_budget == 1
    assert deferred.fetch_plan[0].estimated_api_calls == 2

    executed_provider = EodhdHistoricalPriceProvider(
        "secret", fetcher=lambda url: payload
    )
    executed = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        executed_provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=2,
    )

    assert executed.provider_calls_planned == 2
    assert executed.provider_calls_executed == 1
    assert executed.provider_calls_executed <= executed.api_budget
    assert executed.priced == 4


def test_provider_failure_preserves_cached_observations(tmp_path):
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    cache.store(row.company_id, histories[row.company_id][:1])
    original_records = cache.records
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, (snapshot,))
    provider = FixtureHistoricalPriceProvider(
        {}, provider_errors={row.company_id: "quota unavailable"}
    )

    summary = refresh_outcome_store(
        evaluation_root,
        tmp_path / "outcomes",
        provider,
        retrieved_at=retrieved_at,
        price_cache=cache,
        max_price_api_calls=1,
    )

    assert summary.provider_errors == 1
    assert cache.records == original_records
    assert summary.observations_stored == 0
    assert summary.oldest_unresolved_evaluation_date == snapshot.report_date


def test_cached_provider_revision_preserves_established_entry(tmp_path):
    snapshot = _snapshot(1)
    row = snapshot.rows[0]
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    entry = histories[row.company_id][0]
    existing = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider({row.company_id: (entry,)}),
        retrieved_at=retrieved_at,
    )
    assert all(outcome.status == "missing_exit" for outcome in existing.outcomes)
    outcome_root = tmp_path / "outcomes"
    save_outcome_set(outcome_store_path(outcome_root, snapshot), existing)
    cache = FileHistoricalPriceCache(tmp_path / "prices.json")
    cache.store(row.company_id, histories[row.company_id])
    revised_entry = _observation(
        row,
        entry.session_date,
        entry.adjusted_close / 2.0,
        retrieved_at=retrieved_at + timedelta(days=1),
    )
    cache.store(row.company_id, (revised_entry,))
    evaluation_root = tmp_path / "evaluations"
    _save_snapshots(evaluation_root, (snapshot,))

    summary = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        FixtureHistoricalPriceProvider({}),
        retrieved_at=retrieved_at + timedelta(days=1),
        price_cache=cache,
        max_price_api_calls=0,
    )
    refreshed = discover_outcome_sets(outcome_root)[0]

    assert summary.provider_calls_executed == 0
    assert all(
        outcome.status == "corporate_action_unsupported"
        for outcome in refreshed.outcomes
    )
    assert all(outcome.entry_price == entry.adjusted_close for outcome in refreshed.outcomes)
    assert all("revised cached adjusted-close" in outcome.detail for outcome in refreshed.outcomes)


def test_cache_loss_changes_calls_but_not_calculated_outcomes(tmp_path):
    snapshot = _snapshot(4, countries=("SE", "FI"))
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots((snapshot,), retrieved_at=retrieved_at)
    naive = refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
    )
    evaluation_root = tmp_path / "evaluations"
    outcome_root = tmp_path / "outcomes"
    _save_snapshots(evaluation_root, (snapshot,))

    refresh_outcome_store(
        evaluation_root,
        outcome_root,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
        price_cache=FileHistoricalPriceCache(tmp_path / "new-cache.json"),
        max_price_api_calls=4,
    )
    cached = discover_outcome_sets(outcome_root)[0]

    assert cached.as_payload() == naive.as_payload()


def test_twenty_overlapping_runs_reduce_two_thousand_calls_to_one_hundred(tmp_path):
    evaluation_days = (10, 11, 12, 13, 14, 17, 18, 19, 20, 21)
    snapshots = tuple(
        _snapshot(
            100,
            strategy=strategy,
            decision_at=datetime(2026, 8, day, 8, tzinfo=UTC),
            countries=("SE", "FI"),
        )
        for day in evaluation_days
        for strategy in ("trading", "long-term")
    )
    retrieved_at = datetime(2028, 1, 1, 18, tzinfo=UTC)
    histories = _observations_for_snapshots(snapshots, retrieved_at=retrieved_at)
    naive_provider = FixtureHistoricalPriceProvider(histories)
    naive = {
        snapshot.run_id: refresh_evaluation_outcomes(
            snapshot,
            naive_provider,
            retrieved_at=retrieved_at,
        ).as_payload()
        for snapshot in snapshots
    }
    evaluation_root = tmp_path / "evaluations"
    outcome_root = tmp_path / "outcomes"
    _save_snapshots(evaluation_root, snapshots)
    cached_provider = FixtureHistoricalPriceProvider(histories)

    summary = refresh_outcome_store(
        evaluation_root,
        outcome_root,
        cached_provider,
        retrieved_at=retrieved_at,
        price_cache=FileHistoricalPriceCache(tmp_path / "prices.json"),
        max_price_api_calls=100,
    )
    cached = {
        store.evaluation_run_id: store.as_payload()
        for store in discover_outcome_sets(outcome_root)
    }

    assert naive_provider.api_call_count == 2_000
    assert summary.provider_calls_executed == 100
    assert summary.provider_calls_executed <= summary.api_budget
    assert summary.work_deferred_by_budget == 0
    assert cached == naive
