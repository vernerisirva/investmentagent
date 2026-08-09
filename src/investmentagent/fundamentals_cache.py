from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from investmentagent.models import (
    Company,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    FundamentalsSnapshot,
    ObservationConfidence,
    ReportingPeriodType,
)


FUNDAMENTALS_CACHE_SCHEMA_VERSION = 1
DEFAULT_FUNDAMENTALS_MAX_AGE_DAYS = 45
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


class CacheFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True)
class FundamentalsFreshnessPolicy:
    max_age_days: int = DEFAULT_FUNDAMENTALS_MAX_AGE_DAYS

    def __post_init__(self) -> None:
        if self.max_age_days < 0:
            raise ValueError("fundamentals max age must be at least 0 days")

    def classify(
        self,
        record: CachedFundamentalsRecord,
        *,
        known_at: datetime,
    ) -> CacheFreshness:
        cutoff = _utc_timestamp(known_at, "known_at")
        age = cutoff - record.retrieved_at
        return (
            CacheFreshness.FRESH
            if age.total_seconds() <= self.max_age_days * 86_400
            else CacheFreshness.STALE
        )


@dataclass(frozen=True)
class CachedFundamentalsRecord:
    record_id: str
    schema_version: int
    company_id: str
    ticker: str
    country: str
    isin: str | None
    retrieved_at: datetime
    providers: tuple[str, ...]
    snapshot: FundamentalsSnapshot


