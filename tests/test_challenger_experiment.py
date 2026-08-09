import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investmentagent.cli import app
from investmentagent.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EvaluationSnapshot,
    build_evaluation_snapshot,
    evaluation_run_id,
)
from investmentagent.evaluation_analysis import build_performance_v2_analysis
from investmentagent.evaluation_outcomes import (
    EvaluationOutcomeSet,
    HorizonDefinition,
    refresh_evaluation_outcomes,
)
from investmentagent.experiments import (
    EXPERIMENT_SCHEMA_VERSION,
    MAX_RELATIVE_VALUATION_ADJUSTMENT,
    RELATIVE_VALUATION_EXPERIMENT_ID,
    RELATIVE_VALUATION_V1,
    ChallengerExperimentDefinition,
    build_challenger_experiment_snapshot,
    load_experiment_snapshot,
    save_experiment_snapshot,
    serialize_experiment_snapshot,
)
from investmentagent.long_term_quality import assess_long_term_gate
from investmentagent.market_calendar import (
    advance_market_sessions,
    first_session_closing_after,
    market_for_country,
)
from investmentagent.market_prices import (
    FixtureHistoricalPriceProvider,
    HistoricalPriceObservation,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    FinancialSnapshot,
    ListingSegment,
    ScoreBreakdown,
    SourceCheck,
    WatchlistItem,
)
from investmentagent.reports import (
    WatchlistBuildDiagnostics,
    WatchlistBuildResult,
    build_watchlist_result,
)
from investmentagent.scoring import SCORING_MODEL_VERSION


UTC = timezone.utc
RUNNER = CliRunner()
ONE_SESSION = (HorizonDefinition("1_session", 1),)


class _Provider:
    def __init__(self, research):
        self.research = tuple(research)
        self.research_calls = 0

    def list_companies(self, countries, include_first_north):
        wanted = {country.upper() for country in countries}
        return [item.company for item in self.research if item.company.country in wanted]

    def get_company_research(self, company):
        self.research_calls += 1
        return next(item for item in self.research if item.company == company)

    def get_research(self, ticker):
        self.research_calls += 1
        return next(item for item in self.research if item.company.ticker == ticker)

    def source_checks(self):
        return [SourceCheck("fixture", "ok", f"{len(self.research)} companies")]


def _research(
    index: int,
    *,
    ticker: str | None = None,
    country: str = "SE",
    pe_ratio: float | None = 10.0,
    price_to_book: float | None = None,
    ev_to_ebit: float | None = None,
    strong: bool = True,
) -> CompanyResearch:
    company = Company(
        name=f"Company {index:03d} AB",
        ticker=ticker or f"C{index:03d}",
        country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
        segment=ListingSegment.MAIN_MARKET,
        isin=f"{country}{index:010d}",
        sector="Software",
        market_cap_eur_m=300.0,
        currency="SEK" if country == "SE" else "EUR",
        business_description=("Business software company." if strong else None),
    )
    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        ev_to_ebit=ev_to_ebit,
        net_cash_eur_m=20.0 if strong else None,
        debt_to_equity=0.2 if strong else None,
        revenue_growth_pct=10.0 if strong else None,
        operating_margin_pct=12.0 if strong else None,
        average_daily_value_eur=200_000.0 if strong else None,
        data_quality=DataQuality.GOOD if strong else DataQuality.THIN,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        data_quality=financials.data_quality,
    )


def _score(total: float) -> ScoreBreakdown:
    return ScoreBreakdown(
        value=total,
        discovery=0.0,
        catalyst=0.0,
        risk_penalty=0.0,
        data_quality_penalty=0.0,
        total=total,
    )


