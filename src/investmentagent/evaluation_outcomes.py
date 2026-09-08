from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable

from investmentagent.evaluation import EvaluationCompanyRow, EvaluationSnapshot, load_evaluation_snapshot
from investmentagent.market_calendar import (
    market_for_country,
    market_session,
)
from investmentagent.market_prices import (
    ADJUSTED_PRICE_TYPE,
    HistoricalPriceHistory,
    HistoricalPriceObservation,
    HistoricalPriceProvider,
    SecurityReference,
)
from investmentagent.market_price_cache import HistoricalPriceCache
from investmentagent.outcome_status import (
    BUDGET_DEFERRED_DETAIL, evidence_visible_at, fixed_sessions as _fixed_sessions,
    analysis_view, is_mature, lifecycle_counts,
)
from investmentagent.price_histories import (
    COHERENT_RETURN_METHOD, LEGACY_RETURN_METHOD, OUTCOME_REVISION_POLICY,
    EndpointEvidence, PriceHistoryBatch, HistoryArchive, HistoryMetadata, content_hash,
)


OUTCOME_SCHEMA_VERSION = 2
OUTCOME_STORE_SCHEMA_VERSION = 2
DEFAULT_MAX_PRICE_API_CALLS = 20
OUTCOME_STATUSES = {
    "not_due",
    "priced",
    "missing_entry",
    "missing_exit",
    "symbol_unresolved",
    "provider_error",
    "corporate_action_unsupported",
    "coherent_history_pending",
}
ENTRY_POLICY = "first_market_session_adjusted_close_after_decision"
ENTRY_REVISION_POLICY = (
    "fixed sessions; recalculate both adjusted endpoints from one response; retain revisions"
)


@dataclass(frozen=True)
class HorizonDefinition:
    label: str
    sessions: int

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("horizon label is required")
        if isinstance(self.sessions, bool) or self.sessions <= 0:
            raise ValueError("horizon sessions must be a positive integer")

    def as_payload(self) -> dict[str, Any]:
        return {"label": self.label, "sessions": self.sessions, "unit": "market_sessions"}


DEFAULT_STRATEGY_HORIZONS = {
    "trading": (
        HorizonDefinition("1_session", 1),
        HorizonDefinition("5_sessions", 5),
        HorizonDefinition("20_sessions", 20),
        HorizonDefinition("60_sessions", 60),
    ),
    "long-term": (
        HorizonDefinition("20_sessions", 20),
        HorizonDefinition("60_sessions", 60),
        HorizonDefinition("126_sessions", 126),
        HorizonDefinition("252_sessions", 252),
    ),
}


@dataclass(frozen=True)
class MarketOutcome:
    schema_version: int
    evaluation_run_id: str
    scoring_model_version: str
    strategy: str
    company_id: str
    isin: str | None
    ticker: str
    country: str
    exchange: str
    segment: str
    original_rank: int
    horizon_label: str
    horizon_sessions: int
    decision_at: datetime
    market: str
    entry_policy: str
    entry_reason: str
    entry_session: date
    target_exit_session: date
    actual_exit_session: date | None
    entry_price: float | None
    exit_price: float | None
    price_type: str
    is_adjusted: bool
    currency: str | None
    raw_forward_return_pct: float | None
    net_forward_return_pct: float | None
    status: str
    price_provider: str
    provider_symbol: str | None
    retrieved_at: datetime | None
    entry_retrieved_at: datetime | None
    exit_retrieved_at: datetime | None
    entry_revision_policy: str
    detail: str | None = None
    return_methodology: str = LEGACY_RETURN_METHOD
    calculated_at: datetime | None = None
    history_evidence: EndpointEvidence | None = None
    history_metadata: HistoryMetadata | None = None
    prior_revision_id: str | None = None
    revision_reason: str | None = None
    return_difference_pct: float | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in (1, OUTCOME_SCHEMA_VERSION):
            raise ValueError(f"unsupported market-outcome schema: {self.schema_version}")
        expected_method = LEGACY_RETURN_METHOD if self.schema_version == 1 else COHERENT_RETURN_METHOD
        if self.return_methodology != expected_method:
            raise ValueError("outcome schema and return methodology disagree")
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"unsupported market-outcome status: {self.status}")
        if self.strategy not in DEFAULT_STRATEGY_HORIZONS:
            raise ValueError("outcome strategy must be trading or long-term")
        if self.price_type != ADJUSTED_PRICE_TYPE or self.is_adjusted is not True:
            raise ValueError("Performance v2 outcomes require adjusted-close prices")
        if self.decision_at.tzinfo is None:
            raise ValueError("outcome decision timestamp must be timezone-aware")
        object.__setattr__(self, "decision_at", self.decision_at.astimezone(timezone.utc))
        for field_name in ("retrieved_at", "entry_retrieved_at", "exit_retrieved_at", "calculated_at"):
            value = getattr(self, field_name)
            if value is not None:
                if value.tzinfo is None:
                    raise ValueError(f"{field_name} must be timezone-aware")
                object.__setattr__(self, field_name, value.astimezone(timezone.utc))
        for field_name in ("entry_price", "exit_price"):
            value = getattr(self, field_name)
            if value is not None and not _positive_finite(value):
                raise ValueError(f"{field_name} must be a positive finite number")
        if self.raw_forward_return_pct is not None and not math.isfinite(
            self.raw_forward_return_pct
        ):
            raise ValueError("outcome return must be finite")
        if self.net_forward_return_pct is not None:
            raise ValueError("net returns are reserved for a future cost model")
        if self.status == "priced":
            required = (
                self.entry_price,
                self.exit_price,
                self.actual_exit_session,
                self.raw_forward_return_pct,
                self.provider_symbol,
                self.retrieved_at,
            )
            if any(value is None for value in required):
                raise ValueError("priced outcomes require complete price metadata")
        if self.actual_exit_session is not None and (
            self.actual_exit_session != self.target_exit_session
        ):
            raise ValueError("Performance v2 does not substitute a different exit session")
        if self.entry_price is not None and self.entry_retrieved_at is None:
            raise ValueError("established entry prices require retrieval provenance")
        if self.schema_version == 2:
            if self.history_metadata is not None:
                meta = self.history_metadata
                if (meta.company_id, meta.isin, meta.exchange, meta.provider, meta.symbol, meta.market, meta.currency) != (
                    self.company_id, self.isin, self.exchange, self.price_provider, self.provider_symbol, self.market, self.currency,
                ) or self.calculated_at is None or self.calculated_at < meta.completed_at:
                    raise ValueError("partial outcome history metadata mismatch")
                if self.history_evidence is not None and meta != self.history_evidence.metadata:
                    raise ValueError("conflicting outcome history metadata")
            if self.status != "priced" and self.raw_forward_return_pct is not None:
                raise ValueError("unresolved coherent outcome cannot contain a return")
            if self.status == "priced":
                evidence = self.history_evidence
                if evidence is None or self.calculated_at is None:
                    raise ValueError("coherent priced outcomes require endpoint evidence and calculation time")
                meta = evidence.metadata
                if (meta.company_id, meta.isin, meta.exchange, meta.provider, meta.symbol, meta.market, meta.currency) != (
                    self.company_id, self.isin, self.exchange, self.price_provider, self.provider_symbol, self.market, self.currency,
                ) or (evidence.entry.session_date, evidence.exit.session_date) != (self.entry_session, self.target_exit_session):
                    raise ValueError("outcome evidence conflicts with fixed security or sessions")
                if (self.entry_price, self.exit_price, self.entry_retrieved_at, self.exit_retrieved_at) != (
                    evidence.entry.adjusted_close, evidence.exit.adjusted_close, meta.completed_at, meta.completed_at,
                ) or self.calculated_at < meta.completed_at:
                    raise ValueError("outcome evidence values or timestamps disagree")
                # Only floating-point ratio roundoff, never an economic change, is tolerated.
                expected = (self.exit_price / self.entry_price - 1) * 100
                if not math.isclose(self.raw_forward_return_pct, expected, rel_tol=1e-12, abs_tol=1e-10):
                    raise ValueError("outcome return does not reproduce from evidence")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.evaluation_run_id, self.company_id, self.horizon_label

    @cached_property
    def revision_id(self) -> str:
        return "outcome-" + content_hash(self.as_payload(include_identity=False))

    def as_payload(self, *, include_identity: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "evaluation_run_id": self.evaluation_run_id,
            "scoring_model_version": self.scoring_model_version,
            "strategy": self.strategy,
            "company_id": self.company_id,
            "isin": self.isin,
            "ticker": self.ticker,
            "country": self.country,
            "exchange": self.exchange,
            "segment": self.segment,
            "original_rank": self.original_rank,
            "horizon": {
                "label": self.horizon_label,
                "sessions": self.horizon_sessions,
                "unit": "market_sessions",
            },
            "decision_at": _format_timestamp(self.decision_at),
            "market": self.market,
            "entry_policy": self.entry_policy,
            "entry_reason": self.entry_reason,
            "entry_session": self.entry_session.isoformat(),
            "target_exit_session": self.target_exit_session.isoformat(),
            "actual_exit_session": _format_date(self.actual_exit_session),
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "price_type": self.price_type,
            "is_adjusted": self.is_adjusted,
            "currency": self.currency,
            "raw_forward_return_pct": self.raw_forward_return_pct,
            "net_forward_return_pct": self.net_forward_return_pct,
            "return_basis": "gross",
            "status": self.status,
            "price_provider": self.price_provider,
            "provider_symbol": self.provider_symbol,
            "retrieved_at": _format_optional_timestamp(self.retrieved_at),
            "entry_retrieved_at": _format_optional_timestamp(self.entry_retrieved_at),
            "exit_retrieved_at": _format_optional_timestamp(self.exit_retrieved_at),
            "entry_revision_policy": self.entry_revision_policy,
            "detail": self.detail,
        }
        if self.schema_version == 2:
            payload.update(
                return_methodology=self.return_methodology,
                calculated_at=_format_optional_timestamp(self.calculated_at),
                history_evidence=self.history_evidence.as_payload() if self.history_evidence else None,
                history_metadata=self.history_metadata.as_payload() if self.history_metadata else None,
                history_batch_id=(self.history_evidence.metadata.batch_id if self.history_evidence else
                                  self.history_metadata.batch_id if self.history_metadata else None),
                prior_revision_id=self.prior_revision_id, revision_reason=self.revision_reason,
                return_difference_pct=self.return_difference_pct,
            )
            if include_identity:
                payload["outcome_revision_id"] = self.revision_id
        return payload


