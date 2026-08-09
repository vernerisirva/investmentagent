from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from investmentagent.market_prices import (
    ADJUSTED_PRICE_TYPE,
    HistoricalPriceObservation,
)


MARKET_PRICE_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CachedPriceObservation:
    record_id: str
    schema_version: int
    company_id: str
    observation: HistoricalPriceObservation

    @property
    def key(self) -> tuple[str, str, str, str, date]:
        return (
            self.company_id,
            self.observation.provider,
            self.observation.symbol,
            self.observation.market,
            self.observation.session_date,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "company_id": self.company_id,
            **_observation_payload(self.observation),
        }


@dataclass(frozen=True)
class PriceObservationRevision:
    revision_id: str
    schema_version: int
    company_id: str
    provider: str
    provider_symbol: str
    market: str
    session_date: date
    cached_adjusted_close: float
    cached_close: float | None
    cached_currency: str | None
    cached_retrieved_at: datetime
    observed_adjusted_close: float
    observed_close: float | None
    observed_currency: str | None
    observed_retrieved_at: datetime

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision_id": self.revision_id,
            "company_id": self.company_id,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "market": self.market,
            "session_date": self.session_date.isoformat(),
            "price_type": ADJUSTED_PRICE_TYPE,
            "cached": {
                "adjusted_close": self.cached_adjusted_close,
                "close": self.cached_close,
                "currency": self.cached_currency,
                "retrieved_at": _format_timestamp(self.cached_retrieved_at),
            },
            "observed_revision": {
                "adjusted_close": self.observed_adjusted_close,
                "close": self.observed_close,
                "currency": self.observed_currency,
                "retrieved_at": _format_timestamp(self.observed_retrieved_at),
            },
            "policy": "retain accepted observation and record conflicting revision",
        }


@dataclass(frozen=True)
class PriceCacheStoreResult:
    observations_stored: int
    observations_reused: int
    revisions_detected: int
    revision_session_dates: tuple[date, ...]


@dataclass(frozen=True)
class PriceCacheCoverage:
    securities: int
    observations: int
    revisions: int
    oldest_session: date | None
    newest_session: date | None
    providers: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "securities": self.securities,
            "observations": self.observations,
            "revisions": self.revisions,
            "oldest_session": (
                self.oldest_session.isoformat() if self.oldest_session else None
            ),
            "newest_session": (
                self.newest_session.isoformat() if self.newest_session else None
            ),
            "providers": self.providers,
        }


class HistoricalPriceCache(Protocol):
    def get_observation(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        session_date: date,
        symbol: str | None = None,
    ) -> HistoricalPriceObservation | None: ...

    def get_range(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        start_date: date,
        end_date: date,
        symbol: str | None = None,
    ) -> tuple[HistoricalPriceObservation, ...]: ...

    def preferred_symbol(
        self, company_id: str, *, provider: str, market: str
    ) -> str | None: ...

    def revision_dates(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        start_date: date,
        end_date: date,
        symbol: str | None = None,
    ) -> tuple[date, ...]: ...

    def store(
        self,
        company_id: str,
        observations: Iterable[HistoricalPriceObservation],
    ) -> PriceCacheStoreResult: ...

    def coverage(self) -> PriceCacheCoverage: ...


class FileHistoricalPriceCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records, self._revisions = _load_cache(path)

    @property
    def records(self) -> tuple[CachedPriceObservation, ...]:
        return tuple(self._records)

    @property
    def revisions(self) -> tuple[PriceObservationRevision, ...]:
        return tuple(self._revisions)

    def get_observation(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        session_date: date,
        symbol: str | None = None,
    ) -> HistoricalPriceObservation | None:
        rows = self.get_range(
            company_id,
            provider=provider,
            market=market,
            start_date=session_date,
            end_date=session_date,
            symbol=symbol,
        )
        return rows[0] if rows else None

    def get_range(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        start_date: date,
        end_date: date,
        symbol: str | None = None,
    ) -> tuple[HistoricalPriceObservation, ...]:
        if start_date > end_date:
            raise ValueError("price-cache start date cannot be after end date")
        normalized_company = _required_string(company_id, "company ID")
        normalized_provider = _required_string(provider, "provider").lower()
        normalized_market = _required_string(market, "market").lower()
        normalized_symbol = symbol.strip().upper() if symbol else None
        matching = [
            record.observation
            for record in self._records
            if record.company_id == normalized_company
            and record.observation.provider == normalized_provider
            and record.observation.market == normalized_market
            and start_date <= record.observation.session_date <= end_date
            and (
                normalized_symbol is None
                or record.observation.symbol == normalized_symbol
            )
        ]
        if normalized_symbol is None:
            symbols = {row.symbol for row in matching}
            if len(symbols) > 1:
                preferred = self.preferred_symbol(
                    normalized_company,
                    provider=normalized_provider,
                    market=normalized_market,
                )
                matching = [row for row in matching if row.symbol == preferred]
        return tuple(sorted(matching, key=lambda row: row.session_date))

    def preferred_symbol(
        self, company_id: str, *, provider: str, market: str
    ) -> str | None:
        normalized_company = _required_string(company_id, "company ID")
        normalized_provider = _required_string(provider, "provider").lower()
        normalized_market = _required_string(market, "market").lower()
        matching = [
            record
            for record in self._records
            if record.company_id == normalized_company
            and record.observation.provider == normalized_provider
            and record.observation.market == normalized_market
        ]
        if not matching:
            return None
        newest = max(
            matching,
            key=lambda record: (
                record.observation.retrieved_at,
                record.observation.session_date,
                record.observation.symbol,
            ),
        )
        return newest.observation.symbol

    def revision_dates(
        self,
        company_id: str,
        *,
        provider: str,
        market: str,
        start_date: date,
        end_date: date,
        symbol: str | None = None,
    ) -> tuple[date, ...]:
        normalized_company = _required_string(company_id, "company ID")
        normalized_provider = _required_string(provider, "provider").lower()
        normalized_market = _required_string(market, "market").lower()
        normalized_symbol = symbol.strip().upper() if symbol else None
        return tuple(
            sorted(
                {
                    revision.session_date
                    for revision in self._revisions
                    if revision.company_id == normalized_company
                    and revision.provider == normalized_provider
                    and revision.market == normalized_market
                    and start_date <= revision.session_date <= end_date
                    and (
                        normalized_symbol is None
                        or revision.provider_symbol == normalized_symbol
                    )
                }
            )
        )

    def store(
        self,
        company_id: str,
        observations: Iterable[HistoricalPriceObservation],
    ) -> PriceCacheStoreResult:
        normalized_company = _required_string(company_id, "company ID")
        records_by_key = {record.key: record for record in self._records}
        revision_ids = {revision.revision_id for revision in self._revisions}
        stored = 0
        reused = 0
        revisions_detected = 0
        revision_dates: set[date] = set()
        changed = False
        for observation in sorted(
            tuple(observations),
            key=lambda item: (
                item.provider,
                item.symbol,
                item.market,
                item.session_date,
            ),
        ):
            key = (
                normalized_company,
                observation.provider,
                observation.symbol,
                observation.market,
                observation.session_date,
            )
            existing = records_by_key.get(key)
            if existing is None:
                record = _cached_record(normalized_company, observation)
                self._records.append(record)
                records_by_key[key] = record
                stored += 1
                changed = True
                continue
            if _same_observation(existing.observation, observation):
                reused += 1
                continue
            revision = _revision(normalized_company, existing.observation, observation)
            revision_dates.add(observation.session_date)
            if revision.revision_id not in revision_ids:
                self._revisions.append(revision)
                revision_ids.add(revision.revision_id)
                revisions_detected += 1
                changed = True
        if changed:
            self._records.sort(
                key=lambda record: (
                    record.company_id,
                    record.observation.provider,
                    record.observation.symbol,
                    record.observation.market,
                    record.observation.session_date,
                )
            )
            self._revisions.sort(
                key=lambda revision: (
                    revision.observed_retrieved_at,
                    revision.revision_id,
                )
            )
            _save_cache(self.path, self._records, self._revisions)
        return PriceCacheStoreResult(
            observations_stored=stored,
            observations_reused=reused,
            revisions_detected=revisions_detected,
            revision_session_dates=tuple(sorted(revision_dates)),
        )

    def coverage(self) -> PriceCacheCoverage:
        sessions = [record.observation.session_date for record in self._records]
        provider_counts: dict[str, int] = {}
        for record in self._records:
            provider = record.observation.provider
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        return PriceCacheCoverage(
            securities=len({record.company_id for record in self._records}),
            observations=len(self._records),
            revisions=len(self._revisions),
            oldest_session=min(sessions) if sessions else None,
            newest_session=max(sessions) if sessions else None,
            providers=dict(sorted(provider_counts.items())),
        )