@dataclass(frozen=True)
class CacheCoverage:
    eligible_companies: int
    cached_companies: int
    fresh_companies: int
    stale_companies: int
    missing_companies: int
    oldest_retrieved_at: datetime | None
    newest_retrieved_at: datetime | None
    country_coverage: dict[str, dict[str, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible_companies": self.eligible_companies,
            "cached_companies": self.cached_companies,
            "fresh_companies": self.fresh_companies,
            "stale_companies": self.stale_companies,
            "missing_companies": self.missing_companies,
            "oldest_retrieved_at": _format_timestamp(self.oldest_retrieved_at),
            "newest_retrieved_at": _format_timestamp(self.newest_retrieved_at),
            "country_coverage": self.country_coverage,
        }


class FundamentalsCache(Protocol):
    def store(
        self,
        company: Company,
        snapshot: FundamentalsSnapshot,
        *,
        retrieved_at: datetime,
    ) -> CachedFundamentalsRecord:
        ...

    def get_latest(
        self,
        company: Company,
        *,
        known_at: datetime,
    ) -> CachedFundamentalsRecord | None:
        ...

    def coverage(
        self,
        companies: tuple[Company, ...],
        *,
        known_at: datetime,
        freshness_policy: FundamentalsFreshnessPolicy,
    ) -> CacheCoverage:
        ...


class FileFundamentalsCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records = _load_records(path)

    @property
    def records(self) -> tuple[CachedFundamentalsRecord, ...]:
        return tuple(self._records)

    def records_for(self, company: Company) -> tuple[CachedFundamentalsRecord, ...]:
        company_id = company_cache_identity(company)
        return tuple(
            record for record in self._records if record.company_id == company_id
        )

    def store(
        self,
        company: Company,
        snapshot: FundamentalsSnapshot,
        *,
        retrieved_at: datetime,
    ) -> CachedFundamentalsRecord:
        observed_at = _utc_timestamp(retrieved_at, "retrieved_at")
        company_id = company_cache_identity(company)
        providers = _snapshot_providers(snapshot)
        if not providers:
            raise ValueError(
                "fundamentals snapshot must include explicit provider provenance"
            )
        snapshot_payload = _snapshot_to_payload(snapshot)

        # Same-day reruns with identical accepted content reuse the earliest
        # observation. An earlier backdated boundary is never collapsed into a
        # later one, which preserves point-in-time safety.
        for record in self._records:
            if (
                record.company_id == company_id
                and record.retrieved_at.date() == observed_at.date()
                and record.retrieved_at <= observed_at
                and record.providers == providers
                and _snapshot_to_payload(record.snapshot) == snapshot_payload
            ):
                return record

        identity_payload = {
            "schema_version": FUNDAMENTALS_CACHE_SCHEMA_VERSION,
            "company_id": company_id,
            "retrieved_at": _format_timestamp(observed_at),
            "providers": list(providers),
            "snapshot": snapshot_payload,
        }
        record = CachedFundamentalsRecord(
            record_id=_record_id(identity_payload),
            schema_version=FUNDAMENTALS_CACHE_SCHEMA_VERSION,
            company_id=company_id,
            ticker=company.ticker,
            country=company.country,
            isin=company.isin,
            retrieved_at=observed_at,
            providers=providers,
            snapshot=snapshot,
        )
        records = sorted(
            (*self._records, record),
            key=lambda item: (item.retrieved_at, item.record_id),
        )
        _save_records(self.path, records)
        self._records = list(records)
        return record

    def get_latest(
        self,
        company: Company,
        *,
        known_at: datetime,
    ) -> CachedFundamentalsRecord | None:
        cutoff = _utc_timestamp(known_at, "known_at")
        company_id = company_cache_identity(company)
        eligible = [
            record
            for record in self._records
            if record.company_id == company_id and record.retrieved_at <= cutoff
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item.retrieved_at, item.record_id))

    def coverage(
        self,
        companies: tuple[Company, ...],
        *,
        known_at: datetime,
        freshness_policy: FundamentalsFreshnessPolicy,
    ) -> CacheCoverage:
        unique_companies = {
            company_cache_identity(company): company for company in companies
        }
        country_coverage: dict[str, dict[str, int]] = {}
        latest_records: list[CachedFundamentalsRecord] = []
        fresh_count = 0
        stale_count = 0
        missing_count = 0
        for company in unique_companies.values():
            country_stats = country_coverage.setdefault(
                company.country,
                {"eligible": 0, "cached": 0, "fresh": 0, "stale": 0, "missing": 0},
            )
            country_stats["eligible"] += 1
            record = self.get_latest(company, known_at=known_at)
            if record is None:
                missing_count += 1
                country_stats["missing"] += 1
                continue
            latest_records.append(record)
            country_stats["cached"] += 1
            freshness = freshness_policy.classify(record, known_at=known_at)
            if freshness == CacheFreshness.FRESH:
                fresh_count += 1
                country_stats["fresh"] += 1
            else:
                stale_count += 1
                country_stats["stale"] += 1

        timestamps = [record.retrieved_at for record in latest_records]
        return CacheCoverage(
            eligible_companies=len(unique_companies),
            cached_companies=len(latest_records),
            fresh_companies=fresh_count,
            stale_companies=stale_count,
            missing_companies=missing_count,
            oldest_retrieved_at=min(timestamps) if timestamps else None,
            newest_retrieved_at=max(timestamps) if timestamps else None,
            country_coverage=country_coverage,
        )


def company_cache_identity(company: Company) -> str:
    isin = (company.isin or "").strip().upper()
    if len(isin) == 12 and isin.isalnum():
        return f"isin:{isin}"
    return f"listing:{company.country}:{company.ticker}"


