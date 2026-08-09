from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from investmentagent.fundamentals_cache import company_cache_identity
from investmentagent.long_term_quality import (
    assess_long_term_gate,
    assess_long_term_quality,
)
from investmentagent.models import CompanyResearch, ListingSegment, WatchlistItem
from investmentagent.reports import WatchlistBuildResult
from investmentagent.scoring import SCORING_MODEL_VERSION


EVALUATION_SCHEMA_VERSION = 1
EVALUATION_STRATEGIES = ("trading", "long-term")
_FINANCIAL_FIELDS = (
    "price",
    "pe_ratio",
    "price_to_book",
    "ev_to_ebit",
    "revenue_eur_m",
    "book_value_eur_m",
    "net_income_eur_m",
    "net_cash_eur_m",
    "debt_to_equity",
    "revenue_growth_pct",
    "operating_margin_pct",
    "one_year_return_pct",
    "distance_from_52w_high_pct",
    "average_daily_value_eur",
)


@dataclass(frozen=True)
class EvaluationCompanyRow:
    company_id: str
    isin: str | None
    ticker: str
    country: str
    name: str
    exchange: str
    segment: str
    sector: str | None
    eligible_universe_member: bool
    rank: int
    score: dict[str, float]
    long_term: dict[str, Any] | None
    data_quality: str
    cache: dict[str, Any]
    model_inputs: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "record_type": "company",
            "company_id": self.company_id,
            "isin": self.isin,
            "ticker": self.ticker,
            "country": self.country,
            "name": self.name,
            "exchange": self.exchange,
            "segment": self.segment,
            "sector": self.sector,
            "eligible_universe_member": self.eligible_universe_member,
            "rank": self.rank,
            "score": self.score,
            "long_term": self.long_term,
            "data_quality": self.data_quality,
            "cache": self.cache,
            "model_inputs": self.model_inputs,
        }


@dataclass(frozen=True)
class EvaluationSnapshot:
    schema_version: int
    run_id: str
    strategy: str
    decision_at: datetime
    report_date: date
    universe_size: int
    countries: tuple[str, ...]
    scoring_model_version: str
    configuration: dict[str, Any]
    diagnostics: dict[str, Any]
    rows: tuple[EvaluationCompanyRow, ...]

    def __post_init__(self) -> None:
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported evaluation schema: {self.schema_version}"
            )
        if self.strategy not in EVALUATION_STRATEGIES:
            raise ValueError("evaluation strategy must be trading or long-term")
        decision_at = _utc_timestamp(self.decision_at, "decision_at")
        object.__setattr__(self, "decision_at", decision_at)
        object.__setattr__(
            self, "countries", tuple(country.upper() for country in self.countries)
        )
        if self.universe_size != len(self.rows):
            raise ValueError("evaluation universe size does not match company rows")
        ranks = [row.rank for row in self.rows]
        if ranks != list(range(1, len(self.rows) + 1)):
            raise ValueError("evaluation company ranks must be sequential")
        company_ids = [row.company_id for row in self.rows]
        if len(company_ids) != len(set(company_ids)):
            raise ValueError("evaluation company identities must be unique")
        if self.strategy == "long-term" and any(
            row.long_term is None for row in self.rows
        ):
            raise ValueError("long-term evaluation rows require gate metadata")
        if self.strategy == "trading" and any(
            row.long_term is not None for row in self.rows
        ):
            raise ValueError("trading evaluation rows cannot contain long-term metadata")
        expected_run_id = evaluation_run_id(
            strategy=self.strategy,
            decision_at=decision_at,
            report_date=self.report_date,
            countries=self.countries,
            scoring_model_version=self.scoring_model_version,
            configuration=self.configuration,
        )
        if self.run_id != expected_run_id:
            raise ValueError("evaluation run identity does not match its metadata")
        _validate_json_value(self.configuration, "configuration")
        _validate_json_value(self.diagnostics, "diagnostics")
        for row in self.rows:
            _validate_json_value(row.as_payload(), f"company row {row.rank}")

    def header_payload(self) -> dict[str, Any]:
        return {
            "record_type": "run",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "strategy": self.strategy,
            "decision_at": _format_timestamp(self.decision_at),
            "report_date": self.report_date.isoformat(),
            "universe_size": self.universe_size,
            "countries": list(self.countries),
            "scoring_model_version": self.scoring_model_version,
            "configuration": self.configuration,
            "diagnostics": self.diagnostics,
        }