def _manual_run(
    research: list[CompanyResearch],
    champion_scores: list[float],
    *,
    decision_at: datetime = datetime(2026, 8, 10, 8, tzinfo=UTC),
    public_limit: int = 10,
    model_version: str = SCORING_MODEL_VERSION,
) -> tuple[_Provider, WatchlistBuildResult, EvaluationSnapshot]:
    items = tuple(
        WatchlistItem(rank=index, research=item, score=_score(score))
        for index, (item, score) in enumerate(
            zip(research, champion_scores, strict=True), start=1
        )
    )
    counts = {}
    for item in research:
        counts[item.company.country] = counts.get(item.company.country, 0) + 1
    result = WatchlistBuildResult(
        ranked_items=items,
        selected_items=items[: min(public_limit, len(items))],
        diagnostics=WatchlistBuildDiagnostics(
            source_universe_size=len(items),
            filtered_universe_size=len(items),
            successfully_scored_universe_size=len(items),
            final_ranked_universe_size=len(items),
            public_selection_size=min(public_limit, len(items)),
            source_country_counts=counts,
            source_segment_counts={},
            exclusion_counts={},
        ),
    )
    provider = _Provider(research)
    countries = tuple(sorted(counts))
    configuration = {"provider": "fixture", "public_limit": public_limit}
    snapshot = build_evaluation_snapshot(
        result,
        provider=provider,
        strategy="long-term",
        decision_at=decision_at,
        report_date=decision_at.date(),
        countries=countries,
        configuration=configuration,
        source_checks=provider.source_checks(),
    )
    if model_version != SCORING_MODEL_VERSION:
        run_id = evaluation_run_id(
            strategy="long-term",
            decision_at=decision_at,
            report_date=decision_at.date(),
            countries=countries,
            scoring_model_version=model_version,
            configuration=configuration,
        )
        snapshot = EvaluationSnapshot(
            schema_version=EVALUATION_SCHEMA_VERSION,
            run_id=run_id,
            strategy="long-term",
            decision_at=decision_at,
            report_date=decision_at.date(),
            universe_size=snapshot.universe_size,
            countries=countries,
            scoring_model_version=model_version,
            configuration=configuration,
            diagnostics=snapshot.diagnostics,
            rows=snapshot.rows,
        )
    return provider, result, snapshot


def _experiment(
    research: list[CompanyResearch],
    scores: list[float],
    **kwargs,
):
    provider, result, snapshot = _manual_run(research, scores, **kwargs)
    definition = RELATIVE_VALUATION_V1
    if snapshot.scoring_model_version != definition.champion_scoring_model_version:
        definition = replace(
            definition,
            champion_scoring_model_version=snapshot.scoring_model_version,
        )
    experiment = build_challenger_experiment_snapshot(
        result, snapshot, definition=definition
    )
    return provider, result, snapshot, experiment


def _priced_outcomes(
    snapshot: EvaluationSnapshot,
    returns_pct: list[float],
    *,
    missing_company_ids=(),
) -> EvaluationOutcomeSet:
    retrieved_at = snapshot.decision_at + timedelta(days=20)
    missing = set(missing_company_ids)
    histories = {}
    for row, forward_return in zip(snapshot.rows, returns_pct, strict=True):
        if row.company_id in missing:
            continue
        market = market_for_country(row.country)
        entry = first_session_closing_after(snapshot.decision_at, market).day
        exit_day = advance_market_sessions(entry, 1, market).day
        symbol = f"{row.ticker}.{'ST' if row.country == 'SE' else 'HE'}"
        currency = "SEK" if row.country == "SE" else "EUR"
        histories[row.company_id] = (
            HistoricalPriceObservation(
                "fixture", symbol, market, entry, 100.0, 100.0, currency, retrieved_at
            ),
            HistoricalPriceObservation(
                "fixture",
                symbol,
                market,
                exit_day,
                100.0 + forward_return,
                100.0 + forward_return,
                currency,
                retrieved_at,
            ),
        )
    return refresh_evaluation_outcomes(
        snapshot,
        FixtureHistoricalPriceProvider(histories),
        retrieved_at=retrieved_at,
        horizons=ONE_SESSION,
    )


def test_experiment_does_not_modify_champion_or_public_selection():
    research = [_research(index, pe_ratio=8.0 + index) for index in range(6)]
    provider = _Provider(research)
    result = build_watchlist_result(
        provider,
        countries=("SE",),
        limit=3,
        include_first_north=True,
        strategy="long-term",
    )
    snapshot = build_evaluation_snapshot(
        result,
        provider=provider,
        strategy="long-term",
        decision_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
        report_date=date(2026, 8, 10),
        countries=("SE",),
        configuration={"provider": "fixture"},
        source_checks=provider.source_checks(),
    )
    champion_before = [(item.rank, item.score.total) for item in result.ranked_items]
    public_before = [item.research.company.ticker for item in result.selected_items]
    calls_before = provider.research_calls

    experiment = build_challenger_experiment_snapshot(result, snapshot)

    assert [(item.rank, item.score.total) for item in result.ranked_items] == champion_before
    assert [item.research.company.ticker for item in result.selected_items] == public_before
    assert [(row.champion_rank, row.champion_score) for row in experiment.rows] == champion_before
    assert provider.research_calls == calls_before
    assert SCORING_MODEL_VERSION == "nordic-ranking-v1"


