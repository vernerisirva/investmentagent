"""Offline regressions for X-defined membership and the production/shadow selector."""
import hashlib
import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from investmentagent.challenger_analysis import build_challenger_analysis, _aggregate_paired_runs
from investmentagent.decision_membership import (
    ANALYSIS_METHODOLOGY, DecisionCohort, DecisionMembership, recorded_public_portfolio,
)
from investmentagent.evaluation import build_evaluation_snapshot, serialize_evaluation_snapshot
from investmentagent.evaluation_analysis import (
    ANALYSIS_SCHEMA_VERSION, _aggregate_run_metrics, build_performance_v2_analysis,
    save_analysis_json, save_analysis_markdown,
)
from investmentagent.evaluation_outcomes import refresh_evaluation_outcomes
from investmentagent.experiments import (
    RELATIVE_VALUATION_V1, build_challenger_experiment_snapshot,
    load_experiment_snapshot, save_experiment_snapshot, serialize_experiment_snapshot,
)
from investmentagent.market_prices import FixtureHistoricalPriceProvider
from investmentagent.reports import build_watchlist_result
from investmentagent.selection import SELECTION_POLICY_VERSION, SelectionPolicy
from test_challenger_experiment import _Provider, _experiment, _priced_outcomes, _research, _score
from test_evaluation_outcomes import ONE_SESSION, _observation, _snapshot