def build_evaluation_snapshot(
    result: WatchlistBuildResult,
    *,
    provider,
    strategy: str,
    decision_at: datetime,
    report_date: date,
    countries: tuple[str, ...],
    configuration: dict[str, Any],
    source_checks,
) -> EvaluationSnapshot:
    normalized_strategy = strategy.strip().lower()
    if normalized_strategy not in EVALUATION_STRATEGIES:
        raise ValueError("evaluation snapshots support trading and long-term strategies")
    cutoff = _utc_timestamp(decision_at, "decision_at")
    rows = tuple(
        _evaluation_row(item, provider=provider, strategy=normalized_strategy)
        for item in result.ranked_items
    )
    for row in rows:
        retrieved_at = row.cache.get("retrieved_at")
        if retrieved_at is not None and _parse_timestamp(retrieved_at) > cutoff:
            raise ValueError(
                f"evaluation row {row.company_id} contains future cache data"
            )
    enrichment_stats = getattr(provider, "enrichment_stats", None)
    enrichment = dict(enrichment_stats()) if callable(enrichment_stats) else None
    if enrichment is not None:
        enrichment.pop("candidate_keys", None)
    build_diagnostics = result.diagnostics
    diagnostics = {
        "source_universe_size": build_diagnostics.source_universe_size,
        "filtered_universe_size": build_diagnostics.filtered_universe_size,
        "successfully_scored_universe_size": (
            build_diagnostics.successfully_scored_universe_size
        ),
        "final_ranked_universe_size": build_diagnostics.final_ranked_universe_size,
        "public_selection_size": build_diagnostics.public_selection_size,
        "source_country_counts": build_diagnostics.source_country_counts,
        "source_segment_counts": build_diagnostics.source_segment_counts,
        "exclusion_counts": build_diagnostics.exclusion_counts,
        "enrichment": enrichment,
        "source_checks": [
            {"name": check.name, "status": check.status, "detail": check.detail}
            for check in source_checks
        ],
    }
    run_id = evaluation_run_id(
        strategy=normalized_strategy,
        decision_at=cutoff,
        report_date=report_date,
        countries=countries,
        scoring_model_version=SCORING_MODEL_VERSION,
        configuration=configuration,
    )
    return EvaluationSnapshot(
        schema_version=EVALUATION_SCHEMA_VERSION,
        run_id=run_id,
        strategy=normalized_strategy,
        decision_at=cutoff,
        report_date=report_date,
        universe_size=len(rows),
        countries=tuple(countries),
        scoring_model_version=SCORING_MODEL_VERSION,
        configuration=configuration,
        diagnostics=diagnostics,
        rows=rows,
    )


def evaluation_run_id(
    *,
    strategy: str,
    decision_at: datetime,
    report_date: date,
    countries: tuple[str, ...],
    scoring_model_version: str,
    configuration: dict[str, Any],
) -> str:
    identity = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "strategy": strategy,
        "decision_at": _format_timestamp(_utc_timestamp(decision_at, "decision_at")),
        "report_date": report_date.isoformat(),
        "countries": [country.upper() for country in countries],
        "scoring_model_version": scoring_model_version,
        "configuration": configuration,
    }
    canonical = json.dumps(
        identity,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"evaluation-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


def save_evaluation_snapshot(root: Path, snapshot: EvaluationSnapshot) -> Path:
    content = serialize_evaluation_snapshot(snapshot)
    timestamp = snapshot.decision_at.strftime("%Y%m%dT%H%M%S%fZ")
    path = (
        root
        / snapshot.report_date.isoformat()
        / snapshot.strategy
        / f"{timestamp}-{snapshot.run_id.removeprefix('evaluation-')}.jsonl"
    )
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"unable to read existing evaluation snapshot: {path}") from exc
        if existing == content:
            return path
        raise ValueError(f"evaluation run identity conflict: {snapshot.run_id}")
    _atomic_write(path, content)
    return path


def serialize_evaluation_snapshot(snapshot: EvaluationSnapshot) -> str:
    payloads = [snapshot.header_payload(), *(row.as_payload() for row in snapshot.rows)]
    return "\n".join(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for payload in payloads
    ) + "\n"