def test_lower_relative_valuation_gets_better_factor_and_can_reorder_same_gate():
    research = [
        _research(0, ticker="EXPENSIVE", pe_ratio=30.0),
        _research(1, ticker="CHEAP", pe_ratio=5.0),
        _research(2, ticker="MIDDLE", pe_ratio=15.0),
    ]
    _, _, _, experiment = _experiment(research, [10.0, 9.0, 0.0])
    rows = {row.ticker: row for row in experiment.rows}

    assert rows["CHEAP"].challenger_factor_score > rows["MIDDLE"].challenger_factor_score
    assert rows["MIDDLE"].challenger_factor_score > rows["EXPENSIVE"].challenger_factor_score
    assert rows["CHEAP"].challenger_rank < rows["EXPENSIVE"].challenger_rank
    assert rows["CHEAP"].rank_delta > 0


@pytest.mark.parametrize("invalid_value", [-5.0, 0.0, None])
def test_non_positive_or_missing_valuation_is_neutral_not_cheap(invalid_value):
    research = [
        _research(0, pe_ratio=5.0),
        _research(1, pe_ratio=10.0),
        _research(2, pe_ratio=15.0),
        _research(3, pe_ratio=invalid_value),
    ]
    _, _, _, experiment = _experiment(research, [4.0, 3.0, 2.0, 1.0])
    invalid = experiment.rows[3]

    assert invalid.challenger_factor_score is None
    assert invalid.challenger_adjustment == 0.0
    assert invalid.usable_metric_count == 0
    assert invalid.unavailable_reason_by_metric["pe_ratio"] == "missing_or_non_positive"


def test_country_relative_normalization_compares_each_market_with_itself():
    research = [
        *[_research(index, country="SE", pe_ratio=10.0 + index) for index in range(5)],
        *[
            _research(100 + index, country="FI", pe_ratio=20.0 + index)
            for index in range(5)
        ],
    ]
    _, _, _, experiment = _experiment(research, list(reversed(range(10))))
    rows = {row.ticker: row for row in experiment.rows}

    assert rows["C000"].challenger_factor_score == pytest.approx(1.0)
    assert rows["C100"].challenger_factor_score == pytest.approx(1.0)
    assert rows["C000"].normalization_scope_by_metric["pe_ratio"] == "country"
    assert rows["C100"].normalization_scope_by_metric["pe_ratio"] == "country"
    assert experiment.diagnostics["companies_with_country_normalization"] == 10


def test_small_country_samples_fall_back_to_full_universe_deterministically():
    research = [
        _research(0, country="SE", pe_ratio=5.0),
        _research(1, country="SE", pe_ratio=10.0),
        _research(2, country="FI", pe_ratio=15.0),
        _research(3, country="FI", pe_ratio=20.0),
    ]
    _, _, _, experiment = _experiment(research, [4.0, 3.0, 2.0, 1.0])

    assert all(
        row.normalization_scope_by_metric["pe_ratio"] == "universe_fallback"
        for row in experiment.rows
    )
    assert experiment.rows[0].challenger_factor_score == pytest.approx(1.0)
    assert experiment.rows[-1].challenger_factor_score == pytest.approx(-1.0)


def test_multiple_metrics_combine_as_deterministic_mean_and_stay_bounded():
    research = [
        _research(0, pe_ratio=5.0, price_to_book=1.0, ev_to_ebit=6.0),
        _research(1, pe_ratio=10.0, price_to_book=2.0, ev_to_ebit=12.0),
        _research(2, pe_ratio=15.0, price_to_book=3.0, ev_to_ebit=18.0),
    ]
    _, _, _, experiment = _experiment(research, [3.0, 2.0, 1.0])

    assert experiment.rows[0].challenger_factor_score == pytest.approx(1.0)
    assert experiment.rows[1].challenger_factor_score == pytest.approx(0.0)
    assert experiment.rows[2].challenger_factor_score == pytest.approx(-1.0)
    assert all(
        abs(row.challenger_adjustment) <= MAX_RELATIVE_VALUATION_ADJUSTMENT
        for row in experiment.rows
    )
    assert experiment.diagnostics["companies_by_usable_metric_count"]["3"] == 3


