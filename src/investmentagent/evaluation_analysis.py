from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from investmentagent.analysis_eligibility import (
    DEFAULT_ANALYSIS_ELIGIBILITY,
    DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY,
    AnalysisEligibilityCriteria,
    assess_analysis_eligibility,
)
from investmentagent.evaluation import EvaluationCompanyRow, EvaluationSnapshot
from investmentagent.evaluation_outcomes import (
    EvaluationOutcomeSet,
    MarketOutcome,
    discover_evaluation_snapshots,
    discover_outcome_sets,
)
from investmentagent.experiments import (
    ChallengerExperimentSnapshot,
    discover_experiment_snapshots,
)


ANALYSIS_SCHEMA_VERSION = 1
MIN_RELIABLE_EVALUATION_DATES = 20
MIN_IC_SAMPLE = 2


def analyze_outcome_store(
    evaluation_root: Path,
    outcome_root: Path,
    *,
    generated_at: datetime,
    experiment_root: Path | None = None,
    strategy: str | None = None,
    run_id: str | None = None,
    report_date: date | None = None,
    eligibility_criteria: AnalysisEligibilityCriteria = DEFAULT_ANALYSIS_ELIGIBILITY,
    country_eligibility_criteria: AnalysisEligibilityCriteria = (
        DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY
    ),
) -> dict[str, Any]:
    snapshots = discover_evaluation_snapshots(
        evaluation_root,
        strategy=strategy,
        run_id=run_id,
        report_date=report_date,
    )
    selected_run_ids = {snapshot.run_id for snapshot in snapshots}
    stores = tuple(
        store
        for store in discover_outcome_sets(outcome_root)
        if store.evaluation_run_id in selected_run_ids
    )
    experiments = (
        tuple(
            experiment
            for experiment in discover_experiment_snapshots(experiment_root)
            if experiment.base_evaluation_run_id in selected_run_ids
        )
        if experiment_root is not None
        else None
    )
    return build_performance_v2_analysis(
        snapshots,
        stores,
        generated_at=generated_at,
        experiment_snapshots=experiments,
        eligibility_criteria=eligibility_criteria,
        country_eligibility_criteria=country_eligibility_criteria,
    )


