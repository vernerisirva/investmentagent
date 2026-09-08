"""X defines cohorts and equal weights; Y can only attach observed returns."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from investmentagent.evaluation import EvaluationCompanyRow, EvaluationSnapshot
from investmentagent.evaluation_outcomes import MarketOutcome


ANALYSIS_METHODOLOGY = "fixed-decision-membership-v1"


def observed_returns(outcomes: Iterable[MarketOutcome]) -> dict[str, float]:
    result = {}
    for outcome in outcomes:
        if outcome.status == "priced":
            value = outcome.raw_forward_return_pct
            if value is None or not math.isfinite(value):
                raise ValueError("priced outcome requires a finite return")
            result[outcome.company_id] = float(value)
    return result


@dataclass(frozen=True)
class DecisionCohort:
    company_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.company_ids) != len(set(self.company_ids)):
            raise ValueError("duplicate decision-time cohort member")

    def observe(self, returns: Mapping[str, float]) -> dict[str, Any]:
        values = [returns[key] for key in self.company_ids if key in returns]
        size, priced = len(self.company_ids), len(values)
        mean = statistics.fmean(values) if values else None
        complete = bool(size) and priced == size
        return {
            "member_ids": list(self.company_ids),
            "decision_time_member_count": size,
            "priced_count": priced,
            "missing_count": size - priced,
            "coverage_pct": priced / size * 100 if size else 0.0,
            "weight_per_member": 1 / size if size else None,
            "observed_weight": priced / size if size else 0.0,
            "observed_mean_return_pct": mean,
            "observed_median_return_pct": statistics.median(values) if values else None,
            "exact_equal_weight_return_pct": mean if complete else None,
            "return_status": "complete" if complete else "incomplete" if size else "empty",
            "statistic_scope": "observed-member diagnostic; not a renormalized portfolio return",
        }


def bucket_count(population_size: int) -> int:
    if population_size >= 50:
        return 10
    if population_size >= 25:
        return 5
    if population_size >= 10:
        return 2
    return 1 if population_size else 0


@dataclass(frozen=True)
class DecisionMembership:
    rows: tuple[EvaluationCompanyRow, ...]
    ordered_ids: tuple[str, ...]

    @classmethod
    def from_snapshot(
        cls, snapshot: EvaluationSnapshot, *, ranks: Mapping[str, int] | None = None,
    ) -> DecisionMembership:
        by_id = {row.company_id: row for row in snapshot.rows}
        if ranks is None:
            ranks = {row.company_id: row.rank for row in snapshot.rows}
        if (set(ranks) != set(by_id)
                or sorted(ranks.values()) != list(range(1, len(by_id) + 1))):
            raise ValueError("decision-time ranks must cover the immutable evaluation universe")
        return cls(snapshot.rows, tuple(sorted(by_id, key=ranks.__getitem__)))

    @property
    def universe(self) -> DecisionCohort:
        return DecisionCohort(self.ordered_ids)

    @property
    def top_10(self) -> DecisionCohort:
        return DecisionCohort(self.ordered_ids[:10])

    @property
    def top_decile(self) -> DecisionCohort:
        size = math.ceil(len(self.ordered_ids) * 0.1)
        return DecisionCohort(self.ordered_ids[:size])

    @property
    def bottom_decile(self) -> DecisionCohort:
        size = math.ceil(len(self.ordered_ids) * 0.1)
        return DecisionCohort(self.ordered_ids[-size:] if size else ())

    @property
    def buckets(self) -> tuple[DecisionCohort, ...]:
        size = len(self.ordered_ids)
        count = bucket_count(size)
        # Preserve the existing floor boundary rule, now applied to the original N.
        return tuple(
            DecisionCohort(tuple(
                key for index, key in enumerate(self.ordered_ids)
                if index * count // size == bucket
            ))
            for bucket in range(count)
        )

    def groups(self, dimension: str) -> dict[str, DecisionCohort]:
        by_id = {row.company_id: row for row in self.rows}

        def value(key: str) -> str:
            row = by_id[key]
            if dimension == "gate_tier":
                return str((row.long_term or {}).get("gate_tier") or "Unknown")
            return getattr(row, dimension)

        return {
            group: DecisionCohort(tuple(key for key in self.ordered_ids if value(key) == group))
            for group in sorted({value(key) for key in self.ordered_ids})
        }


def recorded_public_portfolio(
    snapshot: EvaluationSnapshot, returns: Mapping[str, float],
) -> dict[str, Any]:
    """Production records its constrained selected prefix in X, not in outcome ranks."""
    size = snapshot.diagnostics.get("public_selection_size")
    limit = snapshot.configuration.get("public_limit")
    valid = (
        type(size) is int and type(limit) is int and limit > 0
        and size == min(limit, snapshot.universe_size)
        and all(row.eligible_universe_member for row in snapshot.rows[:size])
    )
    if not valid:
        return {
            "membership_status": "unavailable",
            "reason": "insufficient decision-time public selection evidence",
            "exact_equal_weight_return_pct": None,
        }
    return {
        "membership_status": "recorded",
        "membership_evidence": "immutable constrained rank prefix and public_selection_size",
        "selection_policy_version": None,
        "policy_status": "historical policy version not recorded in X; membership is recorded",
        **DecisionCohort(tuple(row.company_id for row in snapshot.rows[:size])).observe(returns),
    }


def cohort_diagnostic(cohort: DecisionCohort, returns: Mapping[str, float]) -> dict[str, Any]:
    observed = cohort.observe(returns)
    return {
        **observed,
        "observations": observed["priced_count"],
        "mean_return_pct": observed["observed_mean_return_pct"],
        "median_return_pct": observed["observed_median_return_pct"],
    }


def top_metrics(
    membership: DecisionMembership, returns: Mapping[str, float],
    universe_return: float | None,
) -> dict[str, Any]:
    cohorts = {
        name: getattr(membership, name).observe(returns)
        for name in ("top_10", "top_decile", "bottom_decile")
    }
    top = cohorts["top_decile"]["observed_mean_return_pct"]
    bottom = cohorts["bottom_decile"]["observed_mean_return_pct"]
    return {
        "cohorts": cohorts,
        "statistic_scope": "observed-member ranking diagnostics with fixed X membership; not exact portfolio returns",
        "top_10_average_return_pct": cohorts["top_10"]["observed_mean_return_pct"],
        "top_decile_count": cohorts["top_decile"]["decision_time_member_count"],
        "top_decile_average_return_pct": top,
        "top_decile_return_pct": top,
        "universe_average_return_pct": universe_return,
        "top_decile_minus_universe_pct": (
            top - universe_return if top is not None and universe_return is not None else None
        ),
        "top_decile_minus_bottom_decile_pct": (
            top - bottom if top is not None and bottom is not None else None
        ),
    }


def aggregate_coverage(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts are member-date observations, never a pooled-return estimator."""
    rows = tuple(rows)
    count = sum(row["decision_time_member_count"] for row in rows)
    priced = sum(row["priced_count"] for row in rows)
    return {
        "decision_time_member_observations": count,
        "priced_member_observations": priced,
        "missing_member_observations": count - priced,
        "coverage_pct": priced / count * 100 if count else 0.0,
        "complete_cohort_dates": sum(row["return_status"] == "complete" for row in rows),
        "statistic_scope": "run-level observed-member diagnostics; not exact portfolio returns",
    }