def test_long_term_gate_order_is_preserved_even_when_lower_gate_has_higher_score():
    high_gate = _research(0, ticker="HIGH", pe_ratio=30.0, strong=True)
    low_gate = _research(1, ticker="LOW", pe_ratio=5.0, strong=False)
    another_low = _research(2, ticker="LOWER", pe_ratio=10.0, strong=False)
    assert assess_long_term_gate(high_gate).tier != assess_long_term_gate(low_gate).tier

    _, _, _, experiment = _experiment(
        [high_gate, low_gate, another_low], [0.0, 100.0, 90.0]
    )
    rows = {row.ticker: row for row in experiment.rows}

    assert rows["HIGH"].challenger_rank == 1
    assert rows["LOW"].challenger_score > rows["HIGH"].challenger_score


def test_challenger_ties_use_ticker_then_company_identity():
    research = [
        _research(0, ticker="BBB", pe_ratio=10.0),
        _research(1, ticker="AAA", pe_ratio=10.0),
        _research(2, ticker="CCC", pe_ratio=10.0),
    ]
    _, _, _, experiment = _experiment(research, [10.0, 10.0, 10.0])
    challenger_order = [
        row.ticker for row in sorted(experiment.rows, key=lambda row: row.challenger_rank)
    ]

    assert challenger_order == ["AAA", "BBB", "CCC"]


def test_experiment_snapshot_round_trip_links_to_production_and_omits_raw_values(tmp_path):
    _, _, snapshot, experiment = _experiment(
        [_research(index, pe_ratio=5.0 + index) for index in range(3)],
        [3.0, 2.0, 1.0],
    )
    path = save_experiment_snapshot(tmp_path / "experiments", experiment)
    restored = load_experiment_snapshot(path)

    assert restored == experiment
    assert restored.schema_version == EXPERIMENT_SCHEMA_VERSION
    assert restored.base_evaluation_run_id == snapshot.run_id
    assert restored.decision_at == snapshot.decision_at
    row_payload = restored.rows[0].as_payload()
    assert "valuation_values" not in row_payload
    assert "financials" not in row_payload
    assert '"pe_ratio": 5' not in serialize_experiment_snapshot(restored)


def test_later_fundamentals_cannot_rewrite_stored_experiment(tmp_path):
    research = [_research(index, pe_ratio=5.0 + index) for index in range(3)]
    _, result, snapshot = _manual_run(research, [3.0, 2.0, 1.0])
    original = build_challenger_experiment_snapshot(result, snapshot)
    root = tmp_path / "experiments"
    path = save_experiment_snapshot(root, original)
    original_bytes = path.read_bytes()
    revised_research = [
        _research(index, pe_ratio=30.0 - index * 5) for index in range(3)
    ]
    _, revised_result, _ = _manual_run(revised_research, [3.0, 2.0, 1.0])
    revised = build_challenger_experiment_snapshot(revised_result, snapshot)

    with pytest.raises(ValueError, match="identity conflict"):
        save_experiment_snapshot(root, revised)
    assert path.read_bytes() == original_bytes


def test_cli_does_not_backfill_when_challenger_was_not_recorded(tmp_path):
    result = RUNNER.invoke(
        app,
        [
            "evaluate",
            "experiments",
            "--experiment-root",
            str(tmp_path / "missing"),
        ],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "challenger not recorded"
    assert not tuple(tmp_path.rglob("*.json"))


def test_fixture_watchlist_report_is_byte_identical_with_shadow_recording():
    with RUNNER.isolated_filesystem():
        common = [
            "watchlist",
            "--provider",
            "fixture",
            "--fundamentals",
            "off",
            "--country",
            "se,fi",
            "--limit",
            "3",
            "--strategy",
            "long-term",
            "--evaluation-report-date",
            "2026-08-10",
            "--evaluation-decision-at",
            "2026-08-10T08:30:00Z",
        ]
        champion = RUNNER.invoke(
            app,
            [
                *common,
                "--evaluation-dir",
                "champion-evaluations",
                "--save",
                "champion.json",
            ],
        )
        shadow = RUNNER.invoke(
            app,
            [
                *common,
                "--evaluation-dir",
                "shadow-evaluations",
                "--experiment-dir",
                "experiments",
                "--save",
                "shadow.json",
            ],
        )

        assert champion.exit_code == 0, champion.output
        assert shadow.exit_code == 0, shadow.output
        assert Path("champion.json").read_bytes() == Path("shadow.json").read_bytes()
        assert len(tuple(Path("experiments").rglob("*.json"))) == 1


def test_challenger_failure_is_visible_without_blocking_public_report(
    monkeypatch,
):
    def fail_experiment(*args, **kwargs):
        raise RuntimeError("sidecar unavailable")

    monkeypatch.setattr(
        "investmentagent.cli.build_challenger_experiment_snapshot",
        fail_experiment,
    )
    with RUNNER.isolated_filesystem():
        result = RUNNER.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "fixture",
                "--fundamentals",
                "off",
                "--country",
                "se,fi",
                "--limit",
                "3",
                "--strategy",
                "long-term",
                "--evaluation-report-date",
                "2026-08-10",
                "--evaluation-decision-at",
                "2026-08-10T08:30:00Z",
                "--evaluation-dir",
                "evaluations",
                "--experiment-dir",
                "experiments",
                "--save",
                "report.json",
            ],
        )

        assert result.exit_code == 0, result.output
        assert Path("report.json").exists()
        assert "challenger experiment error: sidecar unavailable" in result.stderr
        assert not tuple(Path("experiments").rglob("*.json"))


