from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from typing import Any, Iterable

from investmentagent.analysis_eligibility import (
    DEFAULT_ANALYSIS_ELIGIBILITY,
    AnalysisEligibilityCriteria,
    assess_analysis_eligibility,
)
from investmentagent.evaluation import EvaluationSnapshot
from investmentagent.evaluation_analysis import spearman_rank_correlation
from investmentagent.evaluation_outcomes import EvaluationOutcomeSet, MarketOutcome
from investmentagent.experiments import ChallengerExperimentSnapshot


MIN_RELIABLE_PAIRED_DATES = 20


def build_challenger_analysis(
    evaluations: Iterable[EvaluationSnapshot],
    outcome_sets: Iterable[EvaluationOutcomeSet],
    experiments: Iterable[ChallengerExperimentSnapshot],
    *,
    eligibility_criteria: AnalysisEligibilityCriteria = DEFAULT_ANALYSIS_ELIGIBILITY,
) -> dict[str, Any]:
    snapshots = tuple(evaluations)
    stores_by_run = {store.evaluation_run_id: store for store in outcome_sets}
    experiment_rows = tuple(experiments)
    experiments_by_key = {
        (
            experiment.base_evaluation_run_id,
            experiment.experiment_id,
            experiment.experiment_version,
        ): experiment
        for experiment in experiment_rows
    }
    if len(experiments_by_key) != len(experiment_rows):
        raise ValueError("duplicate challenger experiment for evaluation run")
    evaluations_by_run = {snapshot.run_id: snapshot for snapshot in snapshots}
    orphaned = {
        experiment.base_evaluation_run_id
        for experiment in experiment_rows
        if experiment.base_evaluation_run_id not in evaluations_by_run
    }
    if orphaned:
        raise ValueError(
            f"challenger experiment has no evaluation snapshot: {sorted(orphaned)[0]}"
        )

    run_statuses: list[dict[str, Any]] = []
    run_metrics: list[dict[str, Any]] = []
    experiments_by_run: dict[str, list[ChallengerExperimentSnapshot]] = defaultdict(list)
    for experiment in experiment_rows:
        experiments_by_run[experiment.base_evaluation_run_id].append(experiment)
    for evaluation in snapshots:
        if evaluation.strategy != "long-term":
            continue
        run_experiments = experiments_by_run.get(evaluation.run_id, [])
        if not run_experiments:
            run_statuses.append(
                {
                    "evaluation_run_id": evaluation.run_id,
                    "decision_at": _format_timestamp(evaluation.decision_at),
                    "status": "challenger not recorded",
                }
            )
            continue
        store = stores_by_run.get(evaluation.run_id)
        for experiment in run_experiments:
            _validate_experiment(evaluation, experiment)
            if store is None:
                run_statuses.append(
                    {
                        "evaluation_run_id": evaluation.run_id,
                        "experiment_id": experiment.experiment_id,
                        "experiment_version": experiment.experiment_version,
                        "decision_at": _format_timestamp(evaluation.decision_at),
                        "status": "outcomes not recorded",
                    }
                )
                continue
            _validate_outcomes(evaluation, store)
            run_statuses.append(
                {
                    "evaluation_run_id": evaluation.run_id,
                    "experiment_id": experiment.experiment_id,
                    "experiment_version": experiment.experiment_version,
                    "decision_at": _format_timestamp(evaluation.decision_at),
                    "status": "paired analysis available",
                }
            )
            for horizon in store.horizon_definitions:
                outcomes = tuple(
                    outcome
                    for outcome in store.outcomes
                    if outcome.horizon_label == horizon.label
                )
                run_metrics.append(
                    _analyze_paired_run(
                        evaluation,
                        experiment,
                        outcomes,
                        horizon.label,
                        horizon.sessions,
                        eligibility_criteria=eligibility_criteria,
                    )
                )

    groups = _aggregate_paired_runs(run_metrics)
    warnings = [
        (
            "Insufficient paired history to judge challenger performance. "
            f"{group['paired_completed_date_count']} completed dates for "
            f"{group['experiment_id']} v{group['experiment_version']} / "
            f"{group['horizon']['label']}."
        )
        for group in groups
        if group["paired_completed_date_count"] < MIN_RELIABLE_PAIRED_DATES
    ]
    warnings.extend(
        (
            "Insufficient paired outcome coverage: "
            f"{group['paired_partial_date_count']} due paired date(s) are "
            f"descriptive only for {group['experiment_id']} "
            f"v{group['experiment_version']} / {group['horizon']['label']}."
        )
        for group in groups
        if group["paired_partial_date_count"] > 0
    )
    if experiment_rows and not groups:
        warnings.append("Insufficient paired history to judge challenger performance.")
    return {
        "methodology": {
            "sample": (
                "champion and challenger use the exact same priced companies from "
                "the original evaluation run"
            ),
            "aggregation": "paired deltas are calculated per run before aggregation",
            "analysis_eligibility": eligibility_criteria.as_dict(),
            "automatic_promotion": False,
        },
        "reporting_criteria": [
            "positive mean and median paired IC delta",
            "paired IC improvement on more than half of completed dates",
            "improved top-decile-minus-universe spread",
            "no deterioration in paired outcome coverage",
            "ranking churn remains reasonable for a bounded factor experiment",
        ],
        "warnings": warnings,
        "recorded_sidecar_count": len(experiment_rows),
        "run_statuses": run_statuses,
        "run_metrics": run_metrics,
        "groups": groups,
    }