def _cached_record(
    company_id: str, observation: HistoricalPriceObservation
) -> CachedPriceObservation:
    identity = {
        "schema_version": MARKET_PRICE_CACHE_SCHEMA_VERSION,
        "company_id": company_id,
        **_observation_payload(observation),
    }
    return CachedPriceObservation(
        record_id=_content_id("price", identity),
        schema_version=MARKET_PRICE_CACHE_SCHEMA_VERSION,
        company_id=company_id,
        observation=observation,
    )


def _revision(
    company_id: str,
    cached: HistoricalPriceObservation,
    observed: HistoricalPriceObservation,
) -> PriceObservationRevision:
    identity = {
        "schema_version": MARKET_PRICE_CACHE_SCHEMA_VERSION,
        "company_id": company_id,
        "cached": _observation_payload(cached),
        "observed_revision": _observation_payload(observed),
    }
    return PriceObservationRevision(
        revision_id=_content_id("price-revision", identity),
        schema_version=MARKET_PRICE_CACHE_SCHEMA_VERSION,
        company_id=company_id,
        provider=cached.provider,
        provider_symbol=cached.symbol,
        market=cached.market,
        session_date=cached.session_date,
        cached_adjusted_close=cached.adjusted_close,
        cached_close=cached.close,
        cached_currency=cached.currency,
        cached_retrieved_at=cached.retrieved_at,
        observed_adjusted_close=observed.adjusted_close,
        observed_close=observed.close,
        observed_currency=observed.currency,
        observed_retrieved_at=observed.retrieved_at,
    )


def _same_observation(
    left: HistoricalPriceObservation, right: HistoricalPriceObservation
) -> bool:
    return math.isclose(
        left.adjusted_close,
        right.adjusted_close,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )


def _load_cache(
    path: Path,
) -> tuple[list[CachedPriceObservation], list[PriceObservationRevision]]:
    if not path.exists():
        return [], []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read market-price cache: {path}") from exc
    if not content.strip():
        return [], []
    try:
        payload = json.loads(content, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed market-price cache: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"malformed market-price cache: {path}")
    version = payload.get("schema_version")
    if version != MARKET_PRICE_CACHE_SCHEMA_VERSION:
        raise ValueError(f"unsupported market-price cache schema: {version}")
    raw_records = payload.get("observations")
    raw_revisions = payload.get("revisions")
    if not isinstance(raw_records, list) or not isinstance(raw_revisions, list):
        raise ValueError("malformed market-price cache collections")
    records = [_record_from_payload(item) for item in raw_records]
    revisions = [_revision_from_payload(item) for item in raw_revisions]
    record_ids = [record.record_id for record in records]
    revision_ids = [revision.revision_id for revision in revisions]
    keys = [record.key for record in records]
    if len(record_ids) != len(set(record_ids)) or len(keys) != len(set(keys)):
        raise ValueError("malformed market-price cache duplicate observation")
    if len(revision_ids) != len(set(revision_ids)):
        raise ValueError("malformed market-price cache duplicate revision")
    return records, revisions


def _save_cache(
    path: Path,
    records: list[CachedPriceObservation],
    revisions: list[PriceObservationRevision],
) -> None:
    payload = {
        "schema_version": MARKET_PRICE_CACHE_SCHEMA_VERSION,
        "price_type": ADJUSTED_PRICE_TYPE,
        "observations": [record.as_payload() for record in records],
        "revisions": [revision.as_payload() for revision in revisions],
    }
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
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