def load_evaluation_snapshot(path: Path) -> EvaluationSnapshot:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read evaluation snapshot: {path}") from exc
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        raise ValueError("malformed evaluation snapshot: file is empty")
    try:
        payloads = [json.loads(line, parse_constant=_reject_json_constant) for line in lines]
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed evaluation snapshot: {path}") from exc
    header = payloads[0]
    if not isinstance(header, dict) or header.get("record_type") != "run":
        raise ValueError("malformed evaluation snapshot run header")
    schema_version = header.get("schema_version")
    if schema_version != EVALUATION_SCHEMA_VERSION:
        raise ValueError(f"unsupported evaluation schema: {schema_version}")
    rows = tuple(_row_from_payload(payload) for payload in payloads[1:])
    try:
        decision_at = _parse_timestamp(header.get("decision_at"))
        report_date = date.fromisoformat(_required_string(header.get("report_date"), "report_date"))
    except ValueError as exc:
        raise ValueError("malformed evaluation snapshot timestamp or report date") from exc
    return EvaluationSnapshot(
        schema_version=schema_version,
        run_id=_required_string(header.get("run_id"), "run_id"),
        strategy=_required_string(header.get("strategy"), "strategy"),
        decision_at=decision_at,
        report_date=report_date,
        universe_size=_required_int(header.get("universe_size"), "universe_size"),
        countries=tuple(_required_string_list(header.get("countries"), "countries")),
        scoring_model_version=_required_string(
            header.get("scoring_model_version"), "scoring_model_version"
        ),
        configuration=_required_dict(header.get("configuration"), "configuration"),
        diagnostics=_required_dict(header.get("diagnostics"), "diagnostics"),
        rows=rows,
    )


def _evaluation_row(
    item: WatchlistItem,
    *,
    provider,
    strategy: str,
) -> EvaluationCompanyRow:
    research = item.research
    company = research.company
    cache_status_lookup = getattr(provider, "evaluation_cache_status", None)
    cache_status = (
        cache_status_lookup(company)
        if callable(cache_status_lookup)
        else {
            "enabled": False,
            "participated": False,
            "state": "disabled",
            "refreshed_this_run": False,
            "retrieved_at": None,
            "providers": [],
        }
    )
    score = {
        "total": item.score.total,
        "value": item.score.value,
        "discovery": item.score.discovery,
        "catalyst": item.score.catalyst,
        "risk_penalty": item.score.risk_penalty,
        "data_quality_penalty": item.score.data_quality_penalty,
    }
    long_term = _long_term_payload(research) if strategy == "long-term" else None
    return EvaluationCompanyRow(
        company_id=company_cache_identity(company),
        isin=company.isin,
        ticker=company.ticker,
        country=company.country,
        name=company.name,
        exchange=company.exchange,
        segment=company.segment.value,
        sector=company.sector,
        eligible_universe_member=True,
        rank=item.rank,
        score=score,
        long_term=long_term,
        data_quality=research.data_quality.value,
        cache=cache_status,
        model_inputs=_model_input_summary(research),
    )


def _long_term_payload(research: CompanyResearch) -> dict[str, Any]:
    gate = assess_long_term_gate(research)
    quality = assess_long_term_quality(research)
    return {
        "gate_tier": gate.tier.value,
        "quality_bucket": quality.bucket.value,
        "quality_adjustment": quality.quality_adjustment,
        "proof_penalty": quality.proof_penalty,
        "proof_gaps": list(quality.proof_gaps),
        "durable_anchor_count": gate.durable_anchor_count,
        "severe_proof_gap_count": gate.severe_proof_gap_count,
        "valuation": {
            "has_support": gate.valuation.has_support,
            "is_attractive": gate.valuation.is_attractive,
            "primary_kind": gate.valuation.primary_kind,
        },
    }