def _analyze_paired_run(
    evaluation: EvaluationSnapshot,
    experiment: ChallengerExperimentSnapshot,
    outcomes: tuple[MarketOutcome, ...],
    horizon_label: str,
    horizon_sessions: int,
    *,
    eligibility_criteria: AnalysisEligibilityCriteria,
) -> dict[str, Any]:
    evaluation_by_company = {row.company_id: row for row in evaluation.rows}
    experiment_by_company = {row.company_id: row for row in experiment.rows}
    outcomes_by_company = {outcome.company_id: outcome for outcome in outcomes}
    if set(outcomes_by_company) != set(evaluation_by_company):
        raise ValueError("paired outcome universe differs from evaluation universe")
    paired_company_ids = [
        row.company_id
        for row in evaluation.rows
        if outcomes_by_company[row.company_id].status == "priced"
    ]
    returns = [
        float(outcomes_by_company[company_id].raw_forward_return_pct)
        for company_id in paired_company_ids
    ]
    champion_scores = [
        evaluation_by_company[company_id].score["total"]
        for company_id in paired_company_ids
    ]
    champion_rank_signals = [
        -float(evaluation_by_company[company_id].rank)
        for company_id in paired_company_ids
    ]
    challenger_scores = [
        experiment_by_company[company_id].challenger_score
        for company_id in paired_company_ids
    ]
    challenger_rank_signals = [
        -float(experiment_by_company[company_id].challenger_rank)
        for company_id in paired_company_ids
    ]
    champion_score_ic = spearman_rank_correlation(champion_scores, returns)
    champion_rank_ic = spearman_rank_correlation(champion_rank_signals, returns)
    challenger_score_ic = spearman_rank_correlation(challenger_scores, returns)
    challenger_rank_ic = spearman_rank_correlation(challenger_rank_signals, returns)
    universe_return = statistics.fmean(returns) if returns else None
    champion_top = _top_metrics(
        paired_company_ids,
        returns,
        ranks={
            company_id: evaluation_by_company[company_id].rank
            for company_id in paired_company_ids
        },
        universe_return=universe_return,
    )
    challenger_top = _top_metrics(
        paired_company_ids,
        returns,
        ranks={
            company_id: experiment_by_company[company_id].challenger_rank
            for company_id in paired_company_ids
        },
        universe_return=universe_return,
    )
    statuses = {outcome.status for outcome in outcomes}
    is_due = statuses != {"not_due"}
    eligibility = assess_analysis_eligibility(
        len(paired_company_ids),
        evaluation.universe_size,
        criteria=eligibility_criteria,
    )
    analysis_eligible = is_due and eligibility.eligible
    churn = _ranking_churn(experiment)
    return {
        "evaluation_run_id": evaluation.run_id,
        "experiment_run_id": experiment.experiment_run_id,
        "experiment_id": experiment.experiment_id,
        "experiment_version": experiment.experiment_version,
        "strategy": evaluation.strategy,
        "champion_scoring_model_version": evaluation.scoring_model_version,
        "decision_at": _format_timestamp(evaluation.decision_at),
        "horizon": {
            "label": horizon_label,
            "sessions": horizon_sessions,
            "unit": "market_sessions",
        },
        "is_due": is_due,
        "original_universe_size": evaluation.universe_size,
        "paired_company_count": len(paired_company_ids),
        "paired_outcome_coverage_pct": (
            len(paired_company_ids) / evaluation.universe_size * 100
            if evaluation.universe_size
            else 0.0
        ),
        "analysis_eligible": analysis_eligible,
        "champion_analysis_eligible": analysis_eligible,
        "challenger_analysis_eligible": analysis_eligible,
        "analysis_ineligibility_reasons": (
            list(eligibility.reasons) if is_due else ["horizon is not due"]
        ),
        "analysis_eligibility": eligibility.as_dict(),
        "metric_scope": (
            "analysis_eligible" if analysis_eligible else "descriptive_partial"
        ),
        "paired_company_ids": paired_company_ids,
        "paired_sample_sha256": _sample_hash(paired_company_ids),
        "champion": {
            "score_return_ic": champion_score_ic,
            "final_rank_return_ic": champion_rank_ic,
            **champion_top,
        },
        "challenger": {
            "score_return_ic": challenger_score_ic,
            "rank_return_ic": challenger_rank_ic,
            **challenger_top,
        },
        "paired_deltas": {
            "score_ic": _difference(challenger_score_ic, champion_score_ic),
            "rank_ic": _difference(challenger_rank_ic, champion_rank_ic),
            "top_decile_return_pct": _difference(
                challenger_top["top_decile_return_pct"],
                champion_top["top_decile_return_pct"],
            ),
            "top_decile_minus_universe_pct": _difference(
                challenger_top["top_decile_minus_universe_pct"],
                champion_top["top_decile_minus_universe_pct"],
            ),
            "top_decile_minus_bottom_decile_pct": _difference(
                challenger_top["top_decile_minus_bottom_decile_pct"],
                champion_top["top_decile_minus_bottom_decile_pct"],
            ),
            "outcome_coverage_pct": 0.0,
        },
        "ranking_churn": churn,
        "factor_coverage_outcomes": _factor_coverage_outcomes(
            paired_company_ids,
            returns,
            experiment_by_company,
        ),
    }