def test_paired_analysis_uses_exact_same_priced_company_sample():
    research = [_research(index, pe_ratio=5.0 + index) for index in range(5)]
    _, _, snapshot, experiment = _experiment(research, [5, 4, 3, 2, 1])
    missing_id = snapshot.rows[-1].company_id
    outcomes = _priced_outcomes(
        snapshot, [5, 4, 3, 2, 1], missing_company_ids=(missing_id,)
    )

    analysis = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        experiment_snapshots=(experiment,),
    )
    paired = analysis["challenger_analysis"]["run_metrics"][0]

    assert paired["paired_company_count"] == 4
    assert missing_id not in paired["paired_company_ids"]
    assert paired["paired_deltas"]["outcome_coverage_pct"] == 0.0
    assert paired["champion"]["score_return_ic"] is not None
    assert paired["challenger"]["score_return_ic"] is not None


def test_challenger_analysis_causes_zero_additional_price_requests():
    research = [_research(index, pe_ratio=5.0 + index) for index in range(4)]
    _, _, snapshot, experiment = _experiment(research, [4, 3, 2, 1])
    retrieved_at = snapshot.decision_at + timedelta(days=20)
    histories = {}
    for row in snapshot.rows:
        market = market_for_country(row.country)
        entry = first_session_closing_after(snapshot.decision_at, market).day
        exit_day = advance_market_sessions(entry, 1, market).day
        symbol = f"{row.ticker}.{'ST' if row.country == 'SE' else 'HE'}"
        currency = "SEK" if row.country == "SE" else "EUR"
        histories[row.company_id] = (
            HistoricalPriceObservation(
                "fixture", symbol, market, entry, 100.0, 100.0, currency, retrieved_at
            ),
            HistoricalPriceObservation(
                "fixture", symbol, market, exit_day, 101.0, 101.0, currency, retrieved_at
            ),
        )
    provider = FixtureHistoricalPriceProvider(histories)
    outcomes = refresh_evaluation_outcomes(
        snapshot,
        provider,
        retrieved_at=retrieved_at,
        horizons=ONE_SESSION,
    )
    calls_before_analysis = provider.api_call_count

    build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=retrieved_at,
        experiment_snapshots=(experiment,),
    )

    assert provider.api_call_count == calls_before_analysis


def _synthetic_case():
    count = 100
    value_orders = [((index * 37) % count) + 1 for index in range(count)]
    research = [
        _research(index, pe_ratio=5.0 + value_orders[index] * 0.2)
        for index in range(count)
    ]
    champion_scores = [100.0 - index * 0.01 for index in range(count)]
    _, result, snapshot, experiment = _experiment(research, champion_scores)
    incremental_returns = [
        (
            0.35 * (count - index)
            + 0.65 * (count + 1 - value_orders[index])
        )
        / 10.0
        for index in range(count)
    ]
    misleading_returns = [(count - index) / 10.0 for index in range(count)]
    return result, snapshot, experiment, incremental_returns, misleading_returns