def _model_input_summary(research: CompanyResearch) -> dict[str, Any]:
    financials = research.financials
    company = research.company
    catalysts = tuple(item.lower() for item in research.catalysts)
    risks = tuple(item.lower() for item in research.risks)
    signals = catalysts + risks
    observations = financials.observations
    return {
        "available_financial_fields": [
            field_name
            for field_name in _FINANCIAL_FIELDS
            if getattr(financials, field_name) is not None
        ],
        "observation_providers": sorted(
            {observation.provider for observation in observations if observation.provider}
        ),
        "evidence_sources": sorted(
            {evidence.source for evidence in research.evidence if evidence.source}
        ),
        "threshold_flags": {
            "pe_at_or_below_12": _threshold(financials.pe_ratio, lambda value: value <= 12),
            "price_to_book_at_or_below_1_2": _threshold(
                financials.price_to_book, lambda value: value <= 1.2
            ),
            "net_cash_positive": _threshold(
                financials.net_cash_eur_m, lambda value: value > 0
            ),
            "market_cap_at_or_below_500": _threshold(
                company.market_cap_eur_m, lambda value: value <= 500
            ),
            "first_north": company.segment == ListingSegment.FIRST_NORTH,
            "one_year_return_at_or_below_minus_25": _threshold(
                financials.one_year_return_pct, lambda value: value <= -25
            ),
            "distance_from_high_at_or_below_minus_35": _threshold(
                financials.distance_from_52w_high_pct, lambda value: value <= -35
            ),
            "liquidity_below_100k": _threshold(
                financials.average_daily_value_eur, lambda value: value < 100_000
            ),
            "debt_to_equity_above_1_5": _threshold(
                financials.debt_to_equity, lambda value: value > 1.5
            ),
            "debt_to_equity_at_or_below_0_5": _threshold(
                financials.debt_to_equity, lambda value: value <= 0.5
            ),
            "operating_margin_negative": _threshold(
                financials.operating_margin_pct, lambda value: value < 0
            ),
            "operating_margin_positive": _threshold(
                financials.operating_margin_pct, lambda value: value > 0
            ),
            "revenue_growth_positive": _threshold(
                financials.revenue_growth_pct, lambda value: value > 0
            ),
            "pe_above_40": _threshold(financials.pe_ratio, lambda value: value > 40),
            "price_to_book_above_5": _threshold(
                financials.price_to_book, lambda value: value > 5
            ),
            "business_description_available": bool(company.business_description),
        },
        "research_signal_summary": {
            "catalyst_count": len(research.catalysts),
            "risk_count": len(research.risks),
            "intraday_momentum": any("intraday momentum" in signal for signal in signals),
            "high_live_turnover": any("high live turnover" in signal for signal in signals),
            "moderate_live_turnover": any(
                "moderate live turnover" in signal for signal in signals
            ),
            "missing_live_turnover": any(
                "missing live turnover" in signal for signal in signals
            ),
            "low_live_turnover": any("low live turnover" in signal for signal in signals),
            "extreme_intraday_spike": any(
                "extreme intraday spike" in signal for signal in signals
            ),
            "speculative_low_price": any(
                "speculative low-price share" in signal for signal in signals
            ),
        },
    }


def _row_from_payload(payload: Any) -> EvaluationCompanyRow:
    if not isinstance(payload, dict) or payload.get("record_type") != "company":
        raise ValueError("malformed evaluation company row")
    eligible = payload.get("eligible_universe_member")
    if eligible is not True:
        raise ValueError("malformed evaluation eligible-universe membership")
    long_term = payload.get("long_term")
    if long_term is not None and not isinstance(long_term, dict):
        raise ValueError("malformed evaluation long-term payload")
    return EvaluationCompanyRow(
        company_id=_required_string(payload.get("company_id"), "company_id"),
        isin=_optional_string(payload.get("isin"), "isin"),
        ticker=_required_string(payload.get("ticker"), "ticker"),
        country=_required_string(payload.get("country"), "country"),
        name=_required_string(payload.get("name"), "name"),
        exchange=_required_string(payload.get("exchange"), "exchange"),
        segment=_required_string(payload.get("segment"), "segment"),
        sector=_optional_string(payload.get("sector"), "sector"),
        eligible_universe_member=eligible,
        rank=_required_int(payload.get("rank"), "rank"),
        score=_score_from_payload(payload.get("score")),
        long_term=long_term,
        data_quality=_required_string(payload.get("data_quality"), "data_quality"),
        cache=_required_dict(payload.get("cache"), "cache"),
        model_inputs=_required_dict(payload.get("model_inputs"), "model_inputs"),
    )


def _score_from_payload(value: Any) -> dict[str, float]:
    score = _required_dict(value, "score")
    required_fields = (
        "total",
        "value",
        "discovery",
        "catalyst",
        "risk_penalty",
        "data_quality_penalty",
    )
    if set(score) != set(required_fields):
        raise ValueError("malformed evaluation score components")
    for field_name in required_fields:
        field_value = score[field_name]
        if (
            isinstance(field_value, bool)
            or not isinstance(field_value, (int, float))
            or not math.isfinite(field_value)
        ):
            raise ValueError(f"malformed evaluation score {field_name}")
    return score


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()


def _threshold(value: float | None, predicate) -> bool | None:
    return None if value is None else bool(predicate(value))


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime:
    raw = _required_string(value, "decision_at")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _utc_timestamp(parsed, "decision_at")


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"malformed evaluation {field_name}")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"malformed evaluation {field_name}")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"malformed evaluation {field_name}")
    return value


def _required_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"malformed evaluation {field_name}")
    return value


def _required_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"malformed evaluation {field_name}")
    return [_required_string(item, field_name) for item in value]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _validate_json_value(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite evaluation value in {field_name}")
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"non-string evaluation key in {field_name}")
        for item in value.values():
            _validate_json_value(item, field_name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, field_name)
        return
    raise ValueError(f"unsupported evaluation value in {field_name}")