UTC = timezone.utc
GENERATED = datetime(2026, 9, 1, 18, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("fixed-membership tests must be offline")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def production_case(*, count=20, minima=None, public_limit=10, research=None, scores=None):
    research = research if research is not None else [
        _research(i, country="SE" if i < count - 5 else "FI", pe_ratio=None)
        for i in range(count)
    ]
    scores = scores if scores is not None else [float(100 - i) for i in range(len(research))]
    by_isin = {item.company.isin: score for item, score in zip(research, scores, strict=True)}
    provider = _Provider(research)
    minima = {"FI": 3} if minima is None else minima
    with patch("investmentagent.reports._score_for_strategy", side_effect=lambda item, strategy: _score(by_isin[item.company.isin])):
        result = build_watchlist_result(provider, countries=("SE", "FI"), limit=public_limit,
                                       include_first_north=True, strategy="long-term", min_country_counts=minima)
    snapshot = build_evaluation_snapshot(
        result, provider=provider, strategy="long-term", decision_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
        report_date=datetime(2026, 8, 10).date(), countries=("SE", "FI"),
        configuration={"provider": "fixture", "public_limit": public_limit, "minimum_country_counts": minima},
        source_checks=provider.source_checks(),
    )
    return result, snapshot, build_challenger_experiment_snapshot(result, snapshot)


def analyze(snapshot, missing=(), experiment=None):
    store = _priced_outcomes(snapshot, [float(row.rank) for row in snapshot.rows], missing_company_ids=missing)
    analysis = build_performance_v2_analysis([snapshot], [store], generated_at=GENERATED,
                                            experiment_snapshots=[experiment] if experiment else None)
    return analysis, analysis["run_metrics"][0]


def selected(experiment, side):
    return [row.company_id for row in sorted(experiment.rows, key=lambda row: getattr(row, f"{side}_rank"))
            if getattr(row, f"{side}_selected")]


def test_audit_a_missing_first_thirty_does_not_promote_survivors():
    snapshot = _snapshot(100)
    analysis, metric = analyze(snapshot, [row.company_id for row in snapshot.rows[:30]])
    top = metric["top_vs_universe"]["cohorts"]["top_decile"]
    assert metric["original_universe_size"] == 100
    assert metric["valid_company_count"] == 70
    assert metric["outcome_coverage_pct"] == 70.0
    assert metric["analysis_eligible"]
    assert top["member_ids"] == [row.company_id for row in snapshot.rows[:10]]
    assert (top["priced_count"], top["missing_count"], top["coverage_pct"]) == (0, 10, 0.0)
    assert top["exact_equal_weight_return_pct"] is None
    assert metric["top_vs_universe"]["top_decile_average_return_pct"] is None
    assert metric["top_vs_universe"]["top_decile_minus_bottom_decile_pct"] is None
    assert len(metric["buckets"]) == 10
    assert [row["priced_count"] for row in metric["buckets"]] == [0, 0, 0, 10, 10, 10, 10, 10, 10, 10]
    assert metric["company_benchmarks"][30]["rank_bucket"] == 4
    assert metric["bucket_returns_monotonic"] is None
    assert analysis["groups"][0]["bucket_schemes"][0]["buckets"][0]["mean_return_pct"] is None


@pytest.mark.parametrize("missing_ranks", [(1,), (1, 3, 9), tuple(range(1, 11))])
def test_top_ten_never_backfills_rank_eleven(missing_ranks):
    snapshot = _snapshot(100)
    _, metric = analyze(snapshot, [snapshot.rows[rank - 1].company_id for rank in missing_ranks])
    top = metric["top_vs_universe"]["cohorts"]["top_10"]
    assert top["member_ids"] == [row.company_id for row in snapshot.rows[:10]]
    assert snapshot.rows[10].company_id not in top["member_ids"]
    assert top["priced_count"] == 10 - len(missing_ranks)
    assert top["missing_count"] == len(missing_ranks)
    assert top["coverage_pct"] == (10 - len(missing_ranks)) * 10
    assert top["weight_per_member"] == 0.1
    assert top["exact_equal_weight_return_pct"] is None


@pytest.mark.parametrize("count,buckets,decile", [(1, 1, 1), (9, 1, 1), (10, 2, 1), (24, 2, 3), (25, 5, 3), (49, 5, 5), (50, 10, 5), (101, 10, 11)])
def test_bucket_boundaries_use_original_population(count, buckets, decile):
    snapshot = _snapshot(count)
    membership = DecisionMembership.from_snapshot(snapshot)
    assert len(membership.buckets) == buckets
    assert len(membership.top_decile.company_ids) == decile
    assert len(membership.bottom_decile.company_ids) == decile
    for index, row in enumerate(snapshot.rows):
        assert row.company_id in membership.buckets[index * buckets // count].company_ids


def test_additional_outcomes_do_not_change_any_bucket_or_top_members():
    snapshot = _snapshot(100)
    _, partial = analyze(snapshot, [row.company_id for row in snapshot.rows[:30]])
    _, full = analyze(snapshot)
    assert [row["member_ids"] for row in partial["buckets"]] == [row["member_ids"] for row in full["buckets"]]
    for name in ("top_10", "top_decile", "bottom_decile"):
        assert partial["top_vs_universe"]["cohorts"][name]["member_ids"] == full["top_vs_universe"]["cohorts"][name]["member_ids"]


def test_country_and_gate_cohorts_keep_wholly_missing_members():
    snapshot = _snapshot(100, countries=("SE", "FI"))
    missing = [row.company_id for row in snapshot.rows if row.country == "FI"]
    _, metric = analyze(snapshot, missing)
    finland = next(row for row in metric["country_metrics"] if row["country"] == "FI")
    assert (finland["decision_time_member_count"], finland["priced_count"], finland["missing_count"]) == (50, 0, 50)
    assert finland["coverage_pct"] == 0
    assert finland["equal_weight_return_pct"] is None
    for cohort in metric["long_term_gate_tiers"]:
        expected = [row.company_id for row in snapshot.rows if row.long_term["gate_tier"] == cohort["tier"]]
        assert cohort["member_ids"] == expected
        assert cohort["decision_time_member_count"] == 25
    assert sum(row["priced_count"] == 0 for row in metric["long_term_gate_tiers"]) == 2


def test_partial_ic_uses_pairs_but_eligibility_uses_original_x():
    snapshot = _snapshot(100)
    analysis, metric = analyze(snapshot, [row.company_id for row in snapshot.rows[:31]])
    assert metric["score_return_spearman_ic"] == pytest.approx(-1.0)
    assert metric["valid_company_count"] == 69
    assert metric["universe_cohort"]["decision_time_member_count"] == 100
    assert not metric["analysis_eligible"]
    assert analysis["groups"][0]["score_ic"]["run_count"] == 0


def test_partial_observed_mean_is_not_renormalized_portfolio_return():
    cohort = DecisionCohort(("a", "b"))
    partial = cohort.observe({"a": 20.0})
    assert partial["observed_mean_return_pct"] == 20.0
    assert partial["exact_equal_weight_return_pct"] is None
    assert partial["observed_weight"] == 0.5
    assert partial["return_status"] == "incomplete"
    assert cohort.observe({"a": 20.0, "b": -10.0})["exact_equal_weight_return_pct"] == 5.0
    assert DecisionCohort(()).observe({})["return_status"] == "empty"


def test_audit_b_zero_adjustment_applies_fi_three_exactly():
    result, snapshot, corrected = production_case()
    legacy = build_challenger_experiment_snapshot(result, snapshot, definition=RELATIVE_VALUATION_V1)
    champion = [row.company_id for row in snapshot.rows[:10]]
    legacy_top = [row.company_id for row in sorted(legacy.rows, key=lambda row: row.challenger_rank)[:10]]
    assert legacy_top != champion  # Reproduces the audited defect without altering v1.
    assert all(row.challenger_adjustment == 0.0 for row in corrected.rows)
    assert selected(corrected, "champion") == selected(corrected, "challenger") == champion
    assert sum(row.country == "FI" and row.champion_selected for row in corrected.rows) == 3
    assert sum(row.country == "FI" and row.challenger_selected for row in corrected.rows) == 3
    assert all(row.champion_rank == row.challenger_rank for row in corrected.rows)


def test_gate_tiers_and_country_promoted_prefix_follow_production():
    research = [_research(i, country="SE" if i < 15 else "FI", strong=i < 15, pe_ratio=None) for i in range(20)]
    _, _, experiment = production_case(research=research)
    assert selected(experiment, "champion") == selected(experiment, "challenger")
    assert sum(row.country == "FI" and row.challenger_selected for row in experiment.rows) == 3
    # Production may promote a lower-gate FI member ahead of the unselected high-gate tail.
    assert experiment.rows[9].long_term_gate_tier != experiment.rows[10].long_term_gate_tier


def test_ticker_then_stable_input_ties_match_production_not_company_id():
    research = [_research(9, ticker="SAME", country="SE", pe_ratio=None),
                _research(1, ticker="SAME", country="FI", pe_ratio=None),
                _research(3, ticker="AAA", pe_ratio=None)]
    _, snapshot, experiment = production_case(research=research, scores=[50.0] * 3, minima={}, public_limit=3)
    assert [row.ticker for row in snapshot.rows] == ["AAA", "SAME", "SAME"]
    assert [row.country for row in snapshot.rows] == ["SE", "SE", "FI"]
    assert selected(experiment, "champion") == selected(experiment, "challenger")
    assert [row.selection_input_order for row in experiment.rows] == [3, 1, 2]


def test_zero_adjustment_does_not_round_away_champion_ties():
    research = [_research(0, ticker="ZZZ", pe_ratio=None), _research(1, ticker="AAA", pe_ratio=None)]
    _, _, experiment = production_case(research=research, scores=[50.0000000002, 50.0000000001], minima={}, public_limit=1)
    assert selected(experiment, "champion") == selected(experiment, "challenger")


def test_factor_can_change_selection_only_through_shared_policy():
    research = [_research(i, country="SE" if i < 15 else "FI", pe_ratio=float(100 - i * 4)) for i in range(20)]
    _, _, experiment = production_case(research=research, scores=[50 - i * 0.01 for i in range(20)])
    assert selected(experiment, "champion") != selected(experiment, "challenger")
    assert sum(row.country == "FI" and row.challenger_selected for row in experiment.rows) >= 3
    assert experiment.selection_configuration["version"] == SELECTION_POLICY_VERSION


def test_paired_portfolios_never_replace_missing_members_on_either_side():
    research = [_research(i, country="SE" if i < 95 else "FI", pe_ratio=float(110 - i)) for i in range(100)]
    _, snapshot, experiment = production_case(research=research, scores=[50 - i * 0.01 for i in range(100)])
    missing = {selected(experiment, "champion")[0], selected(experiment, "challenger")[0]}
    before = serialize_experiment_snapshot(experiment)
    analysis, _ = analyze(snapshot, missing, experiment)
    paired = analysis["challenger_analysis"]["run_metrics"][0]
    assert paired["analysis_eligible"]
    for side in ("champion", "challenger"):
        portfolio = paired["portfolios"][side]
        assert portfolio["member_ids"] == selected(experiment, side)
        assert portfolio["decision_time_member_count"] == 10
        assert portfolio["missing_count"] >= 1
        assert portfolio["exact_equal_weight_return_pct"] is None
    assert paired["portfolios"]["exact_equal_weight_return_delta_pct"] is None
    assert analysis["challenger_analysis"]["groups"][0]["portfolio_comparison"]["exact_paired_return_delta_pct"]["run_count"] == 0
    assert serialize_experiment_snapshot(experiment) == before


def test_public_portfolio_is_recorded_prefix_not_survivors():
    _, snapshot, _ = production_case(public_limit=7)
    _, metric = analyze(snapshot, [snapshot.rows[0].company_id])
    portfolio = metric["public_portfolio"]
    assert portfolio["member_ids"] == [row.company_id for row in snapshot.rows[:7]]
    assert portfolio["priced_count"] == 6
    assert portfolio["exact_equal_weight_return_pct"] is None
    assert recorded_public_portfolio(_snapshot(100), {})["membership_status"] == "unavailable"


def test_new_sidecar_round_trip_and_tamper_rejection(tmp_path):
    _, _, experiment = production_case()
    path = save_experiment_snapshot(tmp_path, experiment)
    assert experiment.schema_version == 2
    assert experiment.experiment_id == "relative-valuation-v2"
    assert load_experiment_snapshot(path) == experiment
    assert "relative-valuation-v2" in str(path)
    assert len(experiment.selection_configuration_id) == 64
    with pytest.raises(ValueError, match="selection evidence"):
        replace(experiment, rows=(replace(experiment.rows[0], challenger_selected=False), *experiment.rows[1:]))
    with pytest.raises(ValueError, match="input order"):
        replace(experiment, rows=(replace(experiment.rows[0], selection_input_order=None), *experiment.rows[1:]))


def test_v1_golden_bytes_and_identity_remain_unchanged(tmp_path):
    _, _, _, experiment = _experiment([_research(i, pe_ratio=5.0 + i) for i in range(3)], [3.0, 2.0, 1.0])
    serialized = serialize_experiment_snapshot(experiment)
    # Captured from the unchanged a36e3d4 code tree before this repair.
    assert hashlib.sha256(serialized.encode()).hexdigest() == "fbdb6625abcc6ed1393b50d9ad65c8abd16cf5eefdc13df8430c4642231cde41"
    assert experiment.experiment_run_id == "experiment-c88db0b2025eb1ffd7762663"
    assert load_experiment_snapshot(save_experiment_snapshot(tmp_path, experiment)) == experiment


def test_experiment_versions_are_separate_and_legacy_portfolio_unverified():
    result, snapshot, new = production_case(count=100)
    old = build_challenger_experiment_snapshot(result, snapshot, definition=RELATIVE_VALUATION_V1)
    store = _priced_outcomes(snapshot, [1.0] * 100)
    analysis = build_challenger_analysis([snapshot], [store], [old, new])
    assert {group["experiment_id"] for group in analysis["groups"]} == {"relative-valuation-v1", "relative-valuation-v2"}
    legacy = next(row for row in analysis["run_metrics"] if row["experiment_version"] == 1)
    assert legacy["portfolios"]["challenger"]["membership_status"] == "unavailable"
    assert legacy["portfolios"]["exact_equal_weight_return_delta_pct"] is None


def test_constraint_configuration_identity_separates_paired_aggregates():
    _, snapshot, experiment = production_case(count=100)
    analysis, _ = analyze(snapshot, experiment=experiment)
    metric = analysis["challenger_analysis"]["run_metrics"][0]
    groups = _aggregate_paired_runs([metric, {**metric, "selection_configuration_id": "different-configuration"}])
    assert len(groups) == 2


@pytest.mark.parametrize("kind", ["json", "markdown"])
def test_old_analysis_cannot_be_silently_overwritten(tmp_path, kind):
    analysis, _ = analyze(_snapshot(100))
    path = tmp_path / f"old.{kind}"
    old = '{"schema_version": 1}\n' if kind == "json" else "# Historical analysis\n"
    path.write_text(old)
    writer = save_analysis_json if kind == "json" else save_analysis_markdown
    with pytest.raises(ValueError, match="overwrite"):
        writer(path, analysis)
    assert path.read_text() == old
    current = writer(tmp_path / ANALYSIS_METHODOLOGY / path.name, analysis)
    assert current.exists()
    assert writer(current, analysis) == current


def test_analysis_versions_cannot_be_mixed():
    analysis, metric = analyze(_snapshot(100))
    assert analysis["schema_version"] == ANALYSIS_SCHEMA_VERSION == 3
    assert analysis["analysis_methodology"] == ANALYSIS_METHODOLOGY
    with pytest.raises(ValueError, match="methodology"):
        _aggregate_run_metrics([metric, {**metric, "analysis_methodology": "legacy"}])
    _, snapshot, experiment = production_case(count=100)
    paired = analyze(snapshot, experiment=experiment)[0]["challenger_analysis"]["run_metrics"][0]
    with pytest.raises(ValueError, match="methodology"):
        _aggregate_paired_runs([{**paired, "analysis_methodology": "legacy"}])


def test_revision_cutoff_changes_y_not_x_cohorts_or_selections():
    _, snapshot, experiment = production_case(count=100)
    before = serialize_evaluation_snapshot(snapshot), serialize_experiment_snapshot(experiment)
    early_at = datetime(2026, 8, 12, 18, tzinfo=UTC)
    later_at = early_at + timedelta(days=1)
    def prices(at, missing, value):
        return {row.company_id: [_observation(row, datetime(2026, 8, 10).date(), 100.0, retrieved_at=at),
                                 _observation(row, datetime(2026, 8, 11).date(), value, retrieved_at=at)]
                for row in snapshot.rows if row.rank not in missing}
    first = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(prices(early_at, range(1, 31), 110.0)),
                                       retrieved_at=early_at, horizons=ONE_SESSION)
    revised = refresh_evaluation_outcomes(snapshot, FixtureHistoricalPriceProvider(prices(later_at, (), 120.0)),
                                         retrieved_at=later_at, existing=first, horizons=ONE_SESSION, reprice=True)
    analyses = [build_performance_v2_analysis([snapshot], [revised], generated_at=GENERATED, data_cutoff=cutoff,
                                             experiment_snapshots=[experiment]) for cutoff in (early_at, later_at)]
    early, latest = [analysis["run_metrics"][0] for analysis in analyses]
    assert early["valid_company_count"] == 70 and latest["valid_company_count"] == 100
    assert [row["member_ids"] for row in early["buckets"]] == [row["member_ids"] for row in latest["buckets"]]
    for side in ("champion", "challenger"):
        portfolios = [analysis["challenger_analysis"]["run_metrics"][0]["portfolios"][side] for analysis in analyses]
        assert portfolios[0]["member_ids"] == portfolios[1]["member_ids"]
        assert portfolios[0]["exact_equal_weight_return_pct"] is None
        assert portfolios[1]["exact_equal_weight_return_pct"] == pytest.approx(20.0)
    for analysis in analyses:
        assert analysis["methodology"]["selected_outcomes_hash"] == analysis["challenger_analysis"]["methodology"]["selected_outcomes_hash"]
    assert before == (serialize_evaluation_snapshot(snapshot), serialize_experiment_snapshot(experiment))


def test_factor_coverage_cohorts_include_missing_members():
    _, snapshot, experiment = production_case(count=100)
    analysis, _ = analyze(snapshot, [row.company_id for row in snapshot.rows[:30]], experiment)
    cohort = analysis["challenger_analysis"]["run_metrics"][0]["factor_coverage_outcomes"][0]
    assert (cohort["decision_time_member_count"], cohort["priced_count"], cohort["missing_count"], cohort["coverage_pct"]) == (100, 70, 30, 70.0)


def test_v2_refuses_missing_policy_or_ineligible_x_members():
    result, snapshot, _ = production_case()
    with pytest.raises(ValueError, match="selection evidence"):
        build_challenger_experiment_snapshot(replace(result, selection_policy=None), snapshot)
    ineligible = replace(snapshot, rows=(replace(snapshot.rows[0], eligible_universe_member=False), *snapshot.rows[1:]))
    with pytest.raises(ValueError, match="eligible"):
        build_challenger_experiment_snapshot(result, ineligible)


def test_outcome_identity_cannot_override_x_country_or_rank():
    snapshot = _snapshot(100)
    different_ranks = replace(snapshot, rows=(replace(snapshot.rows[1], rank=1),
                                              replace(snapshot.rows[0], rank=2), *snapshot.rows[2:]))
    corrupt = _priced_outcomes(different_ranks, [1.0] * 100)
    with pytest.raises(ValueError, match="immutable X"):
        build_performance_v2_analysis([snapshot], [corrupt], generated_at=GENERATED)


def test_selection_policy_roundtrip_preserves_constraint_iteration_order():
    policy = SelectionPolicy(10, (("SE", 7), ("FI", 3)))
    assert SelectionPolicy.from_payload(json.loads(json.dumps(policy.as_payload(), sort_keys=True))) == policy
    assert policy.as_payload() != SelectionPolicy(10, (("FI", 3), ("SE", 7))).as_payload()


def test_offline_guard_is_active():
    with pytest.raises(AssertionError, match="offline"):
        socket.create_connection(("example.invalid", 443))


def acceptance_demonstration():
    snapshot = _snapshot(100)
    _, metric = analyze(snapshot, [row.company_id for row in snapshot.rows[:30]])
    result, constrained, corrected = production_case()
    old = build_challenger_experiment_snapshot(result, constrained, definition=RELATIVE_VALUATION_V1)
    old_top = [row.ticker for row in sorted(old.rows, key=lambda row: row.challenger_rank)[:10]]
    by_id = {row.company_id: row.ticker for row in corrected.rows}
    return {
        "case_a": {
            "original_universe": 100, "priced": 70, "coverage_pct": 70.0,
            "old_survivor_top_decile_original_ranks": list(range(31, 38)),
            "fixed_top_decile": metric["top_vs_universe"]["cohorts"]["top_decile"],
            "fixed_top_decile_original_ranks": list(range(1, 11)),
        },
        "case_b": {
            "constraint": {"FI": 3},
            "all_adjustments_zero": all(row.challenger_adjustment == 0 for row in corrected.rows),
            "legacy_challenger": old_top,
            "champion": [by_id[key] for key in selected(corrected, "champion")],
            "corrected_challenger": [by_id[key] for key in selected(corrected, "challenger")],
        },
    }


def test_synthetic_acceptance_demonstration():
    demonstration = acceptance_demonstration()
    assert demonstration["case_a"]["fixed_top_decile"]["priced_count"] == 0
    assert demonstration["case_b"]["legacy_challenger"] != demonstration["case_b"]["champion"]
    assert demonstration["case_b"]["corrected_challenger"] == demonstration["case_b"]["champion"]


if __name__ == "__main__":
    print(json.dumps(acceptance_demonstration(), indent=2, sort_keys=True))