def _aggregate_paired_runs(
    run_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, str, str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for metric in run_metrics:
        horizon = metric["horizon"]
        grouped[
            (
                metric["experiment_id"],
                metric["experiment_version"],
                metric["strategy"],
                metric["champion_scoring_model_version"],
                horizon["sessions"],
                horizon["label"],
            )
        ].append(metric)
    groups = []
    for key, metrics in sorted(grouped.items()):
        experiment_id, version, strategy, champion_model, sessions, label = key
        due = [metric for metric in metrics if metric["is_due"]]
        completed = [metric for metric in due if metric["analysis_eligible"]]
        partial = [metric for metric in due if not metric["analysis_eligible"]]
        groups.append(
            {
                "experiment_id": experiment_id,
                "experiment_version": version,
                "strategy": strategy,
                "champion_scoring_model_version": champion_model,
                "horizon": {
                    "label": label,
                    "sessions": sessions,
                    "unit": "market_sessions",
                },
                "recorded_run_count": len(metrics),
                "paired_due_date_count": len(due),
                "paired_completed_date_count": len(completed),
                "paired_analysis_eligible_date_count": len(completed),
                "paired_partial_date_count": len(partial),
                "average_paired_company_count": _mean(
                    metric["paired_company_count"] for metric in completed
                ),
                "average_paired_outcome_coverage_pct": _mean(
                    metric["paired_outcome_coverage_pct"] for metric in completed
                ),
                "average_due_paired_outcome_coverage_pct": _mean(
                    metric["paired_outcome_coverage_pct"] for metric in due
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
                "champion": {
                    "score_ic": _aggregate_values(
                        metric["champion"]["score_return_ic"] for metric in completed
                    ),
                    "final_rank_ic": _aggregate_values(
                        metric["champion"]["final_rank_return_ic"]
                        for metric in completed
                    ),
                    "mean_top_decile_minus_universe_pct": _mean(
                        metric["champion"]["top_decile_minus_universe_pct"]
                        for metric in completed
                    ),
                },
                "challenger": {
                    "score_ic": _aggregate_values(
                        metric["challenger"]["score_return_ic"]
                        for metric in completed
                    ),
                    "rank_ic": _aggregate_values(
                        metric["challenger"]["rank_return_ic"]
                        for metric in completed
                    ),
                    "mean_top_decile_minus_universe_pct": _mean(
                        metric["challenger"]["top_decile_minus_universe_pct"]
                        for metric in completed
                    ),
                },
                "paired_deltas": {
                    "score_ic": _aggregate_values(
                        metric["paired_deltas"]["score_ic"] for metric in completed
                    ),
                    "rank_ic": _aggregate_values(
                        metric["paired_deltas"]["rank_ic"] for metric in completed
                    ),
                    "top_decile_minus_universe_pct": _aggregate_values(
                        metric["paired_deltas"]["top_decile_minus_universe_pct"]
                        for metric in completed
                    ),
                    "top_decile_minus_bottom_decile_pct": _aggregate_values(
                        metric["paired_deltas"]["top_decile_minus_bottom_decile_pct"]
                        for metric in completed
                    ),
                    "outcome_coverage_pct": _aggregate_values(
                        metric["paired_deltas"]["outcome_coverage_pct"]
                        for metric in completed
                    ),
                },
                "ranking_churn": {
                    "mean_absolute_rank_change": _mean(
                        metric["ranking_churn"]["mean_absolute_rank_change"]
                        for metric in completed
                    ),
                    "median_absolute_rank_change": (
                        statistics.median(
                            metric["ranking_churn"]["median_absolute_rank_change"]
                            for metric in completed
                        )
                        if completed
                        else None
                    ),
                    "mean_top_10_overlap_pct": _mean(
                        metric["ranking_churn"]["top_10_overlap_pct"]
                        for metric in completed
                    ),
                    "mean_top_decile_overlap_pct": _mean(
                        metric["ranking_churn"]["top_decile_overlap_pct"]
                        for metric in completed
                    ),
                },
                "sample_warning": len(completed) < MIN_RELIABLE_PAIRED_DATES,
            }
        )
    return groups


def _top_metrics(
    company_ids: list[str],
    returns: list[float],
    *,
    ranks: dict[str, int],
    universe_return: float | None,
) -> dict[str, Any]:
    by_company = dict(zip(company_ids, returns, strict=True))
    ordered = sorted(company_ids, key=lambda company_id: ranks[company_id])
    if not ordered:
        return {
            "top_decile_return_pct": None,
            "top_decile_minus_universe_pct": None,
            "top_decile_minus_bottom_decile_pct": None,
        }
    decile_size = max(1, math.ceil(len(ordered) * 0.1))
    top_return = statistics.fmean(by_company[item] for item in ordered[:decile_size])
    bottom_return = statistics.fmean(
        by_company[item] for item in ordered[-decile_size:]
    )
    return {
        "top_decile_return_pct": top_return,
        "top_decile_minus_universe_pct": (
            top_return - universe_return if universe_return is not None else None
        ),
        "top_decile_minus_bottom_decile_pct": top_return - bottom_return,
    }


def _ranking_churn(experiment: ChallengerExperimentSnapshot) -> dict[str, Any]:
    absolute_changes = [abs(row.rank_delta) for row in experiment.rows]
    universe_size = len(experiment.rows)
    top_10_size = min(10, universe_size)
    top_decile_size = max(1, math.ceil(universe_size * 0.1)) if universe_size else 0
    champion_top_10 = {
        row.company_id for row in experiment.rows if row.champion_rank <= top_10_size
    }
    challenger_top_10 = {
        row.company_id for row in experiment.rows if row.challenger_rank <= top_10_size
    }
    champion_top_decile = {
        row.company_id
        for row in experiment.rows
        if row.champion_rank <= top_decile_size
    }
    challenger_top_decile = {
        row.company_id
        for row in experiment.rows
        if row.challenger_rank <= top_decile_size
    }
    promoted = sorted(
        experiment.rows,
        key=lambda row: (-row.rank_delta, row.ticker, row.company_id),
    )[:5]
    demoted = sorted(
        experiment.rows,
        key=lambda row: (row.rank_delta, row.ticker, row.company_id),
    )[:5]
    return {
        "mean_absolute_rank_change": (
            statistics.fmean(absolute_changes) if absolute_changes else 0.0
        ),
        "median_absolute_rank_change": (
            statistics.median(absolute_changes) if absolute_changes else 0.0
        ),
        "top_10_size": top_10_size,
        "top_10_overlap_count": len(champion_top_10 & challenger_top_10),
        "top_10_overlap_pct": (
            len(champion_top_10 & challenger_top_10) / top_10_size * 100
            if top_10_size
            else None
        ),
        "top_decile_size": top_decile_size,
        "top_decile_overlap_count": len(
            champion_top_decile & challenger_top_decile
        ),
        "top_decile_overlap_pct": (
            len(champion_top_decile & challenger_top_decile)
            / top_decile_size
            * 100
            if top_decile_size
            else None
        ),
        "most_promoted": [_rank_change_payload(row) for row in promoted],
        "most_demoted": [_rank_change_payload(row) for row in demoted],
    }


def _factor_coverage_outcomes(
    company_ids: list[str],
    returns: list[float],
    experiment_by_company: dict[str, Any],
) -> list[dict[str, Any]]:
    values_by_count: dict[int, list[float]] = defaultdict(list)
    for company_id, forward_return in zip(company_ids, returns, strict=True):
        values_by_count[experiment_by_company[company_id].usable_metric_count].append(
            forward_return
        )
    return [
        {
            "usable_metric_count": count,
            "companies": len(values),
            "mean_return_pct": statistics.fmean(values),
            "median_return_pct": statistics.median(values),
        }
        for count, values in sorted(values_by_count.items())
    ]


def _validate_experiment(
    evaluation: EvaluationSnapshot,
    experiment: ChallengerExperimentSnapshot,
) -> None:
    if experiment.base_evaluation_run_id != evaluation.run_id:
        raise ValueError("challenger experiment links to another evaluation")
    if experiment.strategy != evaluation.strategy:
        raise ValueError("challenger experiment strategy mismatch")
    if experiment.champion_scoring_model_version != evaluation.scoring_model_version:
        raise ValueError("challenger experiment champion-model mismatch")
    if experiment.decision_at != evaluation.decision_at:
        raise ValueError("challenger experiment decision timestamp mismatch")
    evaluation_by_company = {row.company_id: row for row in evaluation.rows}
    experiment_by_company = {row.company_id: row for row in experiment.rows}
    if set(evaluation_by_company) != set(experiment_by_company):
        raise ValueError("challenger experiment universe mismatch")
    for company_id, row in experiment_by_company.items():
        evaluation_row = evaluation_by_company[company_id]
        if (
            row.champion_rank != evaluation_row.rank
            or not math.isclose(
                row.champion_score,
                evaluation_row.score["total"],
                abs_tol=1e-12,
            )
            or row.long_term_gate_tier
            != (evaluation_row.long_term or {}).get("gate_tier")
        ):
            raise ValueError("challenger experiment changed champion metadata")


def _validate_outcomes(
    evaluation: EvaluationSnapshot, store: EvaluationOutcomeSet
) -> None:
    if store.evaluation_run_id != evaluation.run_id:
        raise ValueError("paired outcome store links to another evaluation")
    if store.scoring_model_version != evaluation.scoring_model_version:
        raise ValueError("paired outcome model version mismatch")


def _rank_change_payload(row: Any) -> dict[str, Any]:
    return {
        "company_id": row.company_id,
        "ticker": row.ticker,
        "champion_rank": row.champion_rank,
        "challenger_rank": row.challenger_rank,
        "rank_delta": row.rank_delta,
    }


def _aggregate_values(values: Iterable[float | None]) -> dict[str, Any]:
    present = [value for value in values if value is not None]
    return {
        "run_count": len(present),
        "mean": statistics.fmean(present) if present else None,
        "median": statistics.median(present) if present else None,
        "positive_date_pct": (
            sum(value > 0 for value in present) / len(present) * 100
            if present
            else None
        ),
    }


def _mean(values: Iterable[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _difference(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def _sample_hash(company_ids: list[str]) -> str:
    canonical = "\n".join(sorted(company_ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _format_timestamp(value) -> str:
    return value.isoformat().replace("+00:00", "Z")