def build_performance_v2_analysis(
    snapshots: Iterable[EvaluationSnapshot],
    outcome_sets: Iterable[EvaluationOutcomeSet],
    *,
    generated_at: datetime,
    experiment_snapshots: Iterable[ChallengerExperimentSnapshot] | None = None,
    eligibility_criteria: AnalysisEligibilityCriteria = DEFAULT_ANALYSIS_ELIGIBILITY,
    country_eligibility_criteria: AnalysisEligibilityCriteria = (
        DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY
    ),
) -> dict[str, Any]:
    if generated_at.tzinfo is None:
        raise ValueError("analysis generated_at must be timezone-aware")
    ordered_snapshots = tuple(
        sorted(snapshots, key=lambda item: (item.decision_at, item.strategy))
    )
    ordered_stores = tuple(outcome_sets)
    stores_by_run = {store.evaluation_run_id: store for store in ordered_stores}
    if len(stores_by_run) != len(ordered_stores):
        raise ValueError("duplicate outcome set for evaluation run")
    snapshot_ids = {snapshot.run_id for snapshot in ordered_snapshots}
    orphaned = set(stores_by_run) - snapshot_ids
    if orphaned:
        raise ValueError(f"outcome store has no evaluation snapshot: {sorted(orphaned)[0]}")

    run_metrics: list[dict[str, Any]] = []
    all_outcomes: list[MarketOutcome] = []
    for snapshot in ordered_snapshots:
        store = stores_by_run.get(snapshot.run_id)
        if store is None:
            continue
        _validate_store_against_snapshot(snapshot, store)
        all_outcomes.extend(store.outcomes)
        for definition in store.horizon_definitions:
            horizon_outcomes = tuple(
                outcome
                for outcome in store.outcomes
                if outcome.horizon_label == definition.label
            )
            run_metrics.append(
                _analyze_run_horizon(
                    snapshot,
                    horizon_outcomes,
                    definition.label,
                    definition.sessions,
                    eligibility_criteria=eligibility_criteria,
                    country_eligibility_criteria=country_eligibility_criteria,
                )
            )

    groups = _aggregate_run_metrics(run_metrics)
    warnings = [
        (
            "Insufficient history for reliable inference: "
            f"{group['evaluated_run_count']} analysis-eligible evaluation dates for "
            f"{group['strategy']} / {group['scoring_model_version']} / "
            f"{group['horizon']['label']}."
        )
        for group in groups
        if group["evaluated_run_count"] < MIN_RELIABLE_EVALUATION_DATES
    ]
    warnings.extend(
        (
            "No sufficiently covered evaluation dates are available yet for "
            "ranking-quality conclusions: "
            f"{group['strategy']} / {group['scoring_model_version']} / "
            f"{group['horizon']['label']}."
        )
        for group in groups
        if group["due_run_count"] > 0 and group["evaluated_run_count"] == 0
    )
    if any(group["partial_run_count"] for group in groups):
        warnings.append(
            "Partial price coverage may be systematically related to symbol "
            "resolution, country, segment, or company identity; low-coverage "
            "run metrics are therefore descriptive only."
        )
    if not groups:
        warnings.append("No stored market outcomes are available for analysis.")
    analysis = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "generated_at": _format_timestamp(generated_at),
        "return_basis": "gross adjusted-close total-return-compatible prices",
        "costs_excluded": ["spread", "commissions", "slippage"],
        "primary_question": (
            "Do companies ranked higher subsequently outperform companies ranked lower?"
        ),
        "methodology": {
            "analysis_key": ["strategy", "scoring_model_version", "horizon"],
            "benchmark": (
                "equal-weight valid outcomes from the original point-in-time evaluation universe"
            ),
            "score_ic": "Spearman correlation of recorded total score and forward return",
            "final_rank_ic": (
                "Spearman correlation of negative recorded final rank and forward return"
            ),
            "aggregation": (
                "cross-sectional metrics are computed for every run; only analysis-eligible runs are aggregated"
            ),
            "buckets": (
                "rank quantiles; 10 buckets at n>=50, 5 at n>=25, 2 at n>=10, otherwise 1"
            ),
            "analysis_eligibility": eligibility_criteria.as_dict(),
            "country_analysis_eligibility": (
                country_eligibility_criteria.as_dict()
            ),
            "country_benchmark_minimum": 2,
        },
        "warnings": warnings,
        "run_metrics": run_metrics,
        "groups": groups,
        "missingness": _missingness_diagnostics(all_outcomes),
        "limitations": [
            "Repeated company observations across evaluation dates are not independent.",
            "Run-level aggregation limits domination by repeated securities but does not use clustered standard errors.",
            "Missing prices and possible delistings are retained as explicit states and are never treated as zero returns.",
            "Partial price coverage may be non-random across symbol resolution, country, segment, or company identity; ineligible run metrics are descriptive only.",
            "Gross returns do not establish trading profitability because transaction costs are excluded.",
            "Small samples are descriptive and do not establish statistical significance.",
        ],
    }
    if experiment_snapshots is not None:
        from investmentagent.challenger_analysis import build_challenger_analysis

        analysis["challenger_analysis"] = build_challenger_analysis(
            ordered_snapshots,
            ordered_stores,
            tuple(experiment_snapshots),
            eligibility_criteria=eligibility_criteria,
        )
    return analysis


def spearman_rank_correlation(left: Iterable[float], right: Iterable[float]) -> float | None:
    left_values = tuple(float(value) for value in left)
    right_values = tuple(float(value) for value in right)
    if len(left_values) != len(right_values):
        raise ValueError("Spearman inputs must have the same length")
    if len(left_values) < MIN_IC_SAMPLE:
        return None
    left_ranks = _average_tied_ranks(left_values)
    right_ranks = _average_tied_ranks(right_values)
    return _pearson_correlation(left_ranks, right_ranks)


