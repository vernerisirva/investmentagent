"""Frozen X-only nulls; synthetic fixtures never contact a market data provider."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import os
import socket
import statistics
import subprocess
import sys
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from investmentagent import selection
from investmentagent.benchmarks import (
    BENCHMARK_METHODOLOGY, BenchmarkPlan, MIN_ALTERNATIVES, RANDOM_DRAWS,
    benchmark_plan_path, build_benchmark_plan, canonical_hash, load_benchmark_plan,
    matched_pool, portfolio_plan, random_portfolios, random_seed, save_benchmark_plan,
    validate_benchmark_plan,
)
from investmentagent.benchmark_analysis import (
    aggregate_benchmark_runs, analyze_plan, build_benchmark_analysis, cohort_result,
    distribution, percentile, render_benchmark_markdown, weighted_alternatives,
)
from investmentagent.cli import app
from investmentagent.evaluation import (
    evaluation_run_id, load_evaluation_snapshot, save_evaluation_snapshot, serialize_evaluation_snapshot,
)
from investmentagent.evaluation_analysis import (
    analyze_outcome_store, build_performance_v2_analysis, save_analysis_json, save_analysis_markdown,
)
from investmentagent.evaluation_outcomes import serialize_outcome_set
from investmentagent.experiments import serialize_experiment_snapshot
from test_challenger_experiment import _priced_outcomes, _research
from test_evaluation_outcomes import _snapshot
from test_fixed_decision_membership import GENERATED, production_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("benchmark tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(scope="module")
def case():
    return production_case(count=60, research=[
        _research(i, country="SE" if i < 40 else "FI", pe_ratio=None) for i in range(60)])


@pytest.fixture
def plan(case):
    result, snapshot, experiment = case
    return build_benchmark_plan(snapshot, result=result, experiment=experiment)


def observed(snapshot):
    return {row.company_id: float(100 - row.rank) for row in snapshot.rows}


def retag(snapshot, **configuration):
    config = {**snapshot.configuration, **configuration}
    run_id = evaluation_run_id(strategy=snapshot.strategy, decision_at=snapshot.decision_at,
        report_date=snapshot.report_date, countries=snapshot.countries,
        scoring_model_version=snapshot.scoring_model_version, configuration=config)
    return replace(snapshot, configuration=config, run_id=run_id)


def test_same_x_same_thousand_portfolios(case, plan):
    assert RANDOM_DRAWS == len(plan.draws) == 1000
    assert plan == build_benchmark_plan(case[1], result=case[0], experiment=case[2])


def test_reordered_input_does_not_change_random_draws(case, plan):
    policy = selection.SelectionPolicy.from_payload(plan.payload["selection_evidence"]["policy"])
    assert random_portfolios(reversed(case[1].rows), policy, plan.payload["random"]["seed"]) == plan.draws


def test_different_evaluation_changes_seed_and_draws(case, plan):
    policy = selection.SelectionPolicy.from_payload(plan.payload["selection_evidence"]["policy"])
    other = random_seed(case[1].run_id + "-different")
    assert other != plan.payload["random"]["seed"]
    assert random_portfolios(case[1].rows, policy, other) != plan.draws


@pytest.mark.parametrize("hash_seed", ["0", "17", "random"])
def test_process_hash_randomization_cannot_change_draws(hash_seed, case, plan):
    code = (
        "from test_fixed_decision_membership import production_case\n"
        "from test_challenger_experiment import _research\n"
        "from investmentagent.benchmarks import build_benchmark_plan\n"
        "r,x,e=production_case(count=60,research=[_research(i,country='SE' if i<40 else 'FI',pe_ratio=None) for i in range(60)])\n"
        "print(build_benchmark_plan(x,result=r,experiment=e).payload['random']['membership_sha256'])\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH="src:tests"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == plan.payload["random"]["membership_sha256"]


def test_random_reuses_shared_selector(case):
    with patch.object(selection, "rank_and_select", wraps=selection.rank_and_select) as shared:
        plan = build_benchmark_plan(case[1], result=case[0], experiment=case[2])
    assert shared.call_count >= 1001
    assert all(len(draw) == 10 for draw in plan.draws)


@pytest.mark.parametrize("minimum", [0, 1, 3, 5])
def test_country_constraints_and_top_n_are_production_policy(minimum):
    result, snapshot, experiment = production_case(count=30, minima={"FI": minimum})
    plan = build_benchmark_plan(snapshot, result=result, experiment=experiment)
    fi = {row.company_id for row in snapshot.rows if row.country == "FI"}
    assert all(len(draw) == len(result.selected_items) == 10 and len(set(draw) & fi) >= minimum for draw in plan.draws)


def test_soft_gates_remain_priorities_and_country_replacement_still_applies():
    result, snapshot, experiment = production_case(research=[
        _research(i, country="SE" if i < 15 else "FI", strong=i < 15, pe_ratio=None) for i in range(20)])
    plan = build_benchmark_plan(snapshot, result=result, experiment=experiment)
    high = {row.company_id for row in snapshot.rows if row.country == "SE"}
    assert all(len(set(draw) & high) == 7 for draw in plan.draws)
    assert plan.payload["gate_qualified_member_ids"] == plan.payload["opportunity_member_ids"]


@pytest.mark.parametrize("missing", [1, 3, 10, 30, 60])
def test_missing_y_never_redraws_or_replaces(case, plan, missing):
    before = deepcopy(plan.payload), plan.draws
    returns = observed(case[1])
    for row in case[1].rows[:missing]:
        returns.pop(row.company_id)
    analysis = analyze_plan(plan, returns, headline_eligible=True)
    assert (plan.payload, plan.draws) == before
    assert not analysis["random_null"]["headline_eligible"]
    assert analysis["random_null"]["exact_distribution"] is None
    champion = analysis["portfolios"]["champion"]
    assert champion["member_ids"] == plan.payload["portfolios"]["champion"]["member_ids"]
    assert champion["exact_mean_local_return_pct"] is None
    assert champion["random_comparison"]["percentile_pct"] is None


def test_complete_draws_subset_not_primary_even_when_many_survive(case, plan):
    returns = observed(case[1])
    returns.pop(case[1].rows[-1].company_id)
    random = analyze_plan(plan, returns, headline_eligible=True)["random_null"]
    assert 0 < random["fully_observed_draws"] < 1000
    assert random["fully_observed_draws"] + random["incomplete_draws"] == 1000
    assert random["complete_draw_fraction"] == random["fully_observed_draws"] / 1000
    assert random["exact_distribution"] is None


def test_complete_distribution_and_champion_percentile_arithmetic(case, plan):
    returns = observed(case[1])
    values = [statistics.fmean(returns[key] for key in draw) for draw in plan.draws]
    analysis = analyze_plan(plan, returns, headline_eligible=True)
    random = analysis["random_null"]
    assert random["fully_observed_draws"] == 1000
    assert random["exact_distribution"]["mean_local_return_pct"] == statistics.fmean(values)
    assert random["exact_distribution"]["median_local_return_pct"] == statistics.median(values)
    champion = analysis["portfolios"]["champion"]
    exact = statistics.fmean(returns[key] for key in champion["member_ids"])
    assert champion["exact_mean_local_return_pct"] == exact
    expected = 100 * (sum(v < exact for v in values) + 0.5 * sum(v == exact for v in values)) / 1000
    assert champion["random_comparison"]["percentile_pct"] == expected
    assert champion["random_comparison"]["exact_local_excess_vs_mean_pct"] == exact - statistics.fmean(values)


def test_all_ties_use_midrank_percentile(case, plan):
    result = analyze_plan(plan, {key: 7.0 for key in observed(case[1])}, headline_eligible=True)
    assert result["portfolios"]["champion"]["random_comparison"]["percentile_pct"] == 50
    assert result["random_null"]["exact_distribution"]["mean_local_return_pct"] == 7


@pytest.mark.parametrize("values,q,expected", [
    ([0, 10], 0.05, 0.5), ([0, 10], 0.95, 9.5), ([3], 0.95, 3),
    ([0, 10, 20], 0.5, 10), ([], 0.5, None), ([10, 0], 0.95, 9.5),
])
def test_frozen_linear_quantiles(values, q, expected):
    assert percentile(values, q) == expected


@pytest.mark.parametrize("returns,exact,count", [({}, None, 0), ({"a": 20}, None, 1), ({"a": 20, "b": -10}, 5, 2)])
def test_equal_weight_original_denominator(returns, exact, count):
    value = cohort_result(("a", "b"), returns)
    assert value["member_ids"] == ["a", "b"]
    assert value["decision_time_member_count"] == 2
    assert value["priced_count"] == count and value["missing_count"] == 2 - count
    assert value["exact_mean_local_return_pct"] == exact
    assert value["observed_weight"] == count / 2


def test_opportunity_and_gate_members_fixed_from_actual_x(case, plan):
    returns = observed(case[1])
    for row in case[1].rows[:10]:
        returns.pop(row.company_id)
    result = analyze_plan(plan, returns, headline_eligible=True)
    for name in ("opportunity_universe", "gate_qualified"):
        assert set(result[name]["member_ids"]) == {row.company_id for row in case[1].rows}
        assert result[name]["decision_time_member_count"] == 60
        assert result[name]["priced_count"] == 50
        assert result[name]["exact_mean_local_return_pct"] is None


def test_exposure_exactly_reproduces_seven_three(case, plan):
    selected = plan.payload["portfolios"]["champion"]
    assert selected["country_counts"] == {"FI": 3, "SE": 7}
    weighted = weighted_alternatives(selected, observed(case[1]))
    country = {row.company_id: row.country for row in case[1].rows}
    assert sum(weight for key, weight in weighted["security_weights"].items() if country[key] == "FI") == pytest.approx(0.3)
    assert sum(weight for key, weight in weighted["security_weights"].items() if country[key] == "SE") == pytest.approx(0.7)
    assert not set(selected["member_ids"]) & set(weighted["security_weights"])


@pytest.mark.parametrize("size", ["large", "mid", "small"])
@pytest.mark.parametrize("venue", ["main_market", "first_north"])
def test_matching_uses_recorded_size_and_venue(case, size, venue):
    rows = tuple(replace(row, country="SE", segment=venue, nasdaq_size_segment=size) for row in case[1].rows)
    pool = matched_pool(rows[0], rows[1:])
    assert pool["stratum"] == {"country": "SE", "venue": venue, "size": size}
    assert len(pool["member_ids"]) == 59


@pytest.mark.parametrize("venue,size,expected", [
    ("main_market", None, {"country": "SE", "venue": "main_market"}),
    ("unknown", None, {"country": "SE"}),
    ("unknown", "small", {"country": "SE"}),
])
def test_missing_fields_use_preregistered_fallback(case, venue, size, expected):
    rows = [replace(row, country="SE", segment=venue, nasdaq_size_segment=size) for row in case[1].rows]
    assert matched_pool(rows[0], rows[1:])["stratum"] == expected


@pytest.mark.parametrize("count,expected", [(0, "unavailable"), (4, "unavailable"), (5, "available")])
def test_minimum_alternatives_is_five(case, count, expected):
    rows = [replace(row, country="SE") for row in case[1].rows]
    assert MIN_ALTERNATIVES == 5
    assert matched_pool(rows[0], rows[1:count + 1])["status"] == expected


def test_insufficient_size_falls_back_then_insufficient_venue_falls_back(case):
    target = replace(case[1].rows[0], country="SE", segment="main_market", nasdaq_size_segment="small")
    alternatives = [replace(row, country="SE", segment="main_market", nasdaq_size_segment="large") for row in case[1].rows[1:]]
    assert matched_pool(target, alternatives)["stratum"] == {"country": "SE", "venue": "main_market"}
    alternatives = [replace(row, segment="first_north") for row in alternatives]
    assert matched_pool(target, alternatives)["stratum"] == {"country": "SE"}


def test_peer_pools_exclude_entire_portfolio_and_are_order_independent(case, plan):
    portfolio = plan.payload["portfolios"]["champion"]
    for key, pool in portfolio["peers"].items():
        assert key not in pool["member_ids"]
        assert not set(pool["member_ids"]) & set(portfolio["member_ids"])
    assert portfolio_plan(case[1], reversed(portfolio["member_ids"])) == portfolio


def test_later_metadata_is_rejected_not_used_to_change_old_plan(case, plan):
    modified = replace(case[1], rows=tuple(replace(row, nasdaq_size_segment="large") for row in case[1].rows))
    with pytest.raises(ValueError, match="conflicts"):
        validate_benchmark_plan(modified, plan, case[2])


def test_peer_and_exposure_partial_results_keep_fixed_weights(case, plan):
    full = observed(case[1])
    portfolio = plan.payload["portfolios"]["champion"]
    missing = portfolio["peers"][portfolio["member_ids"][0]]["member_ids"][0]
    full.pop(missing)
    result = analyze_plan(plan, full, headline_eligible=True)["portfolios"]["champion"]
    assert result["exposure_matched"]["exact_mean_local_return_pct"] is None
    assert result["exposure_matched"]["observed_weight"] < 1
    assert result["comparisons"]["exposure_matched"]["headline_local_excess_pct"] is None
    for key, cohort in result["matched_peers"].items():
        if missing in cohort["member_ids"]:
            assert cohort["exact_local_excess_pct"] is None
    assert result["exposure_matched"]["security_weights"] == weighted_alternatives(portfolio, {})["security_weights"]


def test_no_alternatives_keeps_unavailable_exposure_weight(case):
    portfolio = portfolio_plan(case[1], [row.company_id for row in case[1].rows])
    result = weighted_alternatives(portfolio, observed(case[1]))
    assert result["exact_mean_local_return_pct"] is None
    assert result["unavailable_exposure_weight"] == pytest.approx(1)


def test_plan_roundtrip_immutable_and_no_y(case, plan, tmp_path):
    before = serialize_evaluation_snapshot(case[1])
    path = save_benchmark_plan(tmp_path, case[1], plan)
    assert save_benchmark_plan(tmp_path, case[1], plan) == path
    assert load_benchmark_plan(tmp_path, case[1], case[2]) == plan
    assert '"raw_forward_return_pct"' not in path.read_text()
    assert not {"outcomes", "returns", "prices"} & set(plan.payload)
    assert serialize_evaluation_snapshot(case[1]) == before
    changed = deepcopy(plan.payload)
    changed["random"]["draw_count"] = 20
    with pytest.raises(ValueError, match="identity conflict"):
        save_benchmark_plan(tmp_path, case[1], BenchmarkPlan(changed, ()))


@pytest.mark.parametrize("field", ["x_sha256", "benchmark_methodology", "provenance", "plan_id"])
def test_tampered_plan_rejected(case, plan, field):
    value = deepcopy(plan.payload)
    value[field] = "wrong"
    with pytest.raises(ValueError):
        validate_benchmark_plan(case[1], BenchmarkPlan(value, ()), case[2])


def test_random_draw_digest_prevents_changed_algorithm_membership(case, plan):
    value = deepcopy(plan.payload)
    value["random"]["membership_sha256"] = "changed"
    with pytest.raises(ValueError, match="conflicts"):
        validate_benchmark_plan(case[1], BenchmarkPlan(value, ()), case[2])


def test_historical_policy_missing_is_unverified_not_guessed(case):
    plan = build_benchmark_plan(case[1])
    assert plan.payload["provenance"] == "retrospective"
    assert plan.payload["random"]["status"] == "unverified"
    assert plan.draws == ()
    assert plan.payload["portfolios"]["champion"]["status"] == "recorded"


def test_retrospective_corrected_sidecar_supports_random_but_not_prospective(case):
    plan = build_benchmark_plan(case[1], experiment=case[2])
    assert plan.payload["provenance"] == "retrospective"
    assert len(plan.draws) == 1000


def test_new_live_producer_is_prospective_and_fixtures_never_are(case, plan):
    live = retag(case[1], provider="live")
    context = {"event": "schedule", "run_id": "123", "repository": "vernerisirva/investmentagent", "workflow_sha": "a" * 40}
    actual = build_benchmark_plan(live, result=case[0], production_context=context)
    assert actual.payload["provenance"] == "prospective"
    assert actual.payload["production_context"] == context
    assert build_benchmark_plan(live, result=case[0]).payload["provenance"] == "prospective_unscheduled"
    assert plan.payload["provenance"] == "fixture"
    assert build_benchmark_plan(live).payload["provenance"] == "retrospective"


def test_historical_missing_prefix_does_not_invent_portfolio():
    plan = build_benchmark_plan(_snapshot(20))
    assert plan.payload["portfolios"]["champion"]["status"] == "unverified"


def test_new_live_selection_must_reproduce_x(case):
    broken = replace(case[0], selected_items=case[0].selected_items[:-1])
    with pytest.raises(ValueError, match="reproduce"):
        build_benchmark_plan(case[1], result=broken)


def test_challenger_plan_requires_the_same_immutable_sidecar(case, plan):
    with pytest.raises(ValueError, match="conflicts"):
        validate_benchmark_plan(case[1], plan)


def test_later_experiment_does_not_upgrade_existing_plan(case):
    plan = build_benchmark_plan(case[1], result=case[0])
    checked = validate_benchmark_plan(case[1], plan, case[2])
    assert checked.payload["portfolios"]["challenger"]["status"] == "unverified"


def test_analysis_preserves_y_x_and_challenger_selections(case, plan):
    snapshot, experiment = case[1:]
    store = _priced_outcomes(snapshot, [float(row.rank) for row in snapshot.rows])
    before = serialize_evaluation_snapshot(snapshot), serialize_outcome_set(store), serialize_experiment_snapshot(experiment)
    result = build_benchmark_analysis([snapshot], [store], generated_at=GENERATED,
                                     experiment_snapshots=[experiment], plans={snapshot.run_id: plan})
    assert result["schema_version"] == 4
    metric = result["run_metrics"][0]
    assert metric["random_null"]["headline_eligible"]
    for side in ("champion", "challenger"):
        assert metric["portfolios"][side]["member_ids"] == plan.payload["portfolios"][side]["member_ids"]
    assert before == (serialize_evaluation_snapshot(snapshot), serialize_outcome_set(store), serialize_experiment_snapshot(experiment))


@pytest.mark.parametrize("count,missing,eligible", [(100, 30, True), (100, 31, False), (49, 0, False), (50, 0, True)])
def test_original_overall_coverage_guards_unchanged(count, missing, eligible):
    snapshot = _snapshot(count)
    store = _priced_outcomes(snapshot, [1.0] * count, missing_company_ids=[row.company_id for row in snapshot.rows[:missing]])
    result = build_benchmark_analysis([snapshot], [store], generated_at=GENERATED)
    metric = result["run_metrics"][0]
    assert metric["analysis_eligible"] is eligible
    assert metric["analysis_eligibility"]["minimum_valid_companies"] == 50
    assert metric["analysis_eligibility"]["minimum_coverage_pct"] == 70


def test_original_country_guards_unchanged(case, plan):
    store = _priced_outcomes(case[1], [1.0] * 60)
    result = build_benchmark_analysis([case[1]], [store], generated_at=GENERATED, plans={case[1].run_id: plan}, experiment_snapshots=[case[2]])
    for country in result["run_metrics"][0]["country_ranking_diagnostics"]:
        assert country["analysis_eligibility"]["minimum_valid_companies"] == 20
        assert country["analysis_eligibility"]["minimum_coverage_pct"] == 70


def test_historical_cutoff_hides_future_returns_without_changing_plan(case, plan):
    snapshot = case[1]
    store = _priced_outcomes(snapshot, [1.0] * 60)
    results = [build_benchmark_analysis([snapshot], [store], generated_at=GENERATED, data_cutoff=cutoff,
                plans={snapshot.run_id: plan}, experiment_snapshots=[case[2]])
               for cutoff in (snapshot.decision_at + timedelta(days=2), GENERATED)]
    early, late = [result["run_metrics"][0] for result in results]
    assert early["plan_id"] == late["plan_id"]
    assert early["opportunity_universe"]["priced_count"] == 0
    assert late["opportunity_universe"]["priced_count"] == 60
    assert early["lifecycle"]["mature_pending"] == 60


def test_grouping_never_pools_provenance_or_policy(case, plan):
    store = _priced_outcomes(case[1], [1.0] * 60)
    run = build_benchmark_analysis([case[1]], [store], generated_at=GENERATED,
            plans={case[1].run_id: plan}, experiment_snapshots=[case[2]])["run_metrics"][0]
    groups = aggregate_benchmark_runs([run, {**run, "provenance": "prospective"}, {**run, "selection_configuration_id": "different"}])
    assert len(groups) == 3 and all(group["evaluation_run_count"] == 1 for group in groups)


def test_legacy_fields_and_v1_do_not_enter_new_headlines(case):
    store = _priced_outcomes(case[1], [1.0] * 60)
    result = build_benchmark_analysis([case[1]], [store], generated_at=GENERATED)
    assert result["legacy_policy"]["performance_v1"] == "LEGACY_NON_AUTHORITATIVE"
    assert "universe_equal_weight_return_pct" not in json.dumps(result)
    assert "company_benchmarks" not in result["run_metrics"][0]
    assert result["external_passive_benchmark"] == {"status": "deferred_pending_license", "included_in_frozen_v1": False}


@pytest.mark.parametrize("suffix", ["json", "md"])
@pytest.mark.parametrize("reverse", [False, True])
def test_new_and_old_analysis_cannot_overwrite_each_other(case, tmp_path, suffix, reverse):
    store = _priced_outcomes(case[1], [1.0] * 60)
    old = build_performance_v2_analysis([case[1]], [store], generated_at=GENERATED)
    new = build_benchmark_analysis([case[1]], [store], generated_at=GENERATED)
    path = tmp_path / ("analysis." + suffix)
    save = save_analysis_json if suffix == "json" else save_analysis_markdown
    first, second = (new, old) if reverse else (old, new)
    save(path, first)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        save(path, second)
    assert path.read_bytes() == before


def test_no_currency_wealth_claim_and_excess_requires_completeness(case, plan):
    returns = observed(case[1])
    returns.pop(case[1].rows[0].company_id)
    result = analyze_plan(plan, returns, headline_eligible=True)
    assert result["return_label"] == "mean_local_return_pct"
    assert all(row["headline_local_excess_pct"] is None for row in result["portfolios"]["champion"]["comparisons"].values())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_nonfinite_or_boolean_y_rejected(case, plan, bad):
    with pytest.raises(ValueError, match="finite"):
        analyze_plan(plan, {case[1].rows[0].company_id: bad}, headline_eligible=True)


def test_cli_producer_persists_plan_without_external_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    root = tmp_path / "evaluations"
    result = CliRunner().invoke(app, ["watchlist", "--provider", "fixture", "--strategy", "long-term",
        "--evaluation-dir", str(root), "--experiment-dir", str(tmp_path / "experiments"),
        "--evaluation-decision-at", "2026-08-10T08:00:00Z", "--min-country", "FI:3"])
    assert result.exit_code == 0, result.exception
    snapshot = load_evaluation_snapshot(next(root.rglob("*.jsonl")))
    payload = json.loads(benchmark_plan_path(root, snapshot).read_text())
    assert payload["provenance"] == "fixture"
    assert payload["random"]["draw_count"] == 1000


def test_store_analysis_reads_plan_and_fails_closed_if_tampered(case, plan, tmp_path):
    save_evaluation_snapshot(tmp_path / "x", case[1])
    unpaired = build_benchmark_plan(case[1], result=case[0])
    path = save_benchmark_plan(tmp_path / "x", case[1], unpaired)
    result = analyze_outcome_store(tmp_path / "x", tmp_path / "y", generated_at=GENERATED)
    assert result["run_metrics"][0]["provenance"] == "fixture"
    payload = json.loads(path.read_text())
    payload["random"]["draw_count"] = 5
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="conflicts"):
        analyze_outcome_store(tmp_path / "x", tmp_path / "y", generated_at=GENERATED)


@pytest.mark.parametrize("size", ["small", "mid", "large"])
def test_optional_size_roundtrip_does_not_guess_current_market_cap(case, size, tmp_path):
    snapshot = replace(case[1], rows=tuple(replace(row, nasdaq_size_segment=size) for row in case[1].rows))
    assert load_evaluation_snapshot(save_evaluation_snapshot(tmp_path, snapshot)) == snapshot
    assert "nasdaq_size_segment" not in serialize_evaluation_snapshot(case[1])


def test_empty_production_is_not_an_exact_null():
    result, snapshot, experiment = production_case(research=[], scores=[])
    plan = build_benchmark_plan(snapshot, result=result, experiment=experiment)
    analysis = analyze_plan(plan, {}, headline_eligible=True)
    assert not analysis["random_null"]["headline_eligible"]
    assert analysis["portfolios"]["champion"]["exact_mean_local_return_pct"] is None


@pytest.mark.parametrize("field,value", [("event", "workflow_dispatch"), ("repository", "other/repo"),
                                        ("run_id", ""), ("workflow_sha", "short")])
def test_prospective_requires_valid_natural_execution_context(case, field, value):
    live = retag(case[1], provider="live")
    context = {"event": "schedule", "run_id": "123", "repository": "vernerisirva/investmentagent", "workflow_sha": "a" * 40}
    context[field] = value
    with pytest.raises(ValueError, match="natural production"):
        build_benchmark_plan(live, result=case[0], production_context=context)


def test_freeze_manifest_pins_unchanged_strategy_files():
    import hashlib
    from pathlib import Path
    manifest = json.loads(Path("METHODOLOGY_FREEZE.json").read_text())
    for path, digest in manifest["preserved_strategy_source_sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert manifest["benchmarks"]["random_draws"] == RANDOM_DRAWS
    assert manifest["benchmarks"]["minimum_alternatives"] == MIN_ALTERNATIVES


def test_new_v1_scorecard_discloses_quarantine_without_changing_ledger():
    from investmentagent.performance import empty_ledger, render_scorecard_markdown
    ledger = empty_ledger()
    before = deepcopy(ledger)
    assert "LEGACY_NON_AUTHORITATIVE" in render_scorecard_markdown(ledger, generated_at="2026-09-08")
    assert ledger == before


def test_coherent_revisions_change_returns_not_membership_and_respect_cutoff(tmp_path):
    from test_coherent_price_histories import _run, _prices, OLD_TIME, NEW_TIME
    from investmentagent.evaluation_outcomes import discover_outcome_sets
    snapshot = _snapshot(1, strategy="trading")
    _run(tmp_path, snapshot, _prices(snapshot, 100, 110, OLD_TIME), at=OLD_TIME)
    _run(tmp_path, snapshot, _prices(snapshot, 100, 120, NEW_TIME), at=NEW_TIME, reprice=True)
    stores = discover_outcome_sets(tmp_path / "outcomes")
    rows = [build_benchmark_analysis([snapshot], stores, generated_at=NEW_TIME, data_cutoff=cutoff)["run_metrics"][0]
            for cutoff in (OLD_TIME, NEW_TIME)]
    assert rows[0]["plan_id"] == rows[1]["plan_id"]
    assert rows[0]["opportunity_universe"]["member_ids"] == rows[1]["opportunity_universe"]["member_ids"]
    assert rows[0]["opportunity_universe"]["exact_mean_local_return_pct"] == pytest.approx(10)
    assert rows[1]["opportunity_universe"]["exact_mean_local_return_pct"] == pytest.approx(20)


def test_workflow_stages_plans_and_uses_versioned_analysis_without_index_api():
    from pathlib import Path
    workflow = Path(".github/workflows/daily-public-watchlist.yml").read_text()
    assert "cutoff-maturity-v1/representative-benchmarks-v1/performance-v2.json" in workflow
    assert "git push origin HEAD:codex/investmentagent-live-data" in workflow
    assert '"$EVALUATION_ROOT"' in workflow
    assert "--max-price-api-calls 20" in workflow
    assert "--reprice" not in workflow
    assert "benchmark-index" not in workflow


def test_legacy_return_method_cannot_supply_new_exact_benchmark_evidence(case):
    from investmentagent.price_histories import LEGACY_RETURN_METHOD
    with pytest.raises(ValueError, match="requires coherent"):
        build_benchmark_analysis([case[1]], [], generated_at=GENERATED, return_methodology=LEGACY_RETURN_METHOD)
