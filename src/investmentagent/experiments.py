from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from investmentagent.evaluation import EvaluationSnapshot
from investmentagent.fundamentals_cache import company_cache_identity
from investmentagent.long_term_quality import LongTermGateTier, assess_long_term_gate
from investmentagent.reports import WatchlistBuildResult


EXPERIMENT_SCHEMA_VERSION = 1
RELATIVE_VALUATION_EXPERIMENT_ID = "relative-valuation-v1"
RELATIVE_VALUATION_EXPERIMENT_VERSION = 1
RELATIVE_VALUATION_HYPOTHESIS = (
    "Within the same long-term gate tier, companies that are relatively cheaper "
    "than other companies available at the same decision time will subsequently "
    "outperform otherwise similarly ranked companies."
)
VALUATION_METRICS = ("pe_ratio", "price_to_book", "ev_to_ebit")
MIN_COUNTRY_NORMALIZATION_SAMPLE = 5
MIN_UNIVERSE_NORMALIZATION_SAMPLE = 3
MAX_RELATIVE_VALUATION_ADJUSTMENT = 6.0

_GATE_ORDER = {
    LongTermGateTier.HIGH_CONVICTION.value: 0,
    LongTermGateTier.FUNDAMENTAL_WATCHLIST.value: 1,
    LongTermGateTier.SPECULATIVE_MONITOR.value: 2,
    LongTermGateTier.INSUFFICIENT_EVIDENCE.value: 3,
}


@dataclass(frozen=True)
class ChallengerExperimentDefinition:
    experiment_id: str
    experiment_version: int
    name: str
    strategy: str
    champion_scoring_model_version: str
    hypothesis: str
    valuation_metrics: tuple[str, ...]
    country_minimum_sample: int
    universe_minimum_sample: int
    maximum_adjustment: float

    def as_configuration(self) -> dict[str, Any]:
        return {
            "valuation_metrics": list(self.valuation_metrics),
            "valid_observation": "finite and strictly positive",
            "metric_percentile": (
                "average-tied ascending rank transformed so lower multiple is better"
            ),
            "factor_composite": "mean centered percentile across participating metrics",
            "factor_score_range": [-1.0, 1.0],
            "adjustment_range": [-self.maximum_adjustment, self.maximum_adjustment],
            "country_minimum_sample": self.country_minimum_sample,
            "universe_minimum_sample": self.universe_minimum_sample,
            "country_fallback": "full contemporaneous eligible universe",
            "missing_treatment": "neutral zero adjustment",
            "ranking_order": [
                "production long-term gate tier",
                "challenger total descending",
                "ticker ascending",
                "company_id ascending",
            ],
            "adjustment_scale_rationale": (
                "six points is below the production seven-point partial-data penalty "
                "and common eight-to-ten-point components, but can reorder close peers"
            ),
        }


RELATIVE_VALUATION_V1 = ChallengerExperimentDefinition(
    experiment_id=RELATIVE_VALUATION_EXPERIMENT_ID,
    experiment_version=RELATIVE_VALUATION_EXPERIMENT_VERSION,
    name="Continuous Relative Valuation",
    strategy="long-term",
    champion_scoring_model_version="nordic-ranking-v1",
    hypothesis=RELATIVE_VALUATION_HYPOTHESIS,
    valuation_metrics=VALUATION_METRICS,
    country_minimum_sample=MIN_COUNTRY_NORMALIZATION_SAMPLE,
    universe_minimum_sample=MIN_UNIVERSE_NORMALIZATION_SAMPLE,
    maximum_adjustment=MAX_RELATIVE_VALUATION_ADJUSTMENT,
)