def _load_records(path: Path) -> list[CachedFundamentalsRecord]:
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read fundamentals cache: {path}") from exc
    if not content.strip():
        return []
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed fundamentals cache: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"malformed fundamentals cache: {path}")
    schema_version = payload.get("schema_version")
    if schema_version != FUNDAMENTALS_CACHE_SCHEMA_VERSION:
        raise ValueError(f"unsupported fundamentals cache schema: {schema_version}")
    records_payload = payload.get("records")
    if not isinstance(records_payload, list):
        raise ValueError("malformed fundamentals cache: records must be a list")
    records = [_record_from_payload(item) for item in records_payload]
    record_ids = [record.record_id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("malformed fundamentals cache: duplicate record id")
    return sorted(records, key=lambda item: (item.retrieved_at, item.record_id))


def _save_records(path: Path, records: list[CachedFundamentalsRecord]) -> None:
    payload = {
        "schema_version": FUNDAMENTALS_CACHE_SCHEMA_VERSION,
        "records": [_record_to_payload(record) for record in records],
    }
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
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


def _record_to_payload(record: CachedFundamentalsRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "record_id": record.record_id,
        "company": {
            "company_id": record.company_id,
            "ticker": record.ticker,
            "country": record.country,
            "isin": record.isin,
        },
        "retrieved_at": _format_timestamp(record.retrieved_at),
        "providers": list(record.providers),
        "snapshot": _snapshot_to_payload(record.snapshot),
    }


def _record_from_payload(payload: Any) -> CachedFundamentalsRecord:
    if not isinstance(payload, dict):
        raise ValueError("malformed fundamentals cache record")
    schema_version = payload.get("schema_version")
    if schema_version != FUNDAMENTALS_CACHE_SCHEMA_VERSION:
        raise ValueError(f"unsupported fundamentals cache record schema: {schema_version}")
    company = payload.get("company")
    if not isinstance(company, dict):
        raise ValueError("malformed fundamentals cache record company")
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers or not all(
        isinstance(provider, str) for provider in providers
    ):
        raise ValueError("malformed fundamentals cache record providers")
    retrieved_at = _parse_timestamp(payload.get("retrieved_at"), "retrieved_at")
    snapshot = _snapshot_from_payload(payload.get("snapshot"))
    record = CachedFundamentalsRecord(
        record_id=_required_string(payload.get("record_id"), "record_id"),
        schema_version=schema_version,
        company_id=_required_string(company.get("company_id"), "company_id"),
        ticker=_required_string(company.get("ticker"), "ticker").upper(),
        country=_required_string(company.get("country"), "country").upper(),
        isin=_optional_string(company.get("isin"), "isin"),
        retrieved_at=retrieved_at,
        providers=tuple(providers),
        snapshot=snapshot,
    )
    identity_payload = {
        "schema_version": record.schema_version,
        "company_id": record.company_id,
        "retrieved_at": _format_timestamp(record.retrieved_at),
        "providers": list(record.providers),
        "snapshot": _snapshot_to_payload(record.snapshot),
    }
    if record.record_id != _record_id(identity_payload):
        raise ValueError("malformed fundamentals cache record identity")
    return record


def _snapshot_to_payload(snapshot: FundamentalsSnapshot) -> dict[str, Any]:
    financials = {
        field_name: _validated_number(getattr(snapshot.financials, field_name), field_name)
        for field_name in _FINANCIAL_FIELDS
    }
    financials.update(
        {
            "currency": snapshot.financials.currency,
            "data_quality": snapshot.financials.data_quality.value,
            "observations": [
                _observation_to_payload(observation)
                for observation in snapshot.financials.observations
            ],
        }
    )
    return {
        "symbol": snapshot.symbol,
        "market_cap_eur_m": _validated_number(
            snapshot.market_cap_eur_m, "market_cap_eur_m"
        ),
        "business_description": snapshot.business_description,
        "ir_url": snapshot.ir_url,
        "financials": financials,
        "evidence": _evidence_to_payload(snapshot.evidence),
    }


def _snapshot_from_payload(payload: Any) -> FundamentalsSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("malformed fundamentals cache snapshot")
    financials_payload = payload.get("financials")
    if not isinstance(financials_payload, dict):
        raise ValueError("malformed fundamentals cache financials")
    observations_payload = financials_payload.get("observations")
    if not isinstance(observations_payload, list):
        raise ValueError("malformed fundamentals cache observations")
    try:
        data_quality = DataQuality(financials_payload.get("data_quality"))
    except ValueError as exc:
        raise ValueError("malformed fundamentals cache data quality") from exc
    financial_values = {
        field_name: _optional_finite_number(
            financials_payload.get(field_name), field_name
        )
        for field_name in _FINANCIAL_FIELDS
    }
    financials = FinancialSnapshot(
        **financial_values,
        currency=_optional_string(financials_payload.get("currency"), "currency"),
        data_quality=data_quality,
        observations=tuple(
            _observation_from_payload(item) for item in observations_payload
        ),
    )
    return FundamentalsSnapshot(
        symbol=_required_string(payload.get("symbol"), "symbol"),
        market_cap_eur_m=_optional_finite_number(
            payload.get("market_cap_eur_m"), "market_cap_eur_m"
        ),
        business_description=_optional_string(
            payload.get("business_description"), "business_description"
        ),
        ir_url=_optional_string(payload.get("ir_url"), "ir_url"),
        financials=financials,
        evidence=_evidence_from_payload(payload.get("evidence")),
    )


def _observation_to_payload(observation: FinancialObservation) -> dict[str, Any]:
    return {
        "canonical_field": observation.canonical_field,
        "normalized_value": _validated_number(
            observation.normalized_value, observation.canonical_field
        ),
        "provider": observation.provider,
        "source_metric": observation.source_metric,
        "as_of": observation.as_of,
        "reporting_period": observation.reporting_period,
        "period_type": observation.period_type.value if observation.period_type else None,
        "original_currency": observation.original_currency,
        "normalized_currency": observation.normalized_currency,
        "is_derived": observation.is_derived,
        "derivation": observation.derivation,
        "confidence": observation.confidence.value if observation.confidence else None,
    }


def _observation_from_payload(payload: Any) -> FinancialObservation:
    if not isinstance(payload, dict):
        raise ValueError("malformed fundamentals cache observation")
    period_type = _optional_enum(
        ReportingPeriodType, payload.get("period_type"), "period_type"
    )
    confidence = _optional_enum(
        ObservationConfidence, payload.get("confidence"), "confidence"
    )
    is_derived = payload.get("is_derived")
    if not isinstance(is_derived, bool):
        raise ValueError("malformed fundamentals cache observation is_derived")
    return FinancialObservation(
        canonical_field=_required_string(
            payload.get("canonical_field"), "canonical_field"
        ),
        normalized_value=_optional_finite_number(
            payload.get("normalized_value"), "normalized_value"
        ),
        provider=_required_string(payload.get("provider"), "provider"),
        source_metric=_required_string(payload.get("source_metric"), "source_metric"),
        as_of=_optional_string(payload.get("as_of"), "as_of"),
        reporting_period=_optional_string(
            payload.get("reporting_period"), "reporting_period"
        ),
        period_type=period_type,
        original_currency=_optional_string(
            payload.get("original_currency"), "original_currency"
        ),
        normalized_currency=_optional_string(
            payload.get("normalized_currency"), "normalized_currency"
        ),
        is_derived=is_derived,
        derivation=_optional_string(payload.get("derivation"), "derivation"),
        confidence=confidence,
    )


def _evidence_to_payload(evidence: Evidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "label": evidence.label,
        "url": evidence.url,
        "source": evidence.source,
        "timestamp": evidence.timestamp,
    }


def _evidence_from_payload(payload: Any) -> Evidence | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("malformed fundamentals cache evidence")
    return Evidence(
        label=_required_string(payload.get("label"), "evidence label"),
        url=_required_string(payload.get("url"), "evidence url"),
        source=_optional_string(payload.get("source"), "evidence source"),
        timestamp=_optional_string(payload.get("timestamp"), "evidence timestamp"),
    )


def _snapshot_providers(snapshot: FundamentalsSnapshot) -> tuple[str, ...]:
    providers = {
        observation.provider
        for observation in snapshot.financials.observations
        if observation.provider
    }
    if snapshot.evidence is not None and snapshot.evidence.source:
        providers.add(snapshot.evidence.source)
    return tuple(sorted(providers))


def _record_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_number(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid cached numeric value for {field_name}")
    if not math.isfinite(value):
        raise ValueError(f"non-finite cached numeric value for {field_name}")
    return float(value)


def _optional_finite_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid cached numeric value for {field_name}")
    if not math.isfinite(value):
        raise ValueError(f"non-finite cached numeric value for {field_name}")
    return float(value)


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"malformed fundamentals cache {field_name}")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"malformed fundamentals cache {field_name}")
    return value


def _optional_enum(enum_type, value: Any, field_name: str):
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"malformed fundamentals cache {field_name}") from exc


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    raw = _required_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"malformed fundamentals cache {field_name}") from exc
    return _utc_timestamp(parsed, field_name)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