@dataclass(frozen=True)
class EvaluationOutcomeSet:
    schema_version: int
    evaluation_run_id: str
    evaluation_schema_version: int
    report_date: date
    strategy: str
    scoring_model_version: str
    horizon_definitions: tuple[HorizonDefinition, ...]
    outcomes: tuple[MarketOutcome, ...]
    revisions: tuple[MarketOutcome, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(self, "revisions", tuple(self.revisions))
        if type(self.schema_version) is not int or self.schema_version not in (1, OUTCOME_STORE_SCHEMA_VERSION):
            raise ValueError(f"unsupported outcome-store schema: {self.schema_version}")
        keys = [outcome.key for outcome in self.outcomes]
        if len(keys) != len(set(keys)):
            raise ValueError("outcome-store records must have unique identities")
        if any(outcome.evaluation_run_id != self.evaluation_run_id for outcome in self.outcomes):
            raise ValueError("outcome-store run identity mismatch")
        if any(outcome.strategy != self.strategy for outcome in self.outcomes):
            raise ValueError("outcome-store strategy mismatch")
        if any(
            outcome.scoring_model_version != self.scoring_model_version
            for outcome in self.outcomes
        ):
            raise ValueError("outcome-store model-version mismatch")
        expected_horizons = {
            (definition.label, definition.sessions)
            for definition in self.horizon_definitions
        }
        actual_horizons = {
            (outcome.horizon_label, outcome.horizon_sessions)
            for outcome in self.outcomes
        }
        if actual_horizons and actual_horizons != expected_horizons:
            raise ValueError("outcome-store horizon definitions do not match records")
        if any(outcome.schema_version != self.schema_version for outcome in self.outcomes):
            raise ValueError("mixed return methodologies in outcome store")
        records = (*self.revisions, *self.outcomes)
        by_id = {outcome.revision_id: outcome for outcome in records}
        current_by_key = {outcome.key: outcome for outcome in self.outcomes}
        if len(by_id) != len(records):
            raise ValueError("duplicate outcome revisions")
        for outcome in records:
            current = current_by_key.get(outcome.key)
            immutable = ("evaluation_run_id", "scoring_model_version", "strategy", "company_id", "isin",
                         "ticker", "country", "exchange", "segment", "original_rank", "horizon_label",
                         "horizon_sessions", "decision_at", "market", "entry_policy", "entry_reason",
                         "entry_session", "target_exit_session")
            if current is None or any(getattr(current, name) != getattr(outcome, name) for name in immutable):
                raise ValueError("outcome revision changed immutable decision or session metadata")
            if outcome.prior_revision_id is not None:
                prior = by_id.get(outcome.prior_revision_id)
                if prior is None or prior.key != outcome.key:
                    raise ValueError("missing or mismatched prior outcome revision")
                if outcome.return_difference_pct is not None:
                    if prior.raw_forward_return_pct is None or outcome.raw_forward_return_pct is None or not math.isclose(
                        outcome.return_difference_pct, outcome.raw_forward_return_pct - prior.raw_forward_return_pct,
                        rel_tol=1e-12, abs_tol=1e-10,
                    ):
                        raise ValueError("outcome revision numerical difference mismatch")

    @property
    def return_methodology(self) -> str:
        return LEGACY_RETURN_METHOD if self.schema_version == 1 else COHERENT_RETURN_METHOD

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "evaluation_run_id": self.evaluation_run_id,
            "evaluation_schema_version": self.evaluation_schema_version,
            "report_date": self.report_date.isoformat(),
            "strategy": self.strategy,
            "scoring_model_version": self.scoring_model_version,
            "entry_policy": ENTRY_POLICY,
            "price_basis": ADJUSTED_PRICE_TYPE,
            "return_basis": "gross",
            "horizon_definitions": [
                definition.as_payload() for definition in self.horizon_definitions
            ],
            "outcomes": [
                outcome.as_payload()
                for outcome in sorted(
                    self.outcomes,
                    key=lambda item: (item.original_rank, item.horizon_sessions),
                )
            ],
        }
        if self.schema_version == 2:
            payload.update(return_methodology=self.return_methodology,
                           revision_policy=OUTCOME_REVISION_POLICY,
                           revisions=[outcome.as_payload() for outcome in self.revisions])
        return payload