@dataclass(frozen=True)
class ChallengerExperimentRow:
    company_id: str
    ticker: str
    country: str
    champion_score: float
    champion_rank: int
    long_term_gate_tier: str
    challenger_factor_score: float | None
    challenger_adjustment: float
    challenger_score: float
    challenger_rank: int
    rank_delta: int
    positive_metric_count: int
    usable_metric_count: int
    participating_metrics: tuple[str, ...]
    normalization_scope_by_metric: dict[str, str]
    unavailable_reason_by_metric: dict[str, str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "ticker": self.ticker,
            "country": self.country,
            "champion_score": self.champion_score,
            "champion_rank": self.champion_rank,
            "long_term_gate_tier": self.long_term_gate_tier,
            "challenger_factor_score": self.challenger_factor_score,
            "challenger_adjustment": self.challenger_adjustment,
            "challenger_score": self.challenger_score,
            "challenger_rank": self.challenger_rank,
            "rank_delta": self.rank_delta,
            "factor_coverage": {
                "positive_metric_count": self.positive_metric_count,
                "usable_metric_count": self.usable_metric_count,
                "participating_metrics": list(self.participating_metrics),
                "normalization_scope_by_metric": self.normalization_scope_by_metric,
                "unavailable_reason_by_metric": self.unavailable_reason_by_metric,
            },
        }


@dataclass(frozen=True)
class ChallengerExperimentSnapshot:
    schema_version: int
    experiment_run_id: str
    experiment_id: str
    experiment_version: int
    experiment_name: str
    base_evaluation_run_id: str
    champion_scoring_model_version: str
    strategy: str
    decision_at: datetime
    report_date: date
    hypothesis: str
    factor_configuration: dict[str, Any]
    universe_size: int
    diagnostics: dict[str, Any]
    rows: tuple[ChallengerExperimentRow, ...]

    def __post_init__(self) -> None:
        if self.schema_version != EXPERIMENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported challenger-experiment schema: {self.schema_version}"
            )
        if self.strategy != "long-term":
            raise ValueError("challenger experiment supports long-term strategy only")
        if self.decision_at.tzinfo is None:
            raise ValueError("experiment decision timestamp must be timezone-aware")
        object.__setattr__(self, "decision_at", self.decision_at.astimezone(timezone.utc))
        if self.universe_size != len(self.rows):
            raise ValueError("experiment universe size does not match rows")
        company_ids = [row.company_id for row in self.rows]
        if len(company_ids) != len(set(company_ids)):
            raise ValueError("experiment company identities must be unique")
        champion_ranks = [row.champion_rank for row in self.rows]
        if champion_ranks != list(range(1, len(self.rows) + 1)):
            raise ValueError("experiment rows must retain sequential champion ranks")
        challenger_ranks = sorted(row.challenger_rank for row in self.rows)
        if challenger_ranks != list(range(1, len(self.rows) + 1)):
            raise ValueError("challenger ranks must be sequential")
        maximum_adjustment = _maximum_adjustment(self.factor_configuration)
        for row in self.rows:
            if abs(row.challenger_adjustment) > maximum_adjustment + 1e-12:
                raise ValueError("challenger adjustment exceeds configured bound")
            if not math.isclose(
                row.challenger_score,
                row.champion_score + row.challenger_adjustment,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError("challenger score does not match its adjustment")
            if row.rank_delta != row.champion_rank - row.challenger_rank:
                raise ValueError("challenger rank delta is inconsistent")
            if row.usable_metric_count != len(row.participating_metrics):
                raise ValueError("experiment factor coverage is inconsistent")
            if row.challenger_factor_score is None:
                if row.challenger_adjustment != 0.0 or row.usable_metric_count != 0:
                    raise ValueError("unavailable factor must have a neutral adjustment")
            elif not -1.0 <= row.challenger_factor_score <= 1.0:
                raise ValueError("challenger factor score must be within [-1, 1]")
        ordered_by_challenger = sorted(self.rows, key=lambda row: row.challenger_rank)
        gate_orders = [_gate_order(row.long_term_gate_tier) for row in ordered_by_challenger]
        if gate_orders != sorted(gate_orders):
            raise ValueError("challenger ranking cannot cross long-term gate tiers")
        expected_id = experiment_run_id(
            self.base_evaluation_run_id,
            self.experiment_id,
            self.experiment_version,
        )
        if self.experiment_run_id != expected_id:
            raise ValueError("challenger experiment identity does not match metadata")

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_run_id": self.experiment_run_id,
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "experiment_name": self.experiment_name,
            "base_evaluation_run_id": self.base_evaluation_run_id,
            "champion_scoring_model_version": self.champion_scoring_model_version,
            "strategy": self.strategy,
            "decision_at": _format_timestamp(self.decision_at),
            "report_date": self.report_date.isoformat(),
            "hypothesis": self.hypothesis,
            "factor_configuration": self.factor_configuration,
            "universe_size": self.universe_size,
            "diagnostics": self.diagnostics,
            "rows": [row.as_payload() for row in self.rows],
        }