def test_incremental_relative_value_signal_beats_imperfect_champion():
    result, snapshot, experiment, returns, _ = _synthetic_case()
    public_before = [item.research.company.ticker for item in result.selected_items]
    outcomes = _priced_outcomes(snapshot, returns)

    analysis = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        experiment_snapshots=(experiment,),
    )
    paired = analysis["challenger_analysis"]["run_metrics"][0]

    assert paired["challenger"]["score_return_ic"] > paired["champion"]["score_return_ic"]
    assert paired["challenger"]["rank_return_ic"] > paired["champion"]["final_rank_return_ic"]
    assert paired["paired_deltas"]["score_ic"] > 0
    assert paired["paired_deltas"]["top_decile_minus_universe_pct"] > 0
    assert [item.research.company.ticker for item in result.selected_items] == public_before


def test_misleading_relative_value_signal_loses_to_champion():
    _, snapshot, experiment, _, returns = _synthetic_case()
    outcomes = _priced_outcomes(snapshot, returns)

    analysis = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        experiment_snapshots=(experiment,),
    )
    paired = analysis["challenger_analysis"]["run_metrics"][0]

    assert paired["paired_deltas"]["score_ic"] < 0
    assert paired["paired_deltas"]["rank_ic"] < 0
    assert paired["paired_deltas"]["top_decile_minus_universe_pct"] < 0


def test_rank_churn_and_top_10_overlap_are_reported():
    _, snapshot, experiment, returns, _ = _synthetic_case()
    outcomes = _priced_outcomes(snapshot, returns)
    analysis = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        experiment_snapshots=(experiment,),
    )
    churn = analysis["challenger_analysis"]["run_metrics"][0]["ranking_churn"]

    assert churn["mean_absolute_rank_change"] > 0
    assert 0 <= churn["top_10_overlap_count"] <= 10
    assert 0 <= churn["top_decile_overlap_pct"] <= 100
    assert churn["most_promoted"]
    assert churn["most_demoted"]


def test_challenger_analysis_keeps_champion_model_versions_separate():
    first_research = [_research(index, pe_ratio=5.0 + index) for index in range(4)]
    _, _, first_snapshot, first_experiment = _experiment(
        first_research, [4, 3, 2, 1]
    )
    second_research = [_research(index, pe_ratio=8.0 + index) for index in range(4)]
    _, _, second_snapshot, second_experiment = _experiment(
        second_research,
        [4, 3, 2, 1],
        decision_at=datetime(2026, 8, 11, 8, tzinfo=UTC),
        model_version="nordic-ranking-v2-shadow",
    )
    analysis = build_performance_v2_analysis(
        (first_snapshot, second_snapshot),
        (
            _priced_outcomes(first_snapshot, [4, 3, 2, 1]),
            _priced_outcomes(second_snapshot, [4, 3, 2, 1]),
        ),
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        experiment_snapshots=(first_experiment, second_experiment),
    )

    groups = analysis["challenger_analysis"]["groups"]
    assert len(groups) == 2
    assert {group["champion_scoring_model_version"] for group in groups} == {
        "nordic-ranking-v1",
        "nordic-ranking-v2-shadow",
    }


def test_performance_v2_remains_compatible_without_challenger_snapshot():
    research = [_research(index, pe_ratio=5.0 + index) for index in range(4)]
    _, _, snapshot = _manual_run(research, [4, 3, 2, 1])
    outcomes = _priced_outcomes(snapshot, [4, 3, 2, 1])

    old_shape = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with_experiment_discovery = build_performance_v2_analysis(
        (snapshot,),
        (outcomes,),
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        experiment_snapshots=(),
    )

    assert "challenger_analysis" not in old_shape
    assert old_shape["groups"] == with_experiment_discovery["groups"]
    assert with_experiment_discovery["challenger_analysis"]["run_statuses"][0][
        "status"
    ] == "challenger not recorded"


def test_experiment_definition_and_snapshot_are_versioned():
    assert RELATIVE_VALUATION_V1 == ChallengerExperimentDefinition(
        experiment_id=RELATIVE_VALUATION_EXPERIMENT_ID,
        experiment_version=1,
        name="Continuous Relative Valuation",
        strategy="long-term",
        champion_scoring_model_version="nordic-ranking-v1",
        hypothesis=RELATIVE_VALUATION_V1.hypothesis,
        valuation_metrics=("pe_ratio", "price_to_book", "ev_to_ebit"),
        country_minimum_sample=5,
        universe_minimum_sample=3,
        maximum_adjustment=6.0,
    )
    assert "relatively cheaper" in RELATIVE_VALUATION_V1.hypothesis