def _record_from_payload(value: Any) -> CachedPriceObservation:
    if not isinstance(value, dict):
        raise ValueError("malformed market-price cache observation")
    version = value.get("schema_version")
    if version != MARKET_PRICE_CACHE_SCHEMA_VERSION:
        raise ValueError(f"unsupported market-price cache record schema: {version}")
    company_id = _required_string(value.get("company_id"), "company ID")
    observation = _observation_from_payload(value)
    record = _cached_record(company_id, observation)
    if record.record_id != _required_string(value.get("record_id"), "record ID"):
        raise ValueError("malformed market-price cache record identity")
    return record


def _revision_from_payload(value: Any) -> PriceObservationRevision:
    if not isinstance(value, dict):
        raise ValueError("malformed market-price cache revision")
    version = value.get("schema_version")
    if version != MARKET_PRICE_CACHE_SCHEMA_VERSION:
        raise ValueError(f"unsupported market-price cache revision schema: {version}")
    cached = _required_dict(value.get("cached"), "cached revision observation")
    observed = _required_dict(
        value.get("observed_revision"), "observed revision"
    )
    common = {
        "provider": value.get("provider"),
        "provider_symbol": value.get("provider_symbol"),
        "market": value.get("market"),
        "session_date": value.get("session_date"),
        "price_type": value.get("price_type"),
        "is_adjusted": True,
    }
    cached_observation = _observation_from_payload({**common, **cached})
    observed_observation = _observation_from_payload({**common, **observed})
    revision = _revision(
        _required_string(value.get("company_id"), "company ID"),
        cached_observation,
        observed_observation,
    )
    if revision.revision_id != _required_string(
        value.get("revision_id"), "revision ID"
    ):
        raise ValueError("malformed market-price cache revision identity")
    return revision


def _observation_payload(observation: HistoricalPriceObservation) -> dict[str, Any]:
    return {
        "provider": observation.provider,
        "provider_symbol": observation.symbol,
        "market": observation.market,
        "session_date": observation.session_date.isoformat(),
        "close": observation.close,
        "adjusted_close": observation.adjusted_close,
        "currency": observation.currency,
        "retrieved_at": _format_timestamp(observation.retrieved_at),
        "price_type": observation.price_type,
        "is_adjusted": observation.is_adjusted,
    }


def _observation_from_payload(value: dict[str, Any]) -> HistoricalPriceObservation:
    if value.get("price_type") != ADJUSTED_PRICE_TYPE or value.get("is_adjusted") is not True:
        raise ValueError("market-price cache accepts adjusted closes only")
    return HistoricalPriceObservation(
        provider=_required_string(value.get("provider"), "provider"),
        symbol=_required_string(value.get("provider_symbol"), "provider symbol"),
        market=_required_string(value.get("market"), "market"),
        session_date=date.fromisoformat(
            _required_string(value.get("session_date"), "session date")
        ),
        close=_optional_number(value.get("close"), "close"),
        adjusted_close=_required_number(value.get("adjusted_close"), "adjusted close"),
        currency=_optional_string(value.get("currency"), "currency"),
        retrieved_at=_parse_timestamp(value.get("retrieved_at")),
        price_type=ADJUSTED_PRICE_TYPE,
        is_adjusted=True,
    )


def _content_id(prefix: str, payload: dict[str, Any]) -> str:
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return f"{prefix}-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:24]}"


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    raw = _required_string(value, "retrieved_at")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("market-price cache retrieved_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"malformed market-price cache {field_name}")
    return value.strip()


def _required_number(value: Any, field_name: str) -> float:
    parsed = _optional_number(value, field_name)
    if parsed is None:
        raise ValueError(f"malformed market-price cache {field_name}")
    return parsed


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"malformed market-price cache {field_name}")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"malformed market-price cache {field_name}")
    return parsed


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"malformed market-price cache {field_name}")
    return value.strip() or None


def _required_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"malformed market-price cache {field_name}")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