def build_challenger_experiment_snapshot(
    result: WatchlistBuildResult,
    evaluation: EvaluationSnapshot,
    *,
    definition: ChallengerExperimentDefinition = RELATIVE_VALUATION_V1,
) -> ChallengerExperimentSnapshot:
    if evaluation.strategy != definition.strategy:
        raise ValueError("challenger definition does not support this evaluation strategy")
    if evaluation.scoring_model_version != definition.champion_scoring_model_version:
        raise ValueError("challenger definition does not support this champion model")
    if len(result.ranked_items) != evaluation.universe_size:
        raise ValueError("challenger input universe differs from production evaluation")
    evaluation_rows = {row.company_id: row for row in evaluation.rows}
    item_by_company_id = {
        company_cache_identity(item.research.company): item
        for item in result.ranked_items
    }
    if set(item_by_company_id) != set(evaluation_rows):
        raise ValueError("challenger companies differ from production evaluation")
    for company_id, item in item_by_company_id.items():
        evaluation_row = evaluation_rows[company_id]
        if (
            evaluation_row.rank != item.rank
            or not math.isclose(
                evaluation_row.score["total"], item.score.total, abs_tol=1e-12
            )
        ):
            raise ValueError("challenger input does not match production ranks and scores")

    normalized_metrics = _normalized_metric_scores(
        result,
        definition=definition,
    )
    rows_without_challenger_rank: list[ChallengerExperimentRow] = []
    for item in result.ranked_items:
        company = item.research.company
        company_id = company_cache_identity(company)
        available = {
            metric
            for metric in definition.valuation_metrics
            if _positive_finite(getattr(item.research.financials, metric))
        }
        participating = tuple(
            metric
            for metric in definition.valuation_metrics
            if (company_id, metric) in normalized_metrics
        )
        metric_results = [normalized_metrics[(company_id, metric)] for metric in participating]
        factor_score = (
            round(statistics.fmean(result[0] for result in metric_results), 8)
            if metric_results
            else None
        )
        adjustment = (
            round(factor_score * definition.maximum_adjustment, 8)
            if factor_score is not None
            else 0.0
        )
        challenger_score = round(item.score.total + adjustment, 8)
        normalization = {
            metric: normalized_metrics[(company_id, metric)][1]
            for metric in participating
        }
        unavailable = {
            metric: (
                "insufficient_cross_section"
                if metric in available
                else "missing_or_non_positive"
            )
            for metric in definition.valuation_metrics
            if metric not in participating
        }
        gate_tier = assess_long_term_gate(item.research).tier.value
        if gate_tier != evaluation_rows[company_id].long_term["gate_tier"]:
            raise ValueError("challenger gate differs from production evaluation")
        rows_without_challenger_rank.append(
            ChallengerExperimentRow(
                company_id=company_id,
                ticker=company.ticker,
                country=company.country,
                champion_score=item.score.total,
                champion_rank=item.rank,
                long_term_gate_tier=gate_tier,
                challenger_factor_score=factor_score,
                challenger_adjustment=adjustment,
                challenger_score=challenger_score,
                challenger_rank=0,
                rank_delta=0,
                positive_metric_count=len(available),
                usable_metric_count=len(participating),
                participating_metrics=participating,
                normalization_scope_by_metric=normalization,
                unavailable_reason_by_metric=unavailable,
            )
        )

    ranked_challenger = sorted(
        rows_without_challenger_rank,
        key=lambda row: (
            _gate_order(row.long_term_gate_tier),
            -row.challenger_score,
            row.ticker,
            row.company_id,
        ),
    )
    challenger_rank_by_company = {
        row.company_id: rank for rank, row in enumerate(ranked_challenger, start=1)
    }
    rows = tuple(
        replace(
            row,
            challenger_rank=challenger_rank_by_company[row.company_id],
            rank_delta=row.champion_rank - challenger_rank_by_company[row.company_id],
        )
        for row in rows_without_challenger_rank
    )
    diagnostics = _factor_diagnostics(rows)
    return ChallengerExperimentSnapshot(
        schema_version=EXPERIMENT_SCHEMA_VERSION,
        experiment_run_id=experiment_run_id(
            evaluation.run_id,
            definition.experiment_id,
            definition.experiment_version,
        ),
        experiment_id=definition.experiment_id,
        experiment_version=definition.experiment_version,
        experiment_name=definition.name,
        base_evaluation_run_id=evaluation.run_id,
        champion_scoring_model_version=evaluation.scoring_model_version,
        strategy=evaluation.strategy,
        decision_at=evaluation.decision_at,
        report_date=evaluation.report_date,
        hypothesis=definition.hypothesis,
        factor_configuration=definition.as_configuration(),
        universe_size=len(rows),
        diagnostics=diagnostics,
        rows=rows,
    )


