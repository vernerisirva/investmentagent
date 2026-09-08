"""Internal benchmarks attach the existing cutoff-selected Y to immutable X plans."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from investmentagent.benchmarks import (
    BENCHMARK_METHODOLOGY, EXTERNAL_STATUS, HIERARCHY, BenchmarkPlan,
    build_benchmark_plan, canonical_hash, validate_benchmark_plan,
)
from investmentagent.decision_membership import DecisionCohort


BENCHMARK_ANALYSIS_SCHEMA = 4


def cohort_result(ids, returns):
    observed = DecisionCohort(tuple(ids)).observe(returns)
    exact = observed.pop("exact_equal_weight_return_pct")
    partial = observed.pop("observed_mean_return_pct")
    observed.pop("observed_median_return_pct")
    return {**observed, "exact_mean_local_return_pct": exact,
            "observed_member_mean_local_return_pct": partial,
            "statistic_scope": "exact only with complete fixed membership; observed mean is a partial diagnostic"}


def percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values):
    return {"mean_local_return_pct": statistics.fmean(values) if values else None,
            "median_local_return_pct": statistics.median(values) if values else None,
            "p05_local_return_pct": percentile(values, 0.05),
            "p95_local_return_pct": percentile(values, 0.95)}


def _excess(left, right):
    return left - right if left is not None and right is not None else None


def weighted_alternatives(portfolio, returns):
    weights = defaultdict(float)
    strata = []
    unavailable_weight = 0.0
    for stratum in portfolio["exposure_strata"]:
        members = stratum["member_ids"]
        observed = cohort_result(members, returns)
        strata.append({"stratum_id": stratum["stratum_id"], "stratum": stratum["stratum"],
                       "weight": stratum["weight"], "status": stratum["status"], **observed})
        if not members:
            unavailable_weight += stratum["weight"]
        else:
            for key in members:
                weights[key] += stratum["weight"] / len(members)
    observed_weight = math.fsum(weight for key, weight in weights.items() if key in returns)
    contribution = math.fsum(weight * returns[key] for key, weight in sorted(weights.items()) if key in returns)
    complete = bool(weights) and unavailable_weight == 0 and all(key in returns for key in weights)
    return {
        "exact_mean_local_return_pct": contribution if complete else None,
        "observed_fixed_weight_contribution_pct": contribution if observed_weight else None,
        "observed_weight": observed_weight, "coverage_pct": observed_weight * 100,
        "unavailable_exposure_weight": unavailable_weight,
        "decision_time_member_count": len(weights), "observed_count": sum(key in returns for key in weights),
        "missing_count": sum(key not in returns for key in weights),
        "security_weights": dict(sorted(weights.items())), "strata": strata,
        "return_status": "complete" if complete else "incomplete",
        "statistic_scope": "fixed exposure weights; partial contribution is not a full return or a zero-imputed estimate",
    }


def analyze_plan(plan: BenchmarkPlan, returns: dict[str, float], *, headline_eligible: bool):
    value = plan.payload
    allowed = set(value["opportunity_member_ids"])
    if not set(returns) <= allowed or any(isinstance(v, bool) or not math.isfinite(v) for v in returns.values()):
        raise ValueError("benchmark returns must be finite observed outcomes from X")
    opportunity = cohort_result(value["opportunity_member_ids"], returns)
    gated = cohort_result(value["gate_qualified_member_ids"], returns)
    completed = [statistics.fmean(returns[key] for key in draw) for draw in plan.draws
                 if draw and all(key in returns for key in draw)]
    random_complete = bool(plan.draws) and bool(gated["decision_time_member_count"]) and gated["return_status"] == "complete"
    random_eligible = random_complete and headline_eligible
    random = {
        **value["random"], "total_draws": len(plan.draws), "fully_observed_draws": len(completed),
        "incomplete_draws": len(plan.draws) - len(completed),
        "complete_draw_fraction": len(completed) / len(plan.draws) if plan.draws else 0.0,
        "underlying_universe": gated, "headline_eligible": random_eligible,
        "exact_distribution": distribution(completed) if random_eligible else None,
        "complete_draw_diagnostic": {"scope": "non-headline; complete draws may be a survivor-selected subset",
                                     **distribution(completed)},
        "ineligibility_reasons": ([] if random_eligible else [
            "requires verified policy, complete nonempty eligible X outcomes, coherent returns, and existing analysis eligibility"]),
    }
    portfolios = {}
    for side, portfolio in value["portfolios"].items():
        if portfolio["status"] != "recorded":
            portfolios[side] = portfolio
            continue
        selected = cohort_result(portfolio["member_ids"], returns)
        exact = selected["exact_mean_local_return_pct"]
        exposure = weighted_alternatives(portfolio, returns)
        peers = {}
        for key, pool in portfolio["peers"].items():
            cohort = cohort_result(pool["member_ids"], returns)
            peers[key] = {**pool, **cohort, "selected_local_return_pct": returns.get(key),
                          "exact_local_excess_pct": _excess(returns.get(key), cohort["exact_mean_local_return_pct"])}
        percentile_rank = (100 * (sum(v < exact for v in completed) + 0.5 * sum(v == exact for v in completed))
                           / len(completed) if random_eligible and exact is not None else None)
        comparisons = {}
        for name, benchmark in (("gate_qualified", gated), ("opportunity", opportunity), ("exposure_matched", exposure)):
            excess = _excess(exact, benchmark["exact_mean_local_return_pct"])
            comparisons[name] = {"exact_local_excess_pct": excess,
                                 "headline_local_excess_pct": excess if headline_eligible else None}
        portfolios[side] = {
            "status": "recorded", **selected, "country_counts": portfolio["country_counts"],
            "exposures": portfolio["exposures"], "exposure_matched": exposure, "matched_peers": peers,
            "comparisons": comparisons,
            "random_comparison": {"percentile_pct": percentile_rank,
                "percentile_rule": "100 * (draws strictly below + half ties) / all 1000 draws",
                "exact_local_excess_vs_mean_pct": _excess(exact, random["exact_distribution"]["mean_local_return_pct"]) if random_eligible else None,
                "exact_local_excess_vs_median_pct": _excess(exact, random["exact_distribution"]["median_local_return_pct"]) if random_eligible else None},
            "peer_portfolio_note": "equal selected-security weighted peer return equals exposure-matched mixture under the same frozen fallback rule",
        }
    return {"plan_id": value["plan_id"], "provenance": value["provenance"],
            "return_label": "mean_local_return_pct", "opportunity_universe": opportunity,
            "gate_qualified": gated, "gate_boundary": value["gate_boundary"],
            "random_null": random, "portfolios": portfolios}


def build_benchmark_analysis(snapshots, outcome_sets, *, generated_at, return_methodology=None,
                             data_cutoff=None, experiment_snapshots=None, plans=None,
                             eligibility_criteria=None, country_eligibility_criteria=None):
    from investmentagent.analysis_eligibility import DEFAULT_ANALYSIS_ELIGIBILITY, DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY
    from investmentagent.evaluation_analysis import build_performance_v2_analysis
    from investmentagent.price_histories import COHERENT_RETURN_METHOD
    if return_methodology not in (None, COHERENT_RETURN_METHOD):
        raise ValueError("benchmark-v1 requires coherent stock returns; use the legacy analysis API for old methods")
    return_methodology = COHERENT_RETURN_METHOD
    snapshots, outcome_sets = tuple(snapshots), tuple(outcome_sets)
    experiments = tuple(experiment_snapshots or ())
    legacy = build_performance_v2_analysis(
        snapshots, outcome_sets, generated_at=generated_at, return_methodology=return_methodology,
        data_cutoff=data_cutoff, experiment_snapshots=experiments,
        eligibility_criteria=eligibility_criteria or DEFAULT_ANALYSIS_ELIGIBILITY,
        country_eligibility_criteria=country_eligibility_criteria or DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY,
    )
    by_run = {snapshot.run_id: snapshot for snapshot in snapshots}
    if len(by_run) != len(snapshots):
        raise ValueError("duplicate benchmark evaluation identity")
    supplied = plans or {}
    if set(supplied) - set(by_run):
        raise ValueError("orphan benchmark plan")
    validated = {}
    runs = []
    for metric in legacy["run_metrics"]:
        run_id = metric["evaluation_run_id"]
        if run_id not in validated:
            experiment = next((e for e in experiments if e.base_evaluation_run_id == run_id and e.schema_version == 2), None)
            validated[run_id] = (validate_benchmark_plan(by_run[run_id], supplied[run_id], experiment)
                                 if run_id in supplied else build_benchmark_plan(by_run[run_id], experiment=experiment))
        plan = validated[run_id]
        returns = {row["company_id"]: row["return_pct"] for row in metric["company_benchmarks"] if row["return_pct"] is not None}
        coherent = legacy["methodology"]["return_methodology"] == "single-response-adjusted-close-v1"
        runs.append({
            **{key: metric[key] for key in ("evaluation_run_id", "decision_at", "strategy", "scoring_model_version",
                "horizon", "is_due", "analysis_eligible", "analysis_eligibility", "outcome_coverage_pct", "lifecycle",
                "score_return_spearman_ic", "final_rank_return_spearman_ic", "analysis_ineligibility_reasons")},
            "country_ranking_diagnostics": [{key: country[key] for key in (
                "country", "original_company_count", "valid_company_count", "analysis_eligible",
                "analysis_eligibility", "score_return_spearman_ic", "final_rank_return_spearman_ic")}
                for country in metric["country_metrics"]],
            "benchmark_methodology": BENCHMARK_METHODOLOGY,
            "selection_configuration_id": canonical_hash(plan.payload["selection_evidence"]["policy"]) if plan.payload["selection_evidence"] else "unverified",
            "coherent_return_basis": coherent,
            **analyze_plan(plan, returns, headline_eligible=metric["analysis_eligible"] and coherent),
        })
    return {
        "schema_version": BENCHMARK_ANALYSIS_SCHEMA, "benchmark_methodology": BENCHMARK_METHODOLOGY,
        "analysis_methodology": legacy["analysis_methodology"],
        "outcome_status_methodology": legacy["outcome_status_methodology"],
        "generated_at": legacy["generated_at"], "methodology": {
            **{key: val for key, val in legacy["methodology"].items() if key not in ("benchmark", "country_benchmark_minimum")},
            "hierarchy": HIERARCHY, "return_label": "mean_local_return_pct",
            "primary_question": "Does ranking add value within the same X universe and production constraints?",
        },
        "external_passive_benchmark": {"status": EXTERNAL_STATUS, "included_in_frozen_v1": False},
        "legacy_policy": {"performance_v1": "LEGACY_NON_AUTHORITATIVE", "performance_v2_benchmarks": "deprecated survivor-defined diagnostics; not consumed by benchmark-v1",
                          "historical_artifacts": "preserved unchanged; legacy renderer/API retained separately"},
        "lifecycle": legacy["lifecycle"], "run_metrics": runs, "groups": aggregate_benchmark_runs(runs),
        "warnings": [*legacy["warnings"],
            "Mixed-country figures are mean local returns/excess, not base-currency wealth returns.",
            "X is already post-hard-gates; gate-qualified and opportunity cohorts coincide. Pre-gate value is not identifiable from retained X.",
            "Retrospective, fixture, and prospective samples are never pooled. Repeated companies/dates are dependent; random percentiles are not significance tests.",
            "No proprietary external passive index is included. This framework tests selection within X, not passive-market outperformance."],
    }


def aggregate_benchmark_runs(runs):
    grouped = defaultdict(list)
    for run in runs:
        if run["benchmark_methodology"] != BENCHMARK_METHODOLOGY:
            raise ValueError("cannot mix benchmark methodology versions")
        key = (run["strategy"], run["scoring_model_version"], run["horizon"]["sessions"],
               run["horizon"]["label"], run["provenance"], run["selection_configuration_id"])
        grouped[key].append(run)
    result = []
    for (strategy, model, sessions, label, provenance, policy), rows in sorted(grouped.items()):
        eligible = [row for row in rows if row["analysis_eligible"] and row["coherent_return_basis"]]
        primary = [row for row in eligible if row["random_null"]["headline_eligible"]]
        sides = {}
        for side in ("champion", "challenger"):
            values = [row["portfolios"][side]["random_comparison"]["exact_local_excess_vs_mean_pct"]
                      for row in primary if row["portfolios"][side]["status"] == "recorded"]
            values = [v for v in values if v is not None]
            sides[side] = {"exact_primary_dates": len(values),
                           "mean_local_excess_vs_random_pct": statistics.fmean(values) if values else None}
        ics = {key: [row[key] for row in eligible if row[key] is not None] for key in
               ("score_return_spearman_ic", "final_rank_return_spearman_ic")}
        result.append({"benchmark_methodology": BENCHMARK_METHODOLOGY, "strategy": strategy,
                       "scoring_model_version": model, "horizon": {"sessions": sessions, "label": label},
                       "provenance": provenance, "selection_configuration_id": policy,
                       "evaluation_run_count": len(rows), "analysis_eligible_run_count": len(eligible),
                       "primary_eligible_run_count": len(primary), "portfolios": sides,
                       "ranking": {key: {"run_count": len(vals), "mean": statistics.fmean(vals) if vals else None}
                                   for key, vals in ics.items()},
                       "scope": "separate provenance and selection policy; descriptive multi-date evidence, not a skill claim"})
    return result


def render_benchmark_markdown(analysis):
    def number(value):
        return "unavailable" if value is None else f"{value:.2f}"
    lines = ["# Performance v2: Internal Benchmarks", "",
             f"Generated: {analysis['generated_at']}",
             f"Analysis methodology: {analysis['analysis_methodology']}",
             f"Outcome status methodology: {analysis['outcome_status_methodology']}",
             f"Benchmark methodology: {BENCHMARK_METHODOLOGY}",
             f"Return methodology: {analysis['methodology']['return_methodology']}",
             f"Analysis data cutoff: {analysis['methodology']['analysis_data_cutoff']}", "",
             "Gross adjusted-close returns use the existing coherent stock outcomes; spread, commissions and slippage are excluded.",
             "Primary: constraint-matched random selection, 1000 fixed draws.",
             "Secondary: gate-qualified EW, opportunity EW, exposure-matched alternatives, matched peers.",
             "EXTERNAL_PASSIVE_BENCHMARK: DEFERRED_PENDING_LICENSE",
             "Performance v1: LEGACY_NON_AUTHORITATIVE. Old v2 survivor benchmarks are not validation evidence.", ""]
    for warning in analysis["warnings"]:
        lines += [f"> {warning}", ""]
    lines += ["## Separate Evidence Samples", "",
              "| Strategy | Horizon | Evidence | Evaluations | Ranking eligible | Exact primary dates | Champion mean local excess vs random (%) | Challenger mean local excess (%) |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for group in analysis["groups"]:
        lines.append(f"| {group['strategy']} | {group['horizon']['label']} | {group['provenance']} | {group['evaluation_run_count']} | {group['analysis_eligible_run_count']} | {group['primary_eligible_run_count']} | {number(group['portfolios']['champion']['mean_local_excess_vs_random_pct'])} | {number(group['portfolios']['challenger']['mean_local_excess_vs_random_pct'])} |")
    lines += ["", "## Fixed Portfolios and Coverage", ""]
    for run in analysis["run_metrics"]:
        lines += [f"### {run['evaluation_run_id']} / {run['horizon']['label']} / {run['provenance']}", "",
                  f"Score IC: {number(run['score_return_spearman_ic'])}; rank IC: {number(run['final_rank_return_spearman_ic'])}. Ranking eligible: {run['analysis_eligible']}.",
                  f"Random complete draws: {run['random_null']['fully_observed_draws']}/{run['random_null']['total_draws']}; underlying coverage: {number(run['random_null']['underlying_universe']['coverage_pct'])}%. Primary eligible: {run['random_null']['headline_eligible']}."]
        for side, portfolio in run["portfolios"].items():
            if portfolio["status"] != "recorded":
                lines.append(f"- {side}: selection unverified.")
                continue
            lines.append(f"- {side}: {portfolio['priced_count']}/{portfolio['decision_time_member_count']} fixed members observed; exact mean local return {number(portfolio['exact_mean_local_return_pct'])}%; partial observed-member diagnostic {number(portfolio['observed_member_mean_local_return_pct'])}%; random percentile {number(portfolio['random_comparison']['percentile_pct'])}.")
            for name, comparison in portfolio["comparisons"].items():
                lines.append(f"- {side} vs {name}: exact local excess {number(comparison['exact_local_excess_pct'])}%; eligible headline {number(comparison['headline_local_excess_pct'])}%.")
        lines.append("")
    return "\n".join(lines)