@dataclass(frozen=True)
class OutcomeRefreshSummary:
    evaluation_runs: int
    outcome_records: int
    priced: int
    not_due: int
    unresolved: int
    files_written: tuple[Path, ...]
    securities_requiring_prices: int = 0
    required_session_observations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    provider_calls_planned: int = 0
    provider_calls_executed: int = 0
    api_budget: int | None = None
    work_deferred_by_budget: int = 0
    deferred_api_calls: int = 0
    observations_stored: int = 0
    provider_errors: int = 0
    unresolved_symbols: int = 0
    revisions_detected: int = 0
    oldest_unresolved_evaluation_date: date | None = None
    deferred_security_ids: tuple[str, ...] = ()
    fetch_plan: tuple[PriceFetchPlanItem, ...] = ()
    cache_coverage: dict[str, Any] | None = None
    legacy_records_skipped: int = 0
    coherent_records_reusable: int = 0
    records_requiring_refetch: int = 0
    records_missing_metadata: int = 0
    dry_run: bool = False
    lifecycle: dict[str, Any] | None = None


@dataclass(frozen=True)
class PriceFetchPlanItem:
    company_id: str
    ticker: str
    country: str
    market: str
    provider_symbol: str | None
    start_date: date
    end_date: date
    missing_session_dates: tuple[date, ...]
    estimated_api_calls: int
    has_unestablished_entry: bool
    shortest_due_horizon_sessions: int
    oldest_evaluation_date: date
    deferred_by_budget: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "ticker": self.ticker,
            "country": self.country,
            "market": self.market,
            "provider_symbol": self.provider_symbol,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "missing_session_dates": [
                value.isoformat() for value in self.missing_session_dates
            ],
            "estimated_api_calls": self.estimated_api_calls,
            "has_unestablished_entry": self.has_unestablished_entry,
            "shortest_due_horizon_sessions": self.shortest_due_horizon_sessions,
            "oldest_evaluation_date": self.oldest_evaluation_date.isoformat(),
            "deferred_by_budget": self.deferred_by_budget,
        }


@dataclass(frozen=True)
class _PreparedCompanyOutcomes:
    row: EvaluationCompanyRow
    outcomes: tuple[MarketOutcome, ...]
    refreshable: tuple[MarketOutcome, ...]


@dataclass(frozen=True)
class _PreparedEvaluationOutcomes:
    snapshot: EvaluationSnapshot
    definitions: tuple[HorizonDefinition, ...]
    companies: tuple[_PreparedCompanyOutcomes, ...]
    existing: EvaluationOutcomeSet | None = None


@dataclass
class _SecurityRequirement:
    security: SecurityReference
    market: str
    required_dates: set[date]
    range_start: date
    range_end: date
    known_symbols: set[str]
    has_unestablished_entry: bool
    shortest_due_horizon_sessions: int
    oldest_evaluation_date: date


def refresh_evaluation_outcomes(
    snapshot: EvaluationSnapshot,
    provider: HistoricalPriceProvider,
    *,
    retrieved_at: datetime,
    existing: EvaluationOutcomeSet | None = None,
    horizons: tuple[HorizonDefinition, ...] | None = None,
    reprice: bool = False,
) -> EvaluationOutcomeSet:
    retrieval_time = _utc_timestamp(retrieved_at, "retrieved_at")
    if existing is not None and existing.schema_version == 1 and not reprice:
        _validate_existing_store(existing, snapshot, horizons or DEFAULT_STRATEGY_HORIZONS[snapshot.strategy])
        return existing
    prepared = _prepare_evaluation_outcomes(
        snapshot, provider_name=provider.name, retrieved_at=retrieval_time,
        existing=existing, horizons=horizons, reprice=reprice,
    )
    outcomes = []
    for company in prepared.companies:
        history, batch = None, None
        if company.refreshable:
            start = min(o.entry_session for o in company.refreshable)
            end = max(o.target_exit_session for o in company.refreshable)
            known = {o.provider_symbol for o in company.refreshable if o.provider_symbol}
            if len(known) > 1:
                raise ValueError("established entries disagree on provider symbol")
            history, batch = _fetch_batch(
                provider, _security_reference(company.row), company.refreshable[0].market,
                start, end, retrieval_time, next(iter(known), None),
            )
        for outcome in company.outcomes:
            outcomes.append(_outcome_from_history(outcome, history, _calculation_time(provider, retrieval_time), batch=batch)
                            if history is not None and outcome in company.refreshable else outcome)
    return _build_outcome_set(prepared, outcomes)


def refresh_outcome_store(
    evaluation_root: Path, outcome_root: Path, provider: HistoricalPriceProvider, *,
    retrieved_at: datetime, strategy: str | None = None, run_id: str | None = None,
    report_date: date | None = None, price_cache: HistoricalPriceCache | None = None,
    max_price_api_calls: int | None = None, reprice: bool = False, dry_run: bool = False,
) -> OutcomeRefreshSummary:
    if max_price_api_calls is not None and (
        isinstance(max_price_api_calls, bool) or max_price_api_calls < 0
    ):
        raise ValueError("maximum price API calls must be at least zero")
    if price_cache is not None and max_price_api_calls is None:
        raise ValueError("cached outcome refresh requires an explicit API budget")
    snapshots = discover_evaluation_snapshots(
        evaluation_root, strategy=strategy, run_id=run_id, report_date=report_date,
    )
    return _refresh_outcome_store_with_cache(
        snapshots, outcome_root, provider, price_cache,
        retrieved_at=_utc_timestamp(retrieved_at, "retrieved_at"),
        max_price_api_calls=max_price_api_calls if max_price_api_calls is not None else DEFAULT_MAX_PRICE_API_CALLS,
        reprice=reprice, dry_run=dry_run,
    )


def _calculation_time(provider: HistoricalPriceProvider, scheduled_at: datetime) -> datetime:
    clock = getattr(provider, "calculation_time", None)
    return _utc_timestamp(clock(scheduled_at) if callable(clock) else datetime.now(timezone.utc), "calculated_at")