def experiment_run_id(
    base_evaluation_run_id: str,
    experiment_id: str,
    experiment_version: int,
) -> str:
    identity = json.dumps(
        {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "base_evaluation_run_id": base_evaluation_run_id,
            "experiment_id": experiment_id,
            "experiment_version": experiment_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"experiment-{digest}"


def experiment_snapshot_path(
    root: Path, snapshot: ChallengerExperimentSnapshot
) -> Path:
    return (
        root
        / snapshot.report_date.isoformat()
        / snapshot.strategy
        / snapshot.experiment_id
        / f"{snapshot.experiment_run_id}.json"
    )


def save_experiment_snapshot(
    root: Path, snapshot: ChallengerExperimentSnapshot
) -> Path:
    path = experiment_snapshot_path(root, snapshot)
    content = serialize_experiment_snapshot(snapshot)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return path
        raise ValueError(
            f"challenger experiment identity conflict: {snapshot.experiment_run_id}"
        )
    _atomic_write(path, content)
    return path


def serialize_experiment_snapshot(snapshot: ChallengerExperimentSnapshot) -> str:
    return json.dumps(
        snapshot.as_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def load_experiment_snapshot(path: Path) -> ChallengerExperimentSnapshot:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed challenger experiment snapshot: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("malformed challenger experiment payload")
    version = payload.get("schema_version")
    if version != EXPERIMENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported challenger-experiment schema: {version}")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("malformed challenger experiment rows")
    return ChallengerExperimentSnapshot(
        schema_version=version,
        experiment_run_id=_required_string(payload.get("experiment_run_id"), "run ID"),
        experiment_id=_required_string(payload.get("experiment_id"), "experiment ID"),
        experiment_version=_required_int(payload.get("experiment_version"), "version"),
        experiment_name=_required_string(payload.get("experiment_name"), "name"),
        base_evaluation_run_id=_required_string(
            payload.get("base_evaluation_run_id"), "base evaluation run ID"
        ),
        champion_scoring_model_version=_required_string(
            payload.get("champion_scoring_model_version"), "champion model"
        ),
        strategy=_required_string(payload.get("strategy"), "strategy"),
        decision_at=_parse_timestamp(payload.get("decision_at")),
        report_date=date.fromisoformat(
            _required_string(payload.get("report_date"), "report date")
        ),
        hypothesis=_required_string(payload.get("hypothesis"), "hypothesis"),
        factor_configuration=_required_dict(
            payload.get("factor_configuration"), "factor configuration"
        ),
        universe_size=_required_int(payload.get("universe_size"), "universe size"),
        diagnostics=_required_dict(payload.get("diagnostics"), "diagnostics"),
        rows=tuple(_row_from_payload(row) for row in raw_rows),
    )


def discover_experiment_snapshots(
    root: Path,
    *,
    experiment_id: str | None = None,
    run_id: str | None = None,
) -> tuple[ChallengerExperimentSnapshot, ...]:
    if not root.exists():
        return ()
    snapshots = []
    seen = set()
    for path in sorted(root.rglob("*.json")):
        snapshot = load_experiment_snapshot(path)
        if experiment_id is not None and snapshot.experiment_id != experiment_id:
            continue
        if run_id is not None and snapshot.base_evaluation_run_id != run_id:
            continue
        if snapshot.experiment_run_id in seen:
            raise ValueError(
                f"duplicate challenger experiment: {snapshot.experiment_run_id}"
            )
        seen.add(snapshot.experiment_run_id)
        snapshots.append(snapshot)
    return tuple(
        sorted(
            snapshots,
            key=lambda item: (
                item.decision_at,
                item.experiment_id,
                item.experiment_version,
            ),
        )
    )


def _normalized_metric_scores(
    result: WatchlistBuildResult,
    *,
    definition: ChallengerExperimentDefinition,
) -> dict[tuple[str, str], tuple[float, str]]:
    normalized: dict[tuple[str, str], tuple[float, str]] = {}
    for metric in definition.valuation_metrics:
        observations = [
            (
                company_cache_identity(item.research.company),
                item.research.company.country,
                float(value),
            )
            for item in result.ranked_items
            if _positive_finite(value := getattr(item.research.financials, metric))
        ]
        universe_scores = (
            _centered_cheapness_scores(observations)
            if len(observations) >= definition.universe_minimum_sample
            else {}
        )
        countries = sorted({country for _, country, _ in observations})
        country_scores = {}
        for country in countries:
            country_observations = [
                observation
                for observation in observations
                if observation[1] == country
            ]
            if len(country_observations) >= definition.country_minimum_sample:
                country_scores[country] = _centered_cheapness_scores(
                    country_observations
                )
        for company_id, country, _ in observations:
            if country in country_scores:
                normalized[(company_id, metric)] = (
                    country_scores[country][company_id],
                    "country",
                )
            elif company_id in universe_scores:
                normalized[(company_id, metric)] = (
                    universe_scores[company_id],
                    "universe_fallback",
                )
    return normalized


def _centered_cheapness_scores(
    observations: list[tuple[str, str, float]],
) -> dict[str, float]:
    ordered = sorted(observations, key=lambda item: (item[2], item[0]))
    count = len(ordered)
    scores: dict[str, float] = {}
    start = 0
    while start < count:
        end = start + 1
        while end < count and ordered[end][2] == ordered[start][2]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        percentile = (count - average_rank) / (count - 1)
        centered = (percentile - 0.5) * 2.0
        for position in range(start, end):
            scores[ordered[position][0]] = centered
        start = end
    return scores


def _factor_diagnostics(
    rows: tuple[ChallengerExperimentRow, ...]
) -> dict[str, Any]:
    usable_counts = {
        str(count): sum(row.usable_metric_count == count for row in rows)
        for count in range(len(VALUATION_METRICS) + 1)
    }
    return {
        "companies_by_usable_metric_count": usable_counts,
        "companies_with_country_normalization": sum(
            "country" in row.normalization_scope_by_metric.values() for row in rows
        ),
        "companies_with_universe_fallback": sum(
            "universe_fallback" in row.normalization_scope_by_metric.values()
            for row in rows
        ),
        "country_normalized_metric_assignments": sum(
            scope == "country"
            for row in rows
            for scope in row.normalization_scope_by_metric.values()
        ),
        "universe_fallback_metric_assignments": sum(
            scope == "universe_fallback"
            for row in rows
            for scope in row.normalization_scope_by_metric.values()
        ),
    }


def _row_from_payload(value: Any) -> ChallengerExperimentRow:
    if not isinstance(value, dict):
        raise ValueError("malformed challenger experiment row")
    coverage = _required_dict(value.get("factor_coverage"), "factor coverage")
    participating = _required_string_list(
        coverage.get("participating_metrics"), "participating metrics"
    )
    normalization = _required_string_dict(
        coverage.get("normalization_scope_by_metric"), "normalization scopes"
    )
    unavailable = _required_string_dict(
        coverage.get("unavailable_reason_by_metric"), "unavailable reasons"
    )
    return ChallengerExperimentRow(
        company_id=_required_string(value.get("company_id"), "company ID"),
        ticker=_required_string(value.get("ticker"), "ticker"),
        country=_required_string(value.get("country"), "country"),
        champion_score=_required_number(value.get("champion_score"), "champion score"),
        champion_rank=_required_int(value.get("champion_rank"), "champion rank"),
        long_term_gate_tier=_required_string(
            value.get("long_term_gate_tier"), "gate tier"
        ),
        challenger_factor_score=_optional_number(value.get("challenger_factor_score")),
        challenger_adjustment=_required_number(
            value.get("challenger_adjustment"), "challenger adjustment"
        ),
        challenger_score=_required_number(
            value.get("challenger_score"), "challenger score"
        ),
        challenger_rank=_required_int(value.get("challenger_rank"), "challenger rank"),
        rank_delta=_required_signed_int(value.get("rank_delta"), "rank delta"),
        positive_metric_count=_required_int(
            coverage.get("positive_metric_count"), "positive metric count"
        ),
        usable_metric_count=_required_int(
            coverage.get("usable_metric_count"), "usable metric count"
        ),
        participating_metrics=tuple(participating),
        normalization_scope_by_metric=normalization,
        unavailable_reason_by_metric=unavailable,
    )


def _gate_order(tier: str) -> int:
    try:
        return _GATE_ORDER[tier]
    except KeyError as exc:
        raise ValueError(f"unsupported long-term gate tier: {tier}") from exc


def _maximum_adjustment(configuration: dict[str, Any]) -> float:
    raw_range = configuration.get("adjustment_range")
    if (
        not isinstance(raw_range, list)
        or len(raw_range) != 2
        or not all(isinstance(value, (int, float)) for value in raw_range)
    ):
        raise ValueError("malformed challenger adjustment range")
    lower, upper = (float(value) for value in raw_range)
    if lower >= 0 or upper <= 0 or not math.isclose(abs(lower), upper):
        raise ValueError("challenger adjustment range must be centered on zero")
    return upper


def _positive_finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _atomic_write(path: Path, content: str) -> None:
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


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    raw = _required_string(value, "decision timestamp")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("experiment decision timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"malformed challenger experiment {field_name}")
    return value.strip()


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"malformed challenger experiment {field_name}")
    return value


def _required_signed_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"malformed challenger experiment {field_name}")
    return value


def _required_number(value: Any, field_name: str) -> float:
    parsed = _optional_number(value)
    if parsed is None:
        raise ValueError(f"malformed challenger experiment {field_name}")
    return parsed


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("malformed challenger experiment number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("malformed challenger experiment number")
    return parsed


def _required_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"malformed challenger experiment {field_name}")
    return value


def _required_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"malformed challenger experiment {field_name}")
    return [_required_string(item, field_name) for item in value]


def _required_string_dict(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"malformed challenger experiment {field_name}")
    return {
        _required_string(key, field_name): _required_string(item, field_name)
        for key, item in value.items()
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
