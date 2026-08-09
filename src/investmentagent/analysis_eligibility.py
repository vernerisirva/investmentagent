from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisEligibilityCriteria:
    minimum_coverage_pct: float
    minimum_valid_companies: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_coverage_pct, bool)
            or not isinstance(self.minimum_coverage_pct, (int, float))
            or not math.isfinite(self.minimum_coverage_pct)
            or not 0.0 <= self.minimum_coverage_pct <= 100.0
        ):
            raise ValueError("minimum analysis coverage must be between 0 and 100")
        if (
            isinstance(self.minimum_valid_companies, bool)
            or not isinstance(self.minimum_valid_companies, int)
            or self.minimum_valid_companies < 1
        ):
            raise ValueError("minimum analysis sample must be a positive integer")

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimum_coverage_pct": float(self.minimum_coverage_pct),
            "minimum_valid_companies": self.minimum_valid_companies,
            "purpose": (
                "research-quality aggregation guardrail; not a statistical-significance threshold"
            ),
        }


@dataclass(frozen=True)
class AnalysisEligibility:
    eligible: bool
    valid_company_count: int
    original_company_count: int
    coverage_pct: float
    minimum_coverage_pct: float
    minimum_valid_companies: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "valid_company_count": self.valid_company_count,
            "original_company_count": self.original_company_count,
            "coverage_pct": self.coverage_pct,
            "minimum_coverage_pct": self.minimum_coverage_pct,
            "minimum_valid_companies": self.minimum_valid_companies,
            "reasons": list(self.reasons),
        }


DEFAULT_ANALYSIS_ELIGIBILITY = AnalysisEligibilityCriteria(
    minimum_coverage_pct=70.0,
    minimum_valid_companies=50,
)
DEFAULT_COUNTRY_ANALYSIS_ELIGIBILITY = AnalysisEligibilityCriteria(
    minimum_coverage_pct=70.0,
    minimum_valid_companies=20,
)


def assess_analysis_eligibility(
    valid_company_count: int,
    original_company_count: int,
    *,
    criteria: AnalysisEligibilityCriteria = DEFAULT_ANALYSIS_ELIGIBILITY,
) -> AnalysisEligibility:
    for value, label in (
        (valid_company_count, "valid company count"),
        (original_company_count, "original company count"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
    if valid_company_count > original_company_count:
        raise ValueError("valid company count cannot exceed original company count")
    coverage_pct = (
        valid_company_count / original_company_count * 100.0
        if original_company_count
        else 0.0
    )
    reasons = []
    if coverage_pct < criteria.minimum_coverage_pct:
        reasons.append(
            f"outcome coverage {coverage_pct:.1f}% is below "
            f"{criteria.minimum_coverage_pct:g}%"
        )
    if valid_company_count < criteria.minimum_valid_companies:
        reasons.append(
            f"valid company count {valid_company_count} is below "
            f"{criteria.minimum_valid_companies}"
        )
    return AnalysisEligibility(
        eligible=not reasons,
        valid_company_count=valid_company_count,
        original_company_count=original_company_count,
        coverage_pct=coverage_pct,
        minimum_coverage_pct=float(criteria.minimum_coverage_pct),
        minimum_valid_companies=criteria.minimum_valid_companies,
        reasons=tuple(reasons),
    )