def _fetch_batch(
    provider: HistoricalPriceProvider, security: SecurityReference, market: str,
    start: date, end: date, retrieval_time: datetime, symbol: str | None,
) -> tuple[HistoricalPriceHistory, PriceHistoryBatch | None]:
    history = provider.get_history(
        security, start_date=start, end_date=end, market=market,
        retrieved_at=retrieval_time, symbol=symbol,
    )
    if history.status != "ok":
        return history, None
    try:
        if history.provider != provider.name or history.market != market:
            raise ValueError("response provider or market conflicts with request")
        if symbol is not None and history.symbol != symbol:
            raise ValueError("response symbol conflicts with established symbol")
        batch = PriceHistoryBatch.accept(security, history, start, end)
    except ValueError as exc:
        return HistoricalPriceHistory("provider_error", provider.name, symbol, market,
                                      detail=str(exc)), None
    return history, batch


def _refresh_outcome_store_with_cache(
    snapshots: tuple[EvaluationSnapshot, ...], outcome_root: Path,
    provider: HistoricalPriceProvider, price_cache: HistoricalPriceCache | None, *,
    retrieved_at: datetime, max_price_api_calls: int,
    reprice: bool = False, dry_run: bool = False,
) -> OutcomeRefreshSummary:
    archive = price_cache.history_archive if price_cache is not None else HistoryArchive()
    prepared_runs = []
    paths = {}
    requirements = {}
    hits = {}
    security_identities = {}
    legacy_skipped = reusable = refetch = missing_metadata = 0
    for snapshot in snapshots:
        path = outcome_store_path(outcome_root, snapshot)
        existing = load_outcome_set(path) if path.exists() else None
        if existing is not None and existing.schema_version == 1:
            repaired_path = path.with_name(f"{path.stem}.coherent-v1.json")
            if repaired_path.exists():
                existing = load_outcome_set(repaired_path)
            elif not reprice:
                legacy_skipped += len(existing.outcomes)
                continue
            path = repaired_path
        paths[snapshot.run_id] = path
        prepared = _prepare_evaluation_outcomes(
            snapshot, provider_name=provider.name, retrieved_at=retrieved_at,
            existing=existing, horizons=None, reprice=reprice,
        )
        prepared_runs.append(prepared)
        for company in prepared.companies:
            security = _security_reference(company.row)
            for outcome in company.refreshable:
                key = (security.company_id, outcome.market)
                identity = (security.isin, security.country, security.exchange)
                if key in security_identities and security_identities[key] != identity:
                    raise ValueError("stable company identity maps to conflicting securities")
                security_identities[key] = identity
                batch = archive.find(
                    security, provider=provider.name, market=outcome.market,
                    entry=outcome.entry_session, exit=outcome.target_exit_session,
                    symbol=outcome.provider_symbol, data_cutoff=retrieved_at,
                )
                # Repricing explicitly requests a fresh response, not a relabelled cache hit.
                if batch is not None and not reprice:
                    hits[outcome.key] = batch
                    reusable += 1
                    continue
                if batch is not None:
                    reusable += 1
                else:
                    refetch += 1
                if existing is not None and existing.schema_version == 1:
                    missing_metadata += 1
                key = (security.company_id, outcome.market)
                requirement = requirements.get(key)
                if requirement is None:
                    requirement = _SecurityRequirement(
                        security, outcome.market, set(), outcome.entry_session,
                        outcome.target_exit_session, set(), outcome.entry_price is None,
                        outcome.horizon_sessions, snapshot.report_date,
                    )
                    requirements[key] = requirement
                if (requirement.security.isin, requirement.security.country, requirement.security.exchange) != (
                    security.isin, security.country, security.exchange,
                ):
                    raise ValueError("stable company identity maps to conflicting securities")
                requirement.required_dates.update((outcome.entry_session, outcome.target_exit_session))
                requirement.range_start = min(requirement.range_start, outcome.entry_session)
                requirement.range_end = max(requirement.range_end, outcome.target_exit_session)
                if outcome.provider_symbol:
                    requirement.known_symbols.add(outcome.provider_symbol)
                requirement.has_unestablished_entry |= outcome.entry_price is None
                requirement.shortest_due_horizon_sessions = min(requirement.shortest_due_horizon_sessions, outcome.horizon_sessions)
                requirement.oldest_evaluation_date = min(requirement.oldest_evaluation_date, snapshot.report_date)

    tasks = []
    for key, requirement in requirements.items():
        if len(requirement.known_symbols) > 1:
            raise ValueError("established entries disagree on provider symbol")
        symbol = next(iter(requirement.known_symbols), None)
        if symbol is None:
            symbol = archive.preferred_symbol(
                requirement.security, provider=provider.name, market=requirement.market,
                data_cutoff=retrieved_at,
            )
        # Legacy symbol metadata can reduce alternate attempts, but never proves price coherence.
        if symbol is None and price_cache is not None:
            symbol = price_cache.preferred_symbol(
                requirement.security.company_id, provider=provider.name, market=requirement.market)
        task = PriceFetchPlanItem(
            requirement.security.company_id, requirement.security.ticker,
            requirement.security.country, requirement.market, symbol,
            requirement.range_start, requirement.range_end,
            tuple(sorted(requirement.required_dates)),
            _estimated_provider_api_calls(provider, requirement.security, symbol=symbol),
            requirement.has_unestablished_entry, requirement.shortest_due_horizon_sessions,
            requirement.oldest_evaluation_date,
        )
        tasks.append((key, task))
    tasks.sort(key=lambda item: (
        not item[1].has_unestablished_entry, item[1].shortest_due_horizon_sessions,
        item[1].end_date, item[1].oldest_evaluation_date, item[1].company_id, item[1].market,
    ))
    plan, planned_calls = [], 0
    for key, task in tasks:
        if planned_calls + task.estimated_api_calls <= max_price_api_calls:
            planned_calls += task.estimated_api_calls
        else:
            task = replace(task, deferred_by_budget=True)
        plan.append((key, task))
    calls_before = _provider_api_call_count(provider)
    fetched = {}
    observations_stored = provider_errors = unresolved_symbols = 0
    if not dry_run:
        for key, task in plan:
            if task.deferred_by_budget:
                continue
            history, batch = _fetch_batch(
                provider, requirements[key].security, task.market, task.start_date,
                task.end_date, retrieved_at, task.provider_symbol,
            )
            fetched[key] = (history, batch)
            if batch is not None and archive.store(batch):
                observations_stored += len(batch.observations)
            provider_errors += history.status == "provider_error"
            unresolved_symbols += history.status == "symbol_unresolved"
    executed = _provider_api_call_count(provider) - calls_before
    if executed > max_price_api_calls:
        raise RuntimeError("historical-price provider exceeded the API-call budget")
    files, all_outcomes = [], []
    revisions_detected = 0
    deferred_keys = {key for key, task in plan if task.deferred_by_budget}
    for prepared in prepared_runs:
        outcomes = []
        for company in prepared.companies:
            for outcome in company.outcomes:
                current = outcome
                if outcome in company.refreshable and dry_run:
                    if outcome.status == "not_due":
                        current = _pending_outcome(outcome, retrieved_at,
                            deferred_by_budget=(outcome.company_id, outcome.market) in deferred_keys)
                elif outcome in company.refreshable:
                    batch = hits.get(outcome.key)
                    history = batch.as_history() if batch is not None else None
                    if history is None:
                        history, batch = fetched.get((outcome.company_id, outcome.market), (None, None))
                    if history is None:
                        current = outcome if outcome.status == "priced" else _pending_outcome(outcome, _calculation_time(provider, retrieved_at))
                    else:
                        current = _outcome_from_history(outcome, history, _calculation_time(provider, retrieved_at), batch=batch)
                    revisions_detected += current.revision_reason == "coherent_endpoint_revision"
                outcomes.append(current)
        if not dry_run:
            refreshed = _build_outcome_set(prepared, outcomes)
            path = paths[prepared.snapshot.run_id]
            save_outcome_set(path, refreshed)
            files.append(path)
        all_outcomes.extend(outcomes)
    deferred = [task for _, task in plan if task.deferred_by_budget]
    # Scheduling remains bounded by retrieved_at; final diagnostics include only
    # evidence actually available by completion, not the current wall clock.
    completed_at = retrieved_at if dry_run else max([retrieved_at, *(evidence_visible_at(o) for o in all_outcomes)])
    lifecycle = lifecycle_counts(all_outcomes, completed_at)
    return OutcomeRefreshSummary(
        evaluation_runs=len(prepared_runs), outcome_records=len(all_outcomes),
        priced=lifecycle["mature_priced"],
        not_due=lifecycle["not_mature"],
        unresolved=lifecycle["mature"] - lifecycle["mature_priced"],
        files_written=tuple(files), securities_requiring_prices=len(requirements),
        required_session_observations=sum(len(r.required_dates) for r in requirements.values()) + 2 * len(hits),
        cache_hits=2 * len(hits), cache_misses=sum(len(r.required_dates) for r in requirements.values()),
        provider_calls_planned=planned_calls, provider_calls_executed=executed,
        api_budget=max_price_api_calls, work_deferred_by_budget=len(deferred),
        deferred_api_calls=sum(t.estimated_api_calls for t in deferred),
        observations_stored=observations_stored, provider_errors=provider_errors,
        unresolved_symbols=unresolved_symbols, revisions_detected=revisions_detected,
        oldest_unresolved_evaluation_date=_oldest_unresolved_evaluation_date(
            prepared_runs, all_outcomes, retrieved_at=retrieved_at),
        deferred_security_ids=tuple(t.company_id for t in deferred),
        fetch_plan=tuple(t for _, t in plan),
        cache_coverage={"coherent_histories": len(archive.batches),
                        "legacy_unverified": price_cache.coverage().as_dict() if price_cache else None},
        legacy_records_skipped=legacy_skipped, coherent_records_reusable=reusable,
        records_requiring_refetch=refetch, records_missing_metadata=missing_metadata,
        dry_run=dry_run,
        lifecycle=lifecycle,
    )


