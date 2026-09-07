"""Immutable single-response histories. Local IDs are NOT vendor adjustment IDs."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path

from investmentagent.market_prices import (
    ADJUSTED_PRICE_TYPE, HistoricalPriceHistory, HistoricalPriceObservation,
    SecurityReference,
)

HISTORY_SCHEMA_VERSION = 2
COHERENT_RETURN_METHOD = "single-response-adjusted-close-v1"
LEGACY_RETURN_METHOD = "legacy-adjusted-close-unverified-v1"
OUTCOME_REVISION_POLICY = "latest-calculation-visible-at-data-cutoff-v1"
CONSISTENCY_ASSUMPTION = "single accepted response; no vendor adjustment-version ID"


def content_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("history timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def observation_payload(row: HistoricalPriceObservation) -> dict:
    return {
        "provider": row.provider, "symbol": row.symbol, "market": row.market,
        "session_date": row.session_date.isoformat(), "close": row.close,
        "adjusted_close": row.adjusted_close, "currency": row.currency,
        "retrieved_at": timestamp(row.retrieved_at),
        "price_type": row.price_type, "is_adjusted": row.is_adjusted,
    }


def observation_from_payload(value: dict) -> HistoricalPriceObservation:
    return HistoricalPriceObservation(**{
        **value, "session_date": date.fromisoformat(value["session_date"]),
        "retrieved_at": datetime.fromisoformat(value["retrieved_at"].replace("Z", "+00:00")),
    })


def observations_hash(rows: tuple[HistoricalPriceObservation, ...]) -> str:
    # Content equality does not erase the identity or time of another retrieval.
    return content_hash([
        {key: value for key, value in observation_payload(row).items() if key != "retrieved_at"}
        for row in rows
    ])


@dataclass(frozen=True)
class HistoryMetadata:
    schema_version: int
    company_id: str
    isin: str | None
    provider: str
    symbol: str
    exchange: str
    market: str
    requested_start: date
    requested_end: date
    actual_sessions: tuple[date, ...]
    completed_at: datetime
    response_id: str
    content_hash: str
    currency: str
    currency_provenance: str
    price_type: str = ADJUSTED_PRICE_TYPE
    consistency_assumption: str = CONSISTENCY_ASSUMPTION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != HISTORY_SCHEMA_VERSION:
            raise ValueError("unsupported coherent history schema")
        for name in ("company_id", "provider", "symbol", "exchange", "market", "response_id", "currency", "currency_provenance"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"history requires {name}")
        if self.price_type != ADJUSTED_PRICE_TYPE or self.consistency_assumption != CONSISTENCY_ASSUMPTION:
            raise ValueError("unsupported history adjustment convention")
        if len(self.content_hash) != 64 or any(c not in "0123456789abcdef" for c in self.content_hash):
            raise ValueError("malformed history content hash")
        timestamp(self.completed_at)
        if not self.actual_sessions or tuple(sorted(set(self.actual_sessions))) != self.actual_sessions:
            raise ValueError("history sessions must be unique and ascending")
        if self.requested_start > self.actual_sessions[0] or self.requested_end < self.actual_sessions[-1]:
            raise ValueError("history sessions outside requested range")

    def as_payload(self) -> dict:
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result.update(
            requested_start=self.requested_start.isoformat(),
            requested_end=self.requested_end.isoformat(),
            actual_sessions=[day.isoformat() for day in self.actual_sessions],
            completed_at=timestamp(self.completed_at),
        )
        return result

    @cached_property
    def batch_id(self) -> str:
        return "history-" + content_hash(self.as_payload())

    @classmethod
    def from_payload(cls, value: dict) -> HistoryMetadata:
        return cls(**{
            **value,
            "requested_start": date.fromisoformat(value["requested_start"]),
            "requested_end": date.fromisoformat(value["requested_end"]),
            "actual_sessions": tuple(date.fromisoformat(day) for day in value["actual_sessions"]),
            "completed_at": datetime.fromisoformat(value["completed_at"].replace("Z", "+00:00")),
        })

    def validate_observation(self, row: HistoricalPriceObservation) -> None:
        if (row.provider, row.symbol, row.market, row.currency, row.retrieved_at) != (
            self.provider, self.symbol, self.market, self.currency, self.completed_at,
        ) or row.session_date not in self.actual_sessions:
            raise ValueError("observation conflicts with response identity, currency, or completion")


@dataclass(frozen=True)
class PriceHistoryBatch:
    metadata: HistoryMetadata
    observations: tuple[HistoricalPriceObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        if tuple(row.session_date for row in self.observations) != self.metadata.actual_sessions:
            raise ValueError("history observation sessions mismatch")
        for row in self.observations:
            self.metadata.validate_observation(row)
        if observations_hash(self.observations) != self.metadata.content_hash:
            raise ValueError("history content hash mismatch")

    @classmethod
    def accept(cls, security: SecurityReference, history: HistoricalPriceHistory,
               start: date, end: date) -> PriceHistoryBatch:
        # EODHD's per-symbol EOD endpoint returns one unpaginated date-range array.
        # Its adjusted_close covers splits AND dividends; raw OHLC never substitutes.
        # https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
        # Separately fetched pages/candidates must never be concatenated here.
        if history.status != "ok" or not history.response_id or history.completed_at is None:
            raise ValueError("coherent history requires explicit single-response provenance")
        currency = history.observations[0].currency
        if security.currency is not None and security.currency != currency:
            raise ValueError("history currency conflicts with security reference")
        return cls(HistoryMetadata(
            HISTORY_SCHEMA_VERSION, security.company_id, security.isin,
            history.provider, history.symbol, security.exchange, history.market,
            start, end, tuple(row.session_date for row in history.observations),
            history.completed_at, history.response_id, observations_hash(history.observations),
            currency, history.currency_provenance,
        ), history.observations)

    def covers(self, entry: date, exit: date) -> bool:
        return entry in self.metadata.actual_sessions and exit in self.metadata.actual_sessions

    def as_history(self) -> HistoricalPriceHistory:
        meta = self.metadata
        return HistoricalPriceHistory(
            "ok", meta.provider, meta.symbol, meta.market, self.observations,
            response_id=meta.response_id, completed_at=meta.completed_at,
            currency_provenance=meta.currency_provenance,
        )

    def evidence(self, entry: date, exit: date) -> EndpointEvidence:
        rows = {row.session_date: row for row in self.observations}
        return EndpointEvidence(self.metadata, rows[entry], rows[exit])

    def as_payload(self) -> dict:
        return {"batch_id": self.metadata.batch_id, "metadata": self.metadata.as_payload(),
                "observations": [observation_payload(row) for row in self.observations]}

    @classmethod
    def from_payload(cls, value: dict) -> PriceHistoryBatch:
        batch = cls(HistoryMetadata.from_payload(value["metadata"]), tuple(
            observation_from_payload(row) for row in value["observations"]))
        if value["batch_id"] != batch.metadata.batch_id:
            raise ValueError("history batch identity mismatch")
        return batch


@dataclass(frozen=True)
class EndpointEvidence:
    """Self-contained endpoints, not the complete vendor history, for public outcomes."""
    metadata: HistoryMetadata
    entry: HistoricalPriceObservation
    exit: HistoricalPriceObservation

    def __post_init__(self) -> None:
        self.metadata.validate_observation(self.entry)
        self.metadata.validate_observation(self.exit)

    def as_payload(self) -> dict:
        return {
            "batch_id": self.metadata.batch_id, "metadata": self.metadata.as_payload(),
            "entry": observation_payload(self.entry), "exit": observation_payload(self.exit),
            "entry_observation_id": self.observation_id(self.entry),
            "exit_observation_id": self.observation_id(self.exit),
        }

    def observation_id(self, row: HistoricalPriceObservation) -> str:
        return "endpoint-" + content_hash([self.metadata.batch_id, observation_payload(row)])

    @classmethod
    def from_payload(cls, value: dict) -> EndpointEvidence:
        evidence = cls(HistoryMetadata.from_payload(value["metadata"]),
                       observation_from_payload(value["entry"]), observation_from_payload(value["exit"]))
        if evidence.as_payload() != value:
            raise ValueError("outcome endpoint evidence identity mismatch")
        return evidence


class HistoryArchive:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.batches: tuple[PriceHistoryBatch, ...] = ()
        if path is not None and path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if type(payload["schema_version"]) is not int or payload["schema_version"] != HISTORY_SCHEMA_VERSION:
                    raise ValueError("unsupported coherent history archive schema")
                self.batches = tuple(PriceHistoryBatch.from_payload(item) for item in payload["histories"])
                if len({batch.metadata.batch_id for batch in self.batches}) != len(self.batches):
                    raise ValueError("duplicate history batch")
                responses = [batch.metadata.response_id for batch in self.batches]
                if len(set(responses)) != len(responses):
                    raise ValueError("response identity reused")
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise ValueError(f"invalid coherent history archive: {path}") from exc

    def store(self, batch: PriceHistoryBatch) -> bool:
        for old in self.batches:
            if old.metadata.response_id == batch.metadata.response_id:
                if old != batch:
                    raise ValueError("cannot mutate an accepted response")
                return False
        batches = (*self.batches, batch)
        if self.path is not None:
            payload = {"schema_version": HISTORY_SCHEMA_VERSION,
                       "histories": [item.as_payload() for item in batches]}
            atomic_json(self.path, payload)
        self.batches = batches
        return True

    def find(self, security: SecurityReference, *, provider: str, market: str,
             entry: date, exit: date, symbol: str | None = None,
             data_cutoff: datetime | None = None) -> PriceHistoryBatch | None:
        candidates = [batch for batch in self.batches
            if batch.metadata.company_id == security.company_id
            and batch.metadata.isin == security.isin
            and batch.metadata.exchange == security.exchange
            and batch.metadata.provider == provider and batch.metadata.market == market
            and batch.metadata.currency == security.currency
            and (symbol is None or batch.metadata.symbol == symbol)
            and (data_cutoff is None or batch.metadata.completed_at <= data_cutoff)
            and batch.covers(entry, exit)]
        return max(candidates, key=lambda b: (b.metadata.completed_at, b.metadata.batch_id), default=None)

    def preferred_symbol(self, security: SecurityReference, *, provider: str,
                         market: str, data_cutoff: datetime) -> str | None:
        candidates = [batch.metadata for batch in self.batches
                      if batch.metadata.company_id == security.company_id
                      and batch.metadata.isin == security.isin
                      and batch.metadata.exchange == security.exchange
                      and batch.metadata.provider == provider and batch.metadata.market == market
                      and batch.metadata.currency == security.currency
                      and batch.metadata.completed_at <= data_cutoff]
        newest = max(candidates, key=lambda meta: (meta.completed_at, meta.batch_id), default=None)
        return newest.symbol if newest else None


def atomic_json(path: Path, payload: dict) -> None:
    content = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()