def save_analysis_json(path: Path, analysis: dict[str, Any]) -> Path:
    content = json.dumps(
        analysis,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    _atomic_write_if_changed(path, content)
    return path


def save_analysis_markdown(path: Path, analysis: dict[str, Any]) -> Path:
    _atomic_write_if_changed(path, render_performance_v2_markdown(analysis) + "\n")
    return path


def render_performance_v2_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# Performance v2: Ranking Quality",
        "",
        f"Generated: {analysis['generated_at']}",
        "",
        "Gross adjusted-close returns are shown. Spread, commissions, and slippage are excluded.",
        "",
    ]
    for warning in analysis.get("warnings", []):
        lines.append(f"> **Warning:** {warning}")
        lines.append("")
    groups = analysis.get("groups", [])
    if not groups:
        lines.append("No completed outcomes are available yet.")
        _append_challenger_report(lines, analysis.get("challenger_analysis"))
        return "\n".join(lines)
    lines.extend(
        [
            "## Run-Level Summary",
            "",
            "| Strategy | Model | Horizon | Evaluations | Due | Eligible | Partial | Avg n | Avg due coverage | Required coverage | Mean score IC | Median score IC | Mean final-rank IC | IC hit rate | Top decile - universe |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in groups:
        lines.append(
            "| {strategy} | {model} | {horizon} | {runs} | {due} | {eligible} | {partial} | {size} | {coverage} | {required} | {mean_ic} | {median_ic} | {rank_ic} | {hit_rate} | {spread} |".format(
                strategy=group["strategy"],
                model=group["scoring_model_version"],
                horizon=group["horizon"]["label"],
                runs=group["evaluation_run_count"],
                due=group["due_run_count"],
                eligible=group["evaluated_run_count"],
                partial=group["partial_run_count"],
                size=_format_number(group["average_valid_universe_size"], 1),
                coverage=_format_percent(group["average_outcome_coverage_pct"]),
                required=_format_percent(
                    group["analysis_eligibility"]["minimum_coverage_pct"]
                ),
                mean_ic=_format_number(group["score_ic"]["mean"], 3),
                median_ic=_format_number(group["score_ic"]["median"], 3),
                rank_ic=_format_number(group["final_rank_ic"]["mean"], 3),
                hit_rate=_format_percent(group["score_ic"]["hit_rate_pct"]),
                spread=_format_return(
                    group["top_vs_universe"]["mean_top_decile_minus_universe_pct"]
                ),
            )
        )
    lines.extend(["", "## Rank Buckets", ""])
    for group in groups:
        label = (
            f"{group['strategy']} / {group['scoring_model_version']} / "
            f"{group['horizon']['label']}"
        )
        lines.append(f"### {label}")
        schemes = group["bucket_schemes"]
        if not schemes:
            lines.append(
                "No eligible-run bucket analysis is available; partial-run buckets remain in JSON diagnostics."
            )
            lines.append("")
            continue
        for scheme in schemes:
            lines.append(
                f"{scheme['bucket_count']}-bucket scheme; monotonic in "
                f"{scheme['monotonic_run_count']}/{scheme['run_count']} runs."
            )
            for bucket in scheme["buckets"]:
                lines.append(
                    f"- Bucket {bucket['bucket']} (best rank first): "
                    f"{_format_return(bucket['mean_return_pct'])}; "
                    f"{bucket['observations']} observations across "
                    f"{bucket['evaluation_dates']} dates"
                )
        lines.append("")
    long_term_groups = [
        group for group in groups if group["strategy"] == "long-term"
    ]
    if long_term_groups:
        lines.extend(["## Long-Term Gate Tiers", ""])
        for group in long_term_groups:
            lines.append(
                f"### {group['scoring_model_version']} / {group['horizon']['label']}"
            )
            for tier in group["gate_tiers"]:
                lines.append(
                    f"- {tier['tier']}: {_format_return(tier['mean_return_pct'])}; "
                    f"{tier['observations']} observations across "
                    f"{tier['evaluation_dates']} dates"
                )
            lines.append("")
    lines.extend(["## Country Breakdown", ""])
    for group in groups:
        label = (
            f"{group['strategy']} / {group['scoring_model_version']} / "
            f"{group['horizon']['label']}"
        )
        lines.append(f"### {label}")
        if not group["countries"]:
            lines.append("No country-specific outcomes are available.")
        for country in group["countries"]:
            lines.append(
                f"- {country['country']}: "
                f"{_format_return(country['mean_equal_weight_return_pct'])}; "
                f"mean score IC {_format_number(country['score_ic']['mean'], 3)}; "
                f"{country['analysis_eligible_run_count']}/{country['due_evaluation_dates']} "
                f"eligible dates; {_format_percent(country['average_outcome_coverage_pct'])} "
                f"average coverage; {country['observations']} eligible observations"
            )
        lines.append("")
    _append_challenger_report(lines, analysis.get("challenger_analysis"))
    lines.extend(
        [
            "## Interpretation Limits",
            "",
            "- Metrics are calculated per evaluation run before aggregation.",
            "- Repeated companies are not independent observations.",
            "- Missing outcomes remain visible and may create small-company or delisting bias.",
            "- Partial price coverage may be non-random across symbol resolution, country, segment, or company identity; ineligible metrics are descriptive only.",
            "- Model versions are analyzed separately and are never pooled by default.",
            "- No scoring weights are changed automatically.",
        ]
    )
    return "\n".join(lines)


def _append_challenger_report(
    lines: list[str], challenger: dict[str, Any] | None
) -> None:
    if challenger is None:
        return
    lines.extend(["## Shadow Challenger", ""])
    lines.append(
        f"Challenger sidecars recorded: {challenger.get('recorded_sidecar_count', 0)}."
    )
    lines.append("")
    for warning in challenger.get("warnings", []):
        lines.append(f"> **Warning:** {warning}")
        lines.append("")
    groups = challenger.get("groups", [])
    if groups:
        lines.extend(
            [
                "| Experiment | Champion | Horizon | Recorded | Due | Eligible | Partial | Mean score IC delta | Median score IC delta | IC improved | Top-decile spread delta | Top-10 overlap |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for group in groups:
            score_delta = group["paired_deltas"]["score_ic"]
            top_delta = group["paired_deltas"]["top_decile_minus_universe_pct"]
            churn = group["ranking_churn"]
            lines.append(
                "| {experiment} v{version} | {champion} | {horizon} | {recorded} | {due} | {eligible} | {partial} | {mean_delta} | {median_delta} | {improved} | {top_delta} | {overlap} |".format(
                    experiment=group["experiment_id"],
                    version=group["experiment_version"],
                    champion=group["champion_scoring_model_version"],
                    horizon=group["horizon"]["label"],
                    recorded=group["recorded_run_count"],
                    due=group["paired_due_date_count"],
                    eligible=group["paired_completed_date_count"],
                    partial=group["paired_partial_date_count"],
                    mean_delta=_format_number(score_delta["mean"], 3),
                    median_delta=_format_number(score_delta["median"], 3),
                    improved=_format_percent(score_delta["positive_date_pct"]),
                    top_delta=_format_return(top_delta["mean"]),
                    overlap=_format_percent(churn["mean_top_10_overlap_pct"]),
                )
            )
        lines.append("")
    statuses = challenger.get("run_statuses", [])
    missing = [status for status in statuses if status["status"] == "challenger not recorded"]
    if missing:
        lines.append(
            f"Challenger not recorded for {len(missing)} historical long-term evaluation run(s); no backfill was attempted."
        )
        lines.append("")
    if not groups and not missing:
        lines.append("No paired challenger outcomes are available yet.")
        lines.append("")


def _analyze_run_horizon(
    snapshot: EvaluationSnapshot,
    outcomes: tuple[MarketOutcome, ...],
    horizon_label: str,
    horizon_sessions: int,
    *,
    eligibility_criteria: AnalysisEligibilityCriteria,
    country_eligibility_criteria: AnalysisEligibilityCriteria,
) -> dict[str, Any]:
    if len(outcomes) != snapshot.universe_size:
        raise ValueError("outcome horizon does not cover the original evaluation universe")
    outcomes_by_company = {outcome.company_id: outcome for outcome in outcomes}
    if len(outcomes_by_company) != len(outcomes):
        raise ValueError("duplicate company outcome in run horizon")
    rows_by_company = {row.company_id: row for row in snapshot.rows}
    if set(outcomes_by_company) != set(rows_by_company):
        raise ValueError("outcome companies do not match the original evaluation universe")
    priced_pairs = [
        (row, outcomes_by_company[row.company_id])
        for row in snapshot.rows
        if outcomes_by_company[row.company_id].status == "priced"
    ]
    returns = [outcome.raw_forward_return_pct for _, outcome in priced_pairs]
    if any(value is None for value in returns):
        raise ValueError("priced outcome is missing its forward return")
    numeric_returns = [float(value) for value in returns]
    universe_return = _mean_or_none(numeric_returns)
    country_returns: dict[str, float] = {}
    for country in sorted({row.country for row, _ in priced_pairs}):
        values = [
            float(outcome.raw_forward_return_pct)
            for row, outcome in priced_pairs
            if row.country == country and outcome.raw_forward_return_pct is not None
        ]
        if len(values) >= 2:
            country_returns[country] = statistics.fmean(values)
    bucket_count = _bucket_count(len(priced_pairs))
    bucket_by_company = {
        row.company_id: min(
            bucket_count,
            (index * bucket_count // len(priced_pairs)) + 1,
        )
        for index, (row, _) in enumerate(
            sorted(priced_pairs, key=lambda pair: pair[0].rank)
        )
    }
    company_metrics = [
        {
            "company_id": row.company_id,
            "ticker": row.ticker,
            "country": row.country,
            "rank": row.rank,
            "score": row.score["total"],
            "rank_bucket": bucket_by_company.get(row.company_id),
            "return_pct": outcome.raw_forward_return_pct,
            "universe_equal_weight_return_pct": universe_return,
            "excess_vs_universe_pct": (
                outcome.raw_forward_return_pct - universe_return
                if universe_return is not None
                and outcome.raw_forward_return_pct is not None
                else None
            ),
            "same_country_equal_weight_return_pct": country_returns.get(row.country),
            "excess_vs_country_pct": (
                outcome.raw_forward_return_pct - country_returns[row.country]
                if row.country in country_returns
                and outcome.raw_forward_return_pct is not None
                else None
            ),
        }
        for row, outcome in priced_pairs
    ]
    scores = [row.score["total"] for row, _ in priced_pairs]
    negative_ranks = [-float(row.rank) for row, _ in priced_pairs]
    bucket_metrics = _run_bucket_metrics(priced_pairs, bucket_count, universe_return)
    top_metrics = _top_metrics(priced_pairs, universe_return)
    original_country_counts = Counter(row.country for row in snapshot.rows)
    country_metrics = [
        _country_run_metric(
            country,
            [pair for pair in priced_pairs if pair[0].country == country],
            original_company_count=original_count,
            eligibility_criteria=country_eligibility_criteria,
        )
        for country, original_count in sorted(original_country_counts.items())
    ]
    statuses = Counter(outcome.status for outcome in outcomes)
    is_due = statuses.get("not_due", 0) != len(outcomes)
    eligibility = assess_analysis_eligibility(
        len(priced_pairs),
        snapshot.universe_size,
        criteria=eligibility_criteria,
    )
    analysis_eligible = is_due and eligibility.eligible
    ineligibility_reasons = (
        list(eligibility.reasons) if is_due else ["horizon is not due"]
    )
    return {
        "evaluation_run_id": snapshot.run_id,
        "report_date": snapshot.report_date.isoformat(),
        "decision_at": _format_timestamp(snapshot.decision_at),
        "strategy": snapshot.strategy,
        "scoring_model_version": snapshot.scoring_model_version,
        "horizon": {
            "label": horizon_label,
            "sessions": horizon_sessions,
            "unit": "market_sessions",
        },
        "is_due": is_due,
        "original_universe_size": snapshot.universe_size,
        "valid_company_count": len(priced_pairs),
        "unique_company_count": len({row.company_id for row, _ in priced_pairs}),
        "outcome_coverage_pct": (
            (len(priced_pairs) / snapshot.universe_size) * 100
            if snapshot.universe_size
            else 0.0
        ),
        "analysis_eligible": analysis_eligible,
        "analysis_ineligibility_reasons": ineligibility_reasons,
        "analysis_eligibility": eligibility.as_dict(),
        "metric_scope": (
            "analysis_eligible" if analysis_eligible else "descriptive_partial"
        ),
        "status_counts": dict(sorted(statuses.items())),
        "universe_equal_weight_return_pct": universe_return,
        "score_return_spearman_ic": spearman_rank_correlation(scores, numeric_returns),
        "final_rank_return_spearman_ic": spearman_rank_correlation(
            negative_ranks, numeric_returns
        ),
        "company_benchmarks": company_metrics,
        "country_metrics": country_metrics,
        "bucket_count": bucket_count,
        "buckets": bucket_metrics,
        "bucket_returns_monotonic": _bucket_returns_monotonic(bucket_metrics),
        "top_vs_universe": top_metrics,
        "long_term_gate_tiers": (
            _run_gate_metrics(priced_pairs) if snapshot.strategy == "long-term" else []
        ),
    }


def _aggregate_run_metrics(run_metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for metric in run_metrics:
        horizon = metric["horizon"]
        grouped[
            (
                metric["strategy"],
                metric["scoring_model_version"],
                horizon["sessions"],
                horizon["label"],
            )
        ].append(metric)
    results: list[dict[str, Any]] = []
    for (strategy, model_version, sessions, label), metrics in sorted(grouped.items()):
        due_metrics = [metric for metric in metrics if metric["is_due"]]
        evaluated = [metric for metric in due_metrics if metric["analysis_eligible"]]
        partial = [
            metric for metric in due_metrics if not metric["analysis_eligible"]
        ]
        partially_priced = [
            metric for metric in partial if metric["valid_company_count"] > 0
        ]
        score_ics = [
            metric["score_return_spearman_ic"]
            for metric in evaluated
            if metric["score_return_spearman_ic"] is not None
        ]
        rank_ics = [
            metric["final_rank_return_spearman_ic"]
            for metric in evaluated
            if metric["final_rank_return_spearman_ic"] is not None
        ]
        unique_companies = {
            company["company_id"]
            for metric in due_metrics
            for company in metric["company_benchmarks"]
        }
        results.append(
            {
                "strategy": strategy,
                "scoring_model_version": model_version,
                "horizon": {
                    "label": label,
                    "sessions": sessions,
                    "unit": "market_sessions",
                },
                "evaluation_run_count": len(metrics),
                "due_run_count": len(due_metrics),
                "evaluated_run_count": len(evaluated),
                "analysis_eligible_run_count": len(evaluated),
                "partial_run_count": len(partial),
                "partially_priced_run_count": len(partially_priced),
                "unique_company_count": len(unique_companies),
                "average_valid_universe_size": _mean_or_none(
                    [metric["valid_company_count"] for metric in due_metrics]
                ),
                "average_outcome_coverage_pct": _mean_or_none(
                    [metric["outcome_coverage_pct"] for metric in due_metrics]
                ),
                "average_eligible_outcome_coverage_pct": _mean_or_none(
                    [metric["outcome_coverage_pct"] for metric in evaluated]
                ),
                "analysis_eligibility": {
                    "minimum_coverage_pct": metrics[0]["analysis_eligibility"][
                        "minimum_coverage_pct"
                    ],
                    "minimum_valid_companies": metrics[0][
                        "analysis_eligibility"
                    ]["minimum_valid_companies"],
                    "purpose": (
                        "research-quality aggregation guardrail; not a statistical-significance threshold"
                    ),
                },
                "score_ic": _aggregate_ic(score_ics),
                "final_rank_ic": _aggregate_ic(rank_ics),
                "top_vs_universe": _aggregate_top_metrics(evaluated),
                "bucket_schemes": _aggregate_bucket_schemes(evaluated),
                "gate_tiers": _aggregate_gate_tiers(evaluated),
                "countries": _aggregate_country_metrics(due_metrics),
                "sample_warning": (
                    len(evaluated) < MIN_RELIABLE_EVALUATION_DATES
                ),
            }
        )
    return results


def _run_bucket_metrics(
    priced_pairs: list[tuple[EvaluationCompanyRow, MarketOutcome]],
    bucket_count: int,
    universe_return: float | None,
) -> list[dict[str, Any]]:
    if bucket_count == 0:
        return []
    ordered = sorted(priced_pairs, key=lambda pair: pair[0].rank)
    bucket_values: dict[int, list[float]] = defaultdict(list)
    for index, (_, outcome) in enumerate(ordered):
        bucket = min(bucket_count, (index * bucket_count // len(ordered)) + 1)
        if outcome.raw_forward_return_pct is not None:
            bucket_values[bucket].append(outcome.raw_forward_return_pct)
    return [
        {
            "bucket": bucket,
            "observations": len(values),
            "mean_return_pct": statistics.fmean(values),
            "median_return_pct": statistics.median(values),
            "mean_excess_vs_universe_pct": (
                statistics.fmean(values) - universe_return
                if universe_return is not None
                else None
            ),
        }
        for bucket, values in sorted(bucket_values.items())
    ]


def _top_metrics(
    priced_pairs: list[tuple[EvaluationCompanyRow, MarketOutcome]],
    universe_return: float | None,
) -> dict[str, Any]:
    ordered = sorted(priced_pairs, key=lambda pair: pair[0].rank)
    if not ordered:
        return {
            "top_10_average_return_pct": None,
            "top_decile_count": 0,
            "top_decile_average_return_pct": None,
            "universe_average_return_pct": None,
            "top_decile_minus_universe_pct": None,
            "top_decile_minus_bottom_decile_pct": None,
        }
    values = [float(outcome.raw_forward_return_pct) for _, outcome in ordered]
    decile_size = max(1, math.ceil(len(values) * 0.1))
    top_decile = statistics.fmean(values[:decile_size])
    bottom_decile = statistics.fmean(values[-decile_size:])
    return {
        "top_10_average_return_pct": statistics.fmean(values[: min(10, len(values))]),
        "top_decile_count": decile_size,
        "top_decile_average_return_pct": top_decile,
        "universe_average_return_pct": universe_return,
        "top_decile_minus_universe_pct": (
            top_decile - universe_return if universe_return is not None else None
        ),
        "top_decile_minus_bottom_decile_pct": top_decile - bottom_decile,
    }


def _country_run_metric(
    country: str,
    pairs: list[tuple[EvaluationCompanyRow, MarketOutcome]],
    *,
    original_company_count: int,
    eligibility_criteria: AnalysisEligibilityCriteria,
) -> dict[str, Any]:
    scores = [row.score["total"] for row, _ in pairs]
    negative_ranks = [-float(row.rank) for row, _ in pairs]
    returns = [float(outcome.raw_forward_return_pct) for _, outcome in pairs]
    eligibility = assess_analysis_eligibility(
        len(pairs),
        original_company_count,
        criteria=eligibility_criteria,
    )
    return {
        "country": country,
        "original_company_count": original_company_count,
        "valid_company_count": len(pairs),
        "outcome_coverage_pct": eligibility.coverage_pct,
        "analysis_eligible": eligibility.eligible,
        "analysis_ineligibility_reasons": list(eligibility.reasons),
        "analysis_eligibility": eligibility.as_dict(),
        "metric_scope": (
            "analysis_eligible"
            if eligibility.eligible
            else "descriptive_partial"
        ),
        "equal_weight_return_pct": (
            statistics.fmean(returns) if returns else None
        ),
        "score_return_spearman_ic": spearman_rank_correlation(scores, returns),
        "final_rank_return_spearman_ic": spearman_rank_correlation(
            negative_ranks, returns
        ),
    }


def _run_gate_metrics(
    priced_pairs: list[tuple[EvaluationCompanyRow, MarketOutcome]],
) -> list[dict[str, Any]]:
    tiers: dict[str, list[float]] = defaultdict(list)
    for row, outcome in priced_pairs:
        tier = str((row.long_term or {}).get("gate_tier") or "Unknown")
        tiers[tier].append(float(outcome.raw_forward_return_pct))
    return [
        {
            "tier": tier,
            "observations": len(values),
            "mean_return_pct": statistics.fmean(values),
            "median_return_pct": statistics.median(values),
        }
        for tier, values in sorted(tiers.items())
    ]


def _aggregate_ic(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "run_count": 0,
            "mean": None,
            "median": None,
            "hit_rate_pct": None,
            "sample_standard_deviation": None,
            "information_ratio": None,
        }
    standard_deviation = statistics.stdev(values) if len(values) >= 2 else None
    mean_value = statistics.fmean(values)
    return {
        "run_count": len(values),
        "mean": mean_value,
        "median": statistics.median(values),
        "hit_rate_pct": (sum(value > 0 for value in values) / len(values)) * 100,
        "sample_standard_deviation": standard_deviation,
        "information_ratio": (
            mean_value / standard_deviation
            if standard_deviation not in (None, 0.0)
            else None
        ),
    }


def _aggregate_top_metrics(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    top_rows = [metric["top_vs_universe"] for metric in metrics]
    spreads = [
        row["top_decile_minus_universe_pct"]
        for row in top_rows
        if row["top_decile_minus_universe_pct"] is not None
    ]
    return {
        "mean_top_10_return_pct": _mean_present(
            row["top_10_average_return_pct"] for row in top_rows
        ),
        "mean_top_decile_return_pct": _mean_present(
            row["top_decile_average_return_pct"] for row in top_rows
        ),
        "mean_universe_return_pct": _mean_present(
            row["universe_average_return_pct"] for row in top_rows
        ),
        "mean_top_decile_minus_universe_pct": _mean_or_none(spreads),
        "mean_top_decile_minus_bottom_decile_pct": _mean_present(
            row["top_decile_minus_bottom_decile_pct"] for row in top_rows
        ),
        "positive_excess_hit_rate_pct": (
            (sum(value > 0 for value in spreads) / len(spreads)) * 100
            if spreads
            else None
        ),
    }


def _aggregate_bucket_schemes(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schemes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        if metric["bucket_count"]:
            schemes[metric["bucket_count"]].append(metric)
    results: list[dict[str, Any]] = []
    for bucket_count, scheme_metrics in sorted(schemes.items()):
        buckets: list[dict[str, Any]] = []
        for bucket in range(1, bucket_count + 1):
            rows = [
                row
                for metric in scheme_metrics
                for row in metric["buckets"]
                if row["bucket"] == bucket
            ]
            run_returns = [row["mean_return_pct"] for row in rows]
            run_excess = [row["mean_excess_vs_universe_pct"] for row in rows]
            buckets.append(
                {
                    "bucket": bucket,
                    "mean_return_pct": _mean_or_none(run_returns),
                    "median_return_pct": (
                        statistics.median(row["median_return_pct"] for row in rows)
                        if rows
                        else None
                    ),
                    "mean_excess_return_pct": _mean_present(run_excess),
                    "observations": sum(row["observations"] for row in rows),
                    "evaluation_dates": len(rows),
                }
            )
        results.append(
            {
                "bucket_count": bucket_count,
                "run_count": len(scheme_metrics),
                "monotonic_run_count": sum(
                    metric["bucket_returns_monotonic"] is True
                    for metric in scheme_metrics
                ),
                "buckets": buckets,
            }
        )
    return results


def _aggregate_gate_tiers(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        for row in metric["long_term_gate_tiers"]:
            rows_by_tier[row["tier"]].append(row)
    return [
        {
            "tier": tier,
            "mean_return_pct": statistics.fmean(
                row["mean_return_pct"] for row in rows
            ),
            "median_of_run_medians_pct": statistics.median(
                row["median_return_pct"] for row in rows
            ),
            "observations": sum(row["observations"] for row in rows),
            "evaluation_dates": len(rows),
        }
        for tier, rows in sorted(rows_by_tier.items())
    ]


def _aggregate_country_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        for row in metric["country_metrics"]:
            rows_by_country[row["country"]].append(
                {**row, "run_analysis_eligible": metric["analysis_eligible"]}
            )
    results = []
    for country, rows in sorted(rows_by_country.items()):
        eligible_rows = [
            row
            for row in rows
            if row["run_analysis_eligible"] and row["analysis_eligible"]
        ]
        score_ics = [
            row["score_return_spearman_ic"]
            for row in eligible_rows
            if row["score_return_spearman_ic"] is not None
        ]
        rank_ics = [
            row["final_rank_return_spearman_ic"]
            for row in eligible_rows
            if row["final_rank_return_spearman_ic"] is not None
        ]
        results.append(
            {
                "country": country,
                "due_evaluation_dates": len(rows),
                "evaluation_dates": len(eligible_rows),
                "analysis_eligible_run_count": len(eligible_rows),
                "partial_run_count": len(rows) - len(eligible_rows),
                "average_outcome_coverage_pct": _mean_or_none(
                    [row["outcome_coverage_pct"] for row in rows]
                ),
                "minimum_coverage_pct": rows[0]["analysis_eligibility"][
                    "minimum_coverage_pct"
                ],
                "minimum_valid_companies": rows[0]["analysis_eligibility"][
                    "minimum_valid_companies"
                ],
                "due_observations": sum(
                    row["valid_company_count"] for row in rows
                ),
                "observations": sum(
                    row["valid_company_count"] for row in eligible_rows
                ),
                "mean_equal_weight_return_pct": _mean_present(
                    row["equal_weight_return_pct"] for row in eligible_rows
                ),
                "score_ic": _aggregate_ic(score_ics),
                "final_rank_ic": _aggregate_ic(rank_ics),
            }
        )
    return results


def _missingness_diagnostics(outcomes: list[MarketOutcome]) -> dict[str, Any]:
    run_sizes = Counter(
        (outcome.evaluation_run_id, outcome.horizon_label) for outcome in outcomes
    )
    dimensions = {
        "strategy": lambda outcome: outcome.strategy,
        "country": lambda outcome: outcome.country,
        "segment": lambda outcome: outcome.segment,
        "rank_decile": lambda outcome: f"decile_{min(10, math.ceil(outcome.original_rank * 10 / max(1, run_sizes[(outcome.evaluation_run_id, outcome.horizon_label)])))}",
    }
    result: dict[str, Any] = {}
    for dimension, value_for in dimensions.items():
        grouped: dict[tuple[str, str, str, str], list[MarketOutcome]] = defaultdict(list)
        for outcome in outcomes:
            grouped[
                (
                    outcome.strategy,
                    outcome.scoring_model_version,
                    outcome.horizon_label,
                    value_for(outcome),
                )
            ].append(outcome)
        rows = []
        for (strategy, model, horizon, value), records in sorted(grouped.items()):
            statuses = Counter(record.status for record in records)
            due_count = len(records) - statuses.get("not_due", 0)
            priced = statuses.get("priced", 0)
            rows.append(
                {
                    "strategy": strategy,
                    "scoring_model_version": model,
                    "horizon": horizon,
                    dimension: value,
                    "records": len(records),
                    "due_records": due_count,
                    "priced_records": priced,
                    "due_coverage_pct": (
                        (priced / due_count) * 100 if due_count else None
                    ),
                    "status_counts": dict(sorted(statuses.items())),
                }
            )
        result[f"by_{dimension}"] = rows
    return result


def _validate_store_against_snapshot(
    snapshot: EvaluationSnapshot, store: EvaluationOutcomeSet
) -> None:
    if store.evaluation_run_id != snapshot.run_id:
        raise ValueError("outcome store run does not match evaluation snapshot")
    if store.strategy != snapshot.strategy:
        raise ValueError("outcome store strategy does not match evaluation snapshot")
    if store.scoring_model_version != snapshot.scoring_model_version:
        raise ValueError("outcome store model version does not match evaluation snapshot")


def _average_tied_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return tuple(ranks)


def _pearson_correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(left_delta, right_delta, strict=True)) / denominator


def _bucket_count(sample_size: int) -> int:
    if sample_size >= 50:
        return 10
    if sample_size >= 25:
        return 5
    if sample_size >= 10:
        return 2
    return 1 if sample_size else 0


def _bucket_returns_monotonic(buckets: list[dict[str, Any]]) -> bool | None:
    if len(buckets) < 2:
        return None
    values = [bucket["mean_return_pct"] for bucket in buckets]
    return all(left >= right for left, right in zip(values, values[1:], strict=False))


def _mean_or_none(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else None


def _mean_present(values: Iterable[float | None]) -> float | None:
    return _mean_or_none(value for value in values if value is not None)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_number(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _format_return(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _atomic_write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()