def _prepare_evaluation_outcomes(
    snapshot: EvaluationSnapshot,
    *,
    provider_name: str,
    retrieved_at: datetime,
    existing: EvaluationOutcomeSet | None,
    horizons: tuple[HorizonDefinition, ...] | None,
    reprice: bool = False,
) -> _PreparedEvaluationOutcomes:
    definitions = horizons or DEFAULT_STRATEGY_HORIZONS[snapshot.strategy]
    if existing is not None:
        _validate_existing_store(existing, snapshot, definitions)
    existing_by_key = {
        (outcome.company_id, outcome.horizon_label): outcome
        for outcome in (existing.outcomes if existing is not None else ())
    }
    companies = []
    for row in snapshot.rows:
        outcomes = tuple(
            _coherent_base(existing_by_key[(row.company_id, horizon.label)])
            if (row.company_id, horizon.label) in existing_by_key
            else _initial_outcome(snapshot, row, horizon, provider_name)
            for horizon in definitions
        )
        companies.append(
            _PreparedCompanyOutcomes(
                row=row,
                outcomes=outcomes,
                refreshable=tuple(
                    outcome
                    for outcome in outcomes
                    if _should_refresh(outcome, retrieved_at, reprice=reprice)
                ),
            )
        )
    return _PreparedEvaluationOutcomes(
        snapshot=snapshot,
        definitions=tuple(definitions),
        companies=tuple(companies),
        existing=existing,
    )


def _build_outcome_set(
    prepared: _PreparedEvaluationOutcomes,
    outcomes: Iterable[MarketOutcome],
) -> EvaluationOutcomeSet:
    snapshot = prepared.snapshot
    outcomes = tuple(outcomes)
    candidates = list(prepared.existing.revisions) if prepared.existing else []
    if prepared.existing:
        candidates.extend(prepared.existing.outcomes)
    candidates.extend(o for company in prepared.companies for o in company.outcomes)
    current_ids = {o.revision_id for o in outcomes}
    revisions = {o.revision_id: o for o in candidates if o.revision_id not in current_ids}
    return EvaluationOutcomeSet(
        schema_version=OUTCOME_STORE_SCHEMA_VERSION,
        evaluation_run_id=snapshot.run_id,
        evaluation_schema_version=snapshot.schema_version,
        report_date=snapshot.report_date,
        strategy=snapshot.strategy,
        scoring_model_version=snapshot.scoring_model_version,
        horizon_definitions=prepared.definitions,
        outcomes=tuple(outcomes),
        revisions=tuple(revisions.values()),
    )


def _estimated_provider_api_calls(
    provider: HistoricalPriceProvider,
    security: SecurityReference,
    *,
    symbol: str | None,
) -> int:
    estimator = getattr(provider, "estimated_api_calls", None)
    estimated = estimator(security, symbol=symbol) if callable(estimator) else 1
    if isinstance(estimated, bool) or not isinstance(estimated, int) or estimated < 0:
        raise ValueError("historical-price provider returned an invalid call estimate")
    return estimated


def _provider_api_call_count(provider: HistoricalPriceProvider) -> int:
    value = getattr(provider, "api_call_count", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("historical-price provider returned an invalid call count")
    return value


def _oldest_unresolved_evaluation_date(
    prepared_runs: list[_PreparedEvaluationOutcomes],
    outcomes: list[MarketOutcome],
    *,
    retrieved_at: datetime,
) -> date | None:
    report_dates = {
        prepared.snapshot.run_id: prepared.snapshot.report_date
        for prepared in prepared_runs
    }
    unresolved_dates = []
    for outcome in outcomes:
        target = market_session(outcome.target_exit_session, outcome.market)
        if (
            target is not None
            and target.closes_at <= retrieved_at
            and outcome.status != "priced"
        ):
            unresolved_dates.append(report_dates[outcome.evaluation_run_id])
    return min(unresolved_dates) if unresolved_dates else None


def discover_evaluation_snapshots(
    root: Path,
    *,
    strategy: str | None = None,
    run_id: str | None = None,
    report_date: date | None = None,
) -> tuple[EvaluationSnapshot, ...]:
    if not root.exists():
        return ()
    snapshots: list[EvaluationSnapshot] = []
    seen_runs: set[str] = set()
    for path in sorted(root.rglob("*.jsonl")):
        snapshot = load_evaluation_snapshot(path)
        if strategy is not None and snapshot.strategy != strategy:
            continue
        if run_id is not None and snapshot.run_id != run_id:
            continue
        if report_date is not None and snapshot.report_date != report_date:
            continue
        if snapshot.run_id in seen_runs:
            raise ValueError(f"duplicate evaluation run discovered: {snapshot.run_id}")
        seen_runs.add(snapshot.run_id)
        snapshots.append(snapshot)
    return tuple(sorted(snapshots, key=lambda item: (item.decision_at, item.strategy)))


def discover_outcome_sets(root: Path) -> tuple[EvaluationOutcomeSet, ...]:
    if not root.exists():
        return ()
    stores = tuple(load_outcome_set(path) for path in sorted(root.rglob("*.json")))
    run_ids = [(store.evaluation_run_id, store.return_methodology) for store in stores]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate outcome stores discovered")
    return stores


def outcome_store_path(root: Path, snapshot: EvaluationSnapshot) -> Path:
    return (
        root
        / snapshot.report_date.isoformat()
        / snapshot.strategy
        / f"{snapshot.run_id}.json"
    )


def save_outcome_set(path: Path, outcome_set: EvaluationOutcomeSet) -> Path:
    content = serialize_outcome_set(outcome_set)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return path
    if path.exists():
        old = load_outcome_set(path)
        if old.schema_version == 1:
            raise ValueError("legacy outcome files are read-only; write a separate coherent store")
        old_ids = {o.revision_id for o in (*old.revisions, *old.outcomes)}
        new_ids = {o.revision_id for o in (*outcome_set.revisions, *outcome_set.outcomes)}
        if not old_ids.issubset(new_ids):
            raise ValueError("cannot overwrite outcome history without retaining prior revisions")
    _atomic_write(path, content)
    return path


def serialize_outcome_set(outcome_set: EvaluationOutcomeSet) -> str:
    return json.dumps(
        outcome_set.as_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def load_outcome_set(path: Path) -> EvaluationOutcomeSet:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed outcome store: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("malformed outcome store payload")
    version = payload.get("schema_version")
    if version not in (1, OUTCOME_STORE_SCHEMA_VERSION):
        raise ValueError(f"unsupported outcome-store schema: {version}")
    raw_definitions = payload.get("horizon_definitions")
    raw_outcomes = payload.get("outcomes")
    if not isinstance(raw_definitions, list) or not isinstance(raw_outcomes, list):
        raise ValueError("malformed outcome-store collections")
    definitions = tuple(_horizon_from_payload(item) for item in raw_definitions)
    outcomes = tuple(_outcome_from_payload(item) for item in raw_outcomes)
    if version == 2 and (payload.get("return_methodology") != COHERENT_RETURN_METHOD
                         or payload.get("revision_policy") != OUTCOME_REVISION_POLICY):
        raise ValueError("unsupported outcome store methodology or revision policy")
    return EvaluationOutcomeSet(
        schema_version=version,
        evaluation_run_id=_required_string(payload.get("evaluation_run_id"), "run ID"),
        evaluation_schema_version=_required_int(
            payload.get("evaluation_schema_version"), "evaluation schema"
        ),
        report_date=date.fromisoformat(
            _required_string(payload.get("report_date"), "report date")
        ),
        strategy=_required_string(payload.get("strategy"), "strategy"),
        scoring_model_version=_required_string(
            payload.get("scoring_model_version"), "model version"
        ),
        horizon_definitions=definitions,
        outcomes=outcomes,
        revisions=tuple(_outcome_from_payload(item) for item in payload.get("revisions", [])),
    )


def _initial_outcome(
    snapshot: EvaluationSnapshot,
    row: EvaluationCompanyRow,
    horizon: HorizonDefinition,
    provider_name: str,
) -> MarketOutcome:
    market = market_for_country(row.country)
    entry, target_exit = _fixed_sessions(snapshot.decision_at, market, horizon.sessions)
    return MarketOutcome(
        schema_version=OUTCOME_SCHEMA_VERSION,
        evaluation_run_id=snapshot.run_id,
        scoring_model_version=snapshot.scoring_model_version,
        strategy=snapshot.strategy,
        company_id=row.company_id,
        isin=row.isin,
        ticker=row.ticker,
        country=row.country,
        exchange=row.exchange,
        segment=row.segment,
        original_rank=row.rank,
        horizon_label=horizon.label,
        horizon_sessions=horizon.sessions,
        decision_at=snapshot.decision_at,
        market=market,
        entry_policy=ENTRY_POLICY,
        entry_reason=(
            "first eligible market-session close strictly after decision_at"
        ),
        entry_session=entry.day,
        target_exit_session=target_exit.day,
        actual_exit_session=None,
        entry_price=None,
        exit_price=None,
        price_type=ADJUSTED_PRICE_TYPE,
        is_adjusted=True,
        currency=_currency_for_country(row.country),
        raw_forward_return_pct=None,
        net_forward_return_pct=None,
        status="not_due",
        price_provider=provider_name,
        provider_symbol=None,
        retrieved_at=None,
        entry_retrieved_at=None,
        exit_retrieved_at=None,
        entry_revision_policy=ENTRY_REVISION_POLICY,
        return_methodology=COHERENT_RETURN_METHOD,
    )


def analysis_outcome_rows(
    snapshot: EvaluationSnapshot, store: EvaluationOutcomeSet | None, *,
    cutoff: datetime, definitions: tuple[HorizonDefinition, ...] | None = None,
) -> tuple[tuple[HorizonDefinition, ...], tuple[MarketOutcome, ...]]:
    """Fill an unfetched X population with explicit missing views, never persisted Y."""
    definitions = definitions or (store.horizon_definitions if store else DEFAULT_STRATEGY_HORIZONS[snapshot.strategy])
    if store is not None:
        _validate_existing_store(store, snapshot, definitions)
        rows = store.outcomes
    else:
        rows = tuple(_initial_outcome(snapshot, row, definition, "unretrieved")
                     for row in snapshot.rows for definition in definitions)
    return tuple(definitions), tuple(analysis_view(row, cutoff) for row in rows)


def _should_refresh(outcome: MarketOutcome, retrieved_at: datetime, *, reprice: bool = False) -> bool:
    if outcome.status == "priced" and not reprice:
        return False
    return is_mature(outcome, retrieved_at)


def _coherent_base(outcome: MarketOutcome) -> MarketOutcome:
    if outcome.schema_version == 2:
        return outcome
    return replace(
        outcome, schema_version=2, return_methodology=COHERENT_RETURN_METHOD,
        status="not_due", entry_price=None, exit_price=None, actual_exit_session=None,
        entry_retrieved_at=None, exit_retrieved_at=None, retrieved_at=None,
        raw_forward_return_pct=None, detail="legacy adjustment basis unverified; coherent refetch required",
        entry_revision_policy=ENTRY_REVISION_POLICY, prior_revision_id=outcome.revision_id,
        revision_reason="explicit_legacy_reprocessing",
    )


def _derived_outcome(outcome: MarketOutcome, calculation_time: datetime, **changes) -> MarketOutcome:
    # Clear the derived fields together: an unresolved revision must not retain an old return.
    values = dict(
        entry_price=None, exit_price=None, actual_exit_session=None,
        entry_retrieved_at=None, exit_retrieved_at=None, history_evidence=None,
        history_metadata=None,
        raw_forward_return_pct=None, retrieved_at=calculation_time,
        calculated_at=calculation_time, prior_revision_id=outcome.revision_id,
        revision_reason="coherent_history_refresh", return_difference_pct=None,
    )
    values.update(changes)
    new_return = values["raw_forward_return_pct"]
    if new_return is not None and outcome.raw_forward_return_pct is not None:
        values["return_difference_pct"] = new_return - outcome.raw_forward_return_pct
    if values["entry_price"] is not None and outcome.entry_price is not None and (
        values["entry_price"] != outcome.entry_price
        or (values["exit_price"] is not None and outcome.exit_price is not None
            and values["exit_price"] != outcome.exit_price)
    ):
        values["revision_reason"] = "coherent_endpoint_revision"
    return replace(outcome, **values)


def _pending_outcome(outcome: MarketOutcome, calculated_at: datetime, *, deferred_by_budget: bool = True) -> MarketOutcome:
    return _derived_outcome(
        outcome, calculated_at, status="coherent_history_pending",
        detail=BUDGET_DEFERRED_DETAIL if deferred_by_budget else "coherent history pending: awaiting retrieval",
    )


def _outcome_from_history(
    outcome: MarketOutcome, history: HistoricalPriceHistory, retrieved_at: datetime, *,
    batch: PriceHistoryBatch | None = None,
) -> MarketOutcome:
    calculation_time = max(retrieved_at, batch.metadata.completed_at) if batch else retrieved_at
    if (batch is not None and outcome.status == "priced" and outcome.history_evidence is not None
            and outcome.history_evidence.metadata.batch_id == batch.metadata.batch_id):
        return outcome
    if history.status != "ok" or batch is None:
        return _derived_outcome(
            outcome, calculation_time,
            status=history.status if history.status in OUTCOME_STATUSES else "provider_error",
            price_provider=history.provider,
            provider_symbol=outcome.provider_symbol or history.symbol,
            detail=history.detail or "single-response adjustment basis is unverified",
        )
    entry = history.observation_on(outcome.entry_session)
    exit = history.observation_on(outcome.target_exit_session)
    if entry is None:
        return _derived_outcome(outcome, calculation_time, status="missing_entry",
                                history_metadata=batch.metadata, price_provider=history.provider,
                                provider_symbol=history.symbol,
                                detail="no adjusted close exists on the required entry session")
    if exit is None:
        return _derived_outcome(
            outcome, calculation_time, status="missing_exit",
            entry_price=entry.adjusted_close, entry_retrieved_at=entry.retrieved_at,
            price_provider=history.provider, provider_symbol=history.symbol,
            history_metadata=batch.metadata,
            detail="no adjusted close exists on the required exit session; coherent refetch required",
        )
    return _derived_outcome(
        outcome, calculation_time, status="priced",
        entry_price=entry.adjusted_close, exit_price=exit.adjusted_close,
        actual_exit_session=exit.session_date, currency=batch.metadata.currency,
        price_provider=history.provider, provider_symbol=history.symbol,
        entry_retrieved_at=entry.retrieved_at, exit_retrieved_at=exit.retrieved_at,
        raw_forward_return_pct=(exit.adjusted_close / entry.adjusted_close - 1) * 100,
        history_evidence=batch.evidence(outcome.entry_session, outcome.target_exit_session),
        detail=None,
    )


def _security_reference(row: EvaluationCompanyRow) -> SecurityReference:
    return SecurityReference(
        company_id=row.company_id,
        isin=row.isin,
        ticker=row.ticker,
        country=row.country,
        exchange=row.exchange,
        currency=_currency_for_country(row.country),
    )


def _currency_for_country(country: str) -> str | None:
    return {"SE": "SEK", "FI": "EUR"}.get(country.strip().upper())


def _validate_existing_store(
    existing: EvaluationOutcomeSet,
    snapshot: EvaluationSnapshot,
    definitions: tuple[HorizonDefinition, ...],
) -> None:
    if existing.evaluation_run_id != snapshot.run_id:
        raise ValueError("existing outcome store belongs to another evaluation run")
    if existing.strategy != snapshot.strategy:
        raise ValueError("existing outcome store strategy mismatch")
    if existing.scoring_model_version != snapshot.scoring_model_version:
        raise ValueError("existing outcome store model-version mismatch")
    if existing.horizon_definitions != tuple(definitions):
        raise ValueError("existing outcome horizon definitions cannot be changed")
    expected_keys = {
        (row.company_id, definition.label)
        for row in snapshot.rows
        for definition in definitions
    }
    outcomes_by_key = {
        (outcome.company_id, outcome.horizon_label): outcome
        for outcome in existing.outcomes
    }
    if set(outcomes_by_key) != expected_keys:
        raise ValueError("existing outcome store does not cover the evaluation universe")
    rows_by_company = {row.company_id: row for row in snapshot.rows}
    for (company_id, horizon_label), outcome in outcomes_by_key.items():
        row = rows_by_company[company_id]
        definition = next(item for item in definitions if item.label == horizon_label)
        market = market_for_country(row.country)
        entry, target = _fixed_sessions(snapshot.decision_at, market, definition.sessions)
        expected_entry, expected_exit = entry.day, target.day
        immutable_metadata = (
            outcome.isin == row.isin,
            outcome.ticker == row.ticker,
            outcome.country == row.country,
            outcome.exchange == row.exchange,
            outcome.segment == row.segment,
            outcome.original_rank == row.rank,
            outcome.decision_at == snapshot.decision_at,
            outcome.market == market,
            outcome.entry_policy == ENTRY_POLICY,
            outcome.entry_session == expected_entry,
            outcome.target_exit_session == expected_exit,
            outcome.horizon_sessions == definition.sessions,
        )
        if not all(immutable_metadata):
            raise ValueError(
                "existing outcome metadata conflicts with the immutable evaluation"
            )


def _horizon_from_payload(value: Any) -> HorizonDefinition:
    if not isinstance(value, dict) or value.get("unit") != "market_sessions":
        raise ValueError("malformed outcome horizon definition")
    return HorizonDefinition(
        _required_string(value.get("label"), "horizon label"),
        _required_int(value.get("sessions"), "horizon sessions"),
    )


def _outcome_from_payload(value: Any) -> MarketOutcome:
    if not isinstance(value, dict):
        raise ValueError("malformed market-outcome record")
    version = value.get("schema_version")
    if version not in (1, OUTCOME_SCHEMA_VERSION):
        raise ValueError(f"unsupported market-outcome schema: {version}")
    horizon = value.get("horizon")
    definition = _horizon_from_payload(horizon)
    outcome = MarketOutcome(
        schema_version=version,
        evaluation_run_id=_required_string(value.get("evaluation_run_id"), "run ID"),
        scoring_model_version=_required_string(
            value.get("scoring_model_version"), "model version"
        ),
        strategy=_required_string(value.get("strategy"), "strategy"),
        company_id=_required_string(value.get("company_id"), "company ID"),
        isin=_optional_string(value.get("isin")),
        ticker=_required_string(value.get("ticker"), "ticker"),
        country=_required_string(value.get("country"), "country"),
        exchange=_required_string(value.get("exchange"), "exchange"),
        segment=_required_string(value.get("segment"), "segment"),
        original_rank=_required_int(value.get("original_rank"), "rank"),
        horizon_label=definition.label,
        horizon_sessions=definition.sessions,
        decision_at=_parse_timestamp(value.get("decision_at"), "decision_at"),
        market=_required_string(value.get("market"), "market"),
        entry_policy=_required_string(value.get("entry_policy"), "entry policy"),
        entry_reason=_required_string(value.get("entry_reason"), "entry reason"),
        entry_session=date.fromisoformat(
            _required_string(value.get("entry_session"), "entry session")
        ),
        target_exit_session=date.fromisoformat(
            _required_string(value.get("target_exit_session"), "target exit")
        ),
        actual_exit_session=_parse_optional_date(value.get("actual_exit_session")),
        entry_price=_optional_number(value.get("entry_price")),
        exit_price=_optional_number(value.get("exit_price")),
        price_type=_required_string(value.get("price_type"), "price type"),
        is_adjusted=value.get("is_adjusted"),
        currency=_optional_string(value.get("currency")),
        raw_forward_return_pct=_optional_number(value.get("raw_forward_return_pct")),
        net_forward_return_pct=_optional_number(value.get("net_forward_return_pct")),
        status=_required_string(value.get("status"), "status"),
        price_provider=_required_string(value.get("price_provider"), "provider"),
        provider_symbol=_optional_string(value.get("provider_symbol")),
        retrieved_at=_parse_optional_timestamp(value.get("retrieved_at")),
        entry_retrieved_at=_parse_optional_timestamp(value.get("entry_retrieved_at")),
        exit_retrieved_at=_parse_optional_timestamp(value.get("exit_retrieved_at")),
        entry_revision_policy=_required_string(
            value.get("entry_revision_policy"), "entry revision policy"
        ),
        detail=_optional_string(value.get("detail")),
        return_methodology=value.get("return_methodology", LEGACY_RETURN_METHOD),
        calculated_at=_parse_optional_timestamp(value.get("calculated_at")),
        history_evidence=EndpointEvidence.from_payload(value["history_evidence"]) if value.get("history_evidence") else None,
        history_metadata=HistoryMetadata.from_payload(value["history_metadata"]) if value.get("history_metadata") else None,
        prior_revision_id=_optional_string(value.get("prior_revision_id")),
        revision_reason=_optional_string(value.get("revision_reason")),
        return_difference_pct=_optional_number(value.get("return_difference_pct")),
    )
    if version == 2 and value.get("outcome_revision_id") != outcome.revision_id:
        raise ValueError("outcome revision identity mismatch")
    if version == 2 and value.get("history_batch_id") != outcome.as_payload()["history_batch_id"]:
        raise ValueError("outcome history batch identity mismatch")
    return outcome


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


def select_outcome_revisions(
    stores: Iterable[EvaluationOutcomeSet], *, return_methodology: str | None = None,
    data_cutoff: datetime | None = None,
) -> tuple[tuple[EvaluationOutcomeSet, ...], dict[str, Any]]:
    """One shared selection boundary for normal and paired analysis, before any metrics."""
    stores = tuple(stores)
    methods = {store.return_methodology for store in stores}
    if return_methodology is None:
        if len(methods) > 1:
            raise ValueError("mixed return methodologies require an explicit analysis selection")
        return_methodology = next(iter(methods), COHERENT_RETURN_METHOD)
    if return_methodology not in {COHERENT_RETURN_METHOD, LEGACY_RETURN_METHOD}:
        raise ValueError("unknown return methodology")
    if data_cutoff is not None:
        data_cutoff = _utc_timestamp(data_cutoff, "analysis data cutoff")
    selected = []
    for store in stores:
        if store.return_methodology != return_methodology:
            continue
        records = (*store.revisions, *store.outcomes)
        by_key: dict[tuple[str, str, str], list[tuple[int, MarketOutcome]]] = {}
        for index, outcome in enumerate(records):
            if outcome.return_methodology != return_methodology:
                continue
            visible_at = max(value for value in (
                outcome.decision_at, outcome.calculated_at, outcome.retrieved_at,
                outcome.entry_retrieved_at, outcome.exit_retrieved_at,
                outcome.history_evidence.metadata.completed_at if outcome.history_evidence else None,
            ) if value is not None)
            if data_cutoff is None or visible_at <= data_cutoff:
                by_key.setdefault(outcome.key, []).append((index, outcome))
        if not by_key:
            continue
        outcomes = []
        for current in store.outcomes:
            candidates = by_key.get(current.key, [])
            if not candidates:
                # Legacy data has no retained pre-retrieval revision. Do not backdate it.
                raise ValueError("analysis cutoff has incomplete revision metadata for this run")
            _, chosen = max(candidates, key=lambda pair: (
                pair[1].calculated_at or pair[1].retrieved_at or pair[1].decision_at, pair[0],
            ))
            outcomes.append(chosen)
        ids = {outcome.revision_id for outcome in outcomes}
        selected.append(replace(store, outcomes=tuple(outcomes),
                                revisions=tuple(o for o in records if o.revision_id not in ids)))
    if len({store.evaluation_run_id for store in selected}) != len(selected):
        raise ValueError("duplicate outcome set for evaluation run and methodology")
    selection = {
        "return_methodology": return_methodology,
        "outcome_revision_policy": OUTCOME_REVISION_POLICY,
        "analysis_data_cutoff": _format_optional_timestamp(data_cutoff),
        "adjustment_basis_verified": return_methodology == COHERENT_RETURN_METHOD,
        "selected_outcomes_hash": content_hash(sorted(
            (o.key, o.revision_id, o.raw_forward_return_pct)
            for store in selected for o in store.outcomes
        )),
    }
    return tuple(selected), selection


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    raw = _required_string(value, field_name)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _utc_timestamp(parsed, field_name)


def _parse_optional_timestamp(value: Any) -> datetime | None:
    return None if value is None else _parse_timestamp(value, "timestamp")


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else _format_timestamp(value)


def _format_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_optional_date(value: Any) -> date | None:
    return None if value is None else date.fromisoformat(_required_string(value, "date"))


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"malformed outcome {field_name}")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("malformed optional outcome string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"malformed outcome {field_name}")
    return value


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("malformed outcome number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("malformed outcome number")
    return parsed


def _positive_finite(value: float) -> bool:
    return not isinstance(value, bool) and math.isfinite(value) and value > 0


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
