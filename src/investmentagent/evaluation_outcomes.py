from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from investmentagent.evaluation import EvaluationCompanyRow, EvaluationSnapshot, load_evaluation_snapshot
from investmentagent.market_calendar import (
    advance_market_sessions,
    first_session_closing_after,
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


OUTCOME_SCHEMA_VERSION = 1
OUTCOME_STORE_SCHEMA_VERSION = 1
DEFAULT_MAX_PRICE_API_CALLS = 20
OUTCOME_STATUSES = {
    "not_due",
    "priced",
    "missing_entry",
    "missing_exit",
    "symbol_unresolved",
    "provider_error",
    "corporate_action_unsupported",
}
ENTRY_POLICY = "first_market_session_adjusted_close_after_decision"
ENTRY_REVISION_POLICY = (
    "freeze established entry; flag provider revisions instead of silently replacing it"
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

    def __post_init__(self) -> None:
        if self.schema_version != OUTCOME_SCHEMA_VERSION:
            raise ValueError(f"unsupported market-outcome schema: {self.schema_version}")
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"unsupported market-outcome status: {self.status}")
        if self.strategy not in DEFAULT_STRATEGY_HORIZONS:
            raise ValueError("outcome strategy must be trading or long-term")
        if self.price_type != ADJUSTED_PRICE_TYPE or self.is_adjusted is not True:
            raise ValueError("Performance v2 outcomes require adjusted-close prices")
        if self.decision_at.tzinfo is None:
            raise ValueError("outcome decision timestamp must be timezone-aware")
        object.__setattr__(self, "decision_at", self.decision_at.astimezone(timezone.utc))
        for field_name in ("retrieved_at", "entry_retrieved_at", "exit_retrieved_at"):
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

    @property
    def key(self) -> tuple[str, str, str]:
        return self.evaluation_run_id, self.company_id, self.horizon_label

    def as_payload(self) -> dict[str, Any]:
        return {
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

    def __post_init__(self) -> None:
        if self.schema_version != OUTCOME_STORE_SCHEMA_VERSION:
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

    def as_payload(self) -> dict[str, Any]:
        return {
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
) -> EvaluationOutcomeSet:
    retrieval_time = _utc_timestamp(retrieved_at, "retrieved_at")
    prepared = _prepare_evaluation_outcomes(
        snapshot,
        provider_name=provider.name,
        retrieved_at=retrieval_time,
        existing=existing,
        horizons=horizons,
    )
    outcomes: list[MarketOutcome] = []
    for company in prepared.companies:
        history: HistoricalPriceHistory | None = None
        if company.refreshable:
            known_symbols = {
                outcome.provider_symbol
                for outcome in company.refreshable
                if outcome.entry_price is not None and outcome.provider_symbol is not None
            }
            if len(known_symbols) > 1:
                raise ValueError("established entries disagree on provider symbol")
            start_date = min(
                outcome.entry_session for outcome in company.refreshable
            )
            end_date = max(
                outcome.target_exit_session for outcome in company.refreshable
            )
            market = company.refreshable[0].market
            history = provider.get_history(
                _security_reference(company.row),
                start_date=start_date,
                end_date=end_date,
                market=market,
                retrieved_at=retrieval_time,
                symbol=next(iter(known_symbols), None),
            )
        for outcome in company.outcomes:
            if history is not None and outcome in company.refreshable:
                outcomes.append(_outcome_from_history(outcome, history, retrieval_time))
            else:
                outcomes.append(outcome)
    return _build_outcome_set(prepared, outcomes)


def refresh_outcome_store(
    evaluation_root: Path,
    outcome_root: Path,
    provider: HistoricalPriceProvider,
    *,
    retrieved_at: datetime,
    strategy: str | None = None,
    run_id: str | None = None,
    report_date: date | None = None,
    price_cache: HistoricalPriceCache | None = None,
    max_price_api_calls: int | None = None,
) -> OutcomeRefreshSummary:
    if max_price_api_calls is not None and (
        isinstance(max_price_api_calls, bool) or max_price_api_calls < 0
    ):
        raise ValueError("maximum price API calls must be at least zero")
    snapshots = discover_evaluation_snapshots(
        evaluation_root,
        strategy=strategy,
        run_id=run_id,
        report_date=report_date,
    )
    if price_cache is not None:
        if max_price_api_calls is None:
            raise ValueError("cached outcome refresh requires an explicit API budget")
        return _refresh_outcome_store_with_cache(
            snapshots,
            outcome_root,
            provider,
            price_cache,
            retrieved_at=_utc_timestamp(retrieved_at, "retrieved_at"),
            max_price_api_calls=max_price_api_calls,
        )

    calls_before = _provider_api_call_count(provider)
    files: list[Path] = []
    all_outcomes: list[MarketOutcome] = []
    for snapshot in snapshots:
        path = outcome_store_path(outcome_root, snapshot)
        existing = load_outcome_set(path) if path.exists() else None
        refreshed = refresh_evaluation_outcomes(
            snapshot,
            provider,
            retrieved_at=retrieved_at,
            existing=existing,
        )
        save_outcome_set(path, refreshed)
        files.append(path)
        all_outcomes.extend(refreshed.outcomes)
    unresolved_statuses = OUTCOME_STATUSES - {"priced", "not_due"}
    return OutcomeRefreshSummary(
        evaluation_runs=len(snapshots),
        outcome_records=len(all_outcomes),
        priced=sum(outcome.status == "priced" for outcome in all_outcomes),
        not_due=sum(outcome.status == "not_due" for outcome in all_outcomes),
        unresolved=sum(outcome.status in unresolved_statuses for outcome in all_outcomes),
        files_written=tuple(files),
        provider_calls_executed=(
            _provider_api_call_count(provider) - calls_before
        ),
    )


def _refresh_outcome_store_with_cache(
    snapshots: tuple[EvaluationSnapshot, ...],
    outcome_root: Path,
    provider: HistoricalPriceProvider,
    price_cache: HistoricalPriceCache,
    *,
    retrieved_at: datetime,
    max_price_api_calls: int,
) -> OutcomeRefreshSummary:
    prepared_runs: list[_PreparedEvaluationOutcomes] = []
    requirements: dict[tuple[str, str], _SecurityRequirement] = {}
    for snapshot in snapshots:
        path = outcome_store_path(outcome_root, snapshot)
        existing = load_outcome_set(path) if path.exists() else None
        prepared = _prepare_evaluation_outcomes(
            snapshot,
            provider_name=provider.name,
            retrieved_at=retrieved_at,
            existing=existing,
            horizons=None,
        )
        prepared_runs.append(prepared)
        for company in prepared.companies:
            if not company.refreshable:
                continue
            market = company.refreshable[0].market
            key = (company.row.company_id, market)
            known_symbols = {
                outcome.provider_symbol
                for outcome in company.refreshable
                if outcome.entry_price is not None
                and outcome.provider_symbol is not None
            }
            start_date = min(
                outcome.entry_session for outcome in company.refreshable
            )
            end_date = max(
                outcome.target_exit_session for outcome in company.refreshable
            )
            required_dates = {
                session
                for outcome in company.refreshable
                for session in (outcome.entry_session, outcome.target_exit_session)
            }
            has_unestablished_entry = any(
                outcome.entry_price is None for outcome in company.refreshable
            )
            shortest_horizon = min(
                outcome.horizon_sessions for outcome in company.refreshable
            )
            requirement = requirements.get(key)
            if requirement is None:
                requirements[key] = _SecurityRequirement(
                    security=_security_reference(company.row),
                    market=market,
                    required_dates=set(required_dates),
                    range_start=start_date,
                    range_end=end_date,
                    known_symbols=set(known_symbols),
                    has_unestablished_entry=has_unestablished_entry,
                    shortest_due_horizon_sessions=shortest_horizon,
                    oldest_evaluation_date=prepared.snapshot.report_date,
                )
                continue
            if (
                requirement.security.country != company.row.country
                or requirement.security.isin != company.row.isin
            ):
                raise ValueError(
                    "stable company identity maps to conflicting securities"
                )
            requirement.required_dates.update(required_dates)
            requirement.range_start = min(requirement.range_start, start_date)
            requirement.range_end = max(requirement.range_end, end_date)
            requirement.known_symbols.update(known_symbols)
            requirement.has_unestablished_entry = (
                requirement.has_unestablished_entry or has_unestablished_entry
            )
            requirement.shortest_due_horizon_sessions = min(
                requirement.shortest_due_horizon_sessions,
                shortest_horizon,
            )
            requirement.oldest_evaluation_date = min(
                requirement.oldest_evaluation_date,
                prepared.snapshot.report_date,
            )

    cache_hits = 0
    cache_misses = 0
    tasks_with_keys: list[tuple[tuple[str, str], PriceFetchPlanItem]] = []
    preferred_symbols: dict[tuple[str, str], str | None] = {}
    for key, requirement in requirements.items():
        if len(requirement.known_symbols) > 1:
            raise ValueError("established entries disagree on provider symbol")
        preferred_symbol = next(iter(requirement.known_symbols), None)
        if preferred_symbol is None:
            preferred_symbol = price_cache.preferred_symbol(
                requirement.security.company_id,
                provider=provider.name,
                market=requirement.market,
            )
        preferred_symbols[key] = preferred_symbol
        missing_dates = []
        for session_date in sorted(requirement.required_dates):
            observation = price_cache.get_observation(
                requirement.security.company_id,
                provider=provider.name,
                market=requirement.market,
                session_date=session_date,
                symbol=preferred_symbol,
            )
            if observation is None:
                cache_misses += 1
                missing_dates.append(session_date)
            else:
                cache_hits += 1
        if not missing_dates:
            continue
        estimated_calls = _estimated_provider_api_calls(
            provider,
            requirement.security,
            symbol=preferred_symbol,
        )
        tasks_with_keys.append(
            (
                key,
                PriceFetchPlanItem(
                    company_id=requirement.security.company_id,
                    ticker=requirement.security.ticker,
                    country=requirement.security.country,
                    market=requirement.market,
                    provider_symbol=preferred_symbol,
                    start_date=min(missing_dates),
                    end_date=max(missing_dates),
                    missing_session_dates=tuple(missing_dates),
                    estimated_api_calls=estimated_calls,
                    has_unestablished_entry=requirement.has_unestablished_entry,
                    shortest_due_horizon_sessions=(
                        requirement.shortest_due_horizon_sessions
                    ),
                    oldest_evaluation_date=requirement.oldest_evaluation_date,
                ),
            )
        )

    ordered_tasks = sorted(
        tasks_with_keys,
        key=lambda item: (
            not item[1].has_unestablished_entry,
            item[1].shortest_due_horizon_sessions,
            item[1].end_date,
            item[1].oldest_evaluation_date,
            item[1].company_id,
            item[1].market,
        ),
    )
    planned_calls = 0
    selected: list[tuple[tuple[str, str], PriceFetchPlanItem]] = []
    deferred: list[tuple[tuple[str, str], PriceFetchPlanItem]] = []
    final_plan: list[tuple[tuple[str, str], PriceFetchPlanItem]] = []
    for key, task in ordered_tasks:
        if planned_calls + task.estimated_api_calls <= max_price_api_calls:
            planned_calls += task.estimated_api_calls
            selected.append((key, task))
            final_plan.append((key, task))
        else:
            deferred_task = replace(task, deferred_by_budget=True)
            deferred.append((key, deferred_task))
            final_plan.append((key, deferred_task))

    calls_before = _provider_api_call_count(provider)
    fetched_histories: dict[tuple[str, str], HistoricalPriceHistory] = {}
    observations_stored = 0
    provider_errors = 0
    unresolved_symbols = 0
    revisions_detected = 0
    for key, task in selected:
        requirement = requirements[key]
        history = provider.get_history(
            requirement.security,
            start_date=task.start_date,
            end_date=task.end_date,
            market=requirement.market,
            retrieved_at=retrieved_at,
            symbol=task.provider_symbol,
        )
        fetched_histories[key] = history
        if history.status == "ok":
            stored = price_cache.store(
                requirement.security.company_id,
                history.observations,
            )
            observations_stored += stored.observations_stored
            revisions_detected += stored.revisions_detected
        elif history.status == "provider_error":
            provider_errors += 1
        elif history.status == "symbol_unresolved":
            unresolved_symbols += 1
    calls_executed = _provider_api_call_count(provider) - calls_before
    if calls_executed > max_price_api_calls:
        raise RuntimeError("historical-price provider exceeded the API-call budget")

    files: list[Path] = []
    all_outcomes: list[MarketOutcome] = []
    for prepared in prepared_runs:
        outcomes: list[MarketOutcome] = []
        for company in prepared.companies:
            history: HistoricalPriceHistory | None = None
            if company.refreshable:
                market = company.refreshable[0].market
                key = (company.row.company_id, market)
                requirement = requirements[key]
                fetched = fetched_histories.get(key)
                symbol = preferred_symbols[key]
                if fetched is not None and fetched.symbol is not None:
                    symbol = fetched.symbol
                revision_dates = tuple(
                    value
                    for value in price_cache.revision_dates(
                        company.row.company_id,
                        provider=provider.name,
                        market=market,
                        start_date=requirement.range_start,
                        end_date=requirement.range_end,
                        symbol=symbol,
                    )
                    if value in requirement.required_dates
                )
                cached_rows = price_cache.get_range(
                    company.row.company_id,
                    provider=provider.name,
                    market=market,
                    start_date=requirement.range_start,
                    end_date=requirement.range_end,
                    symbol=symbol,
                )
                if revision_dates:
                    history = HistoricalPriceHistory(
                        "corporate_action_unsupported",
                        provider.name,
                        symbol,
                        market,
                        detail=(
                            "provider revised cached adjusted-close observation(s) on "
                            + ", ".join(day.isoformat() for day in revision_dates)
                            + "; accepted cache values and established entries were preserved"
                        ),
                    )
                elif (
                    fetched is not None
                    and fetched.status == "corporate_action_unsupported"
                ):
                    history = fetched
                elif cached_rows:
                    history = HistoricalPriceHistory(
                        "ok",
                        provider.name,
                        symbol or cached_rows[0].symbol,
                        market,
                        cached_rows,
                    )
                elif fetched is not None:
                    history = fetched
            for outcome in company.outcomes:
                if history is not None and outcome in company.refreshable:
                    outcomes.append(
                        _outcome_from_history(outcome, history, retrieved_at)
                    )
                else:
                    outcomes.append(outcome)
        refreshed = _build_outcome_set(prepared, outcomes)
        path = outcome_store_path(outcome_root, prepared.snapshot)
        save_outcome_set(path, refreshed)
        files.append(path)
        all_outcomes.extend(refreshed.outcomes)

    unresolved_statuses = OUTCOME_STATUSES - {"priced", "not_due"}
    oldest_unresolved = _oldest_unresolved_evaluation_date(
        prepared_runs,
        all_outcomes,
        retrieved_at=retrieved_at,
    )
    return OutcomeRefreshSummary(
        evaluation_runs=len(snapshots),
        outcome_records=len(all_outcomes),
        priced=sum(outcome.status == "priced" for outcome in all_outcomes),
        not_due=sum(outcome.status == "not_due" for outcome in all_outcomes),
        unresolved=sum(
            outcome.status in unresolved_statuses for outcome in all_outcomes
        ),
        files_written=tuple(files),
        securities_requiring_prices=len(requirements),
        required_session_observations=sum(
            len(requirement.required_dates) for requirement in requirements.values()
        ),
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        provider_calls_planned=planned_calls,
        provider_calls_executed=calls_executed,
        api_budget=max_price_api_calls,
        work_deferred_by_budget=len(deferred),
        deferred_api_calls=sum(task.estimated_api_calls for _, task in deferred),
        observations_stored=observations_stored,
        provider_errors=provider_errors,
        unresolved_symbols=unresolved_symbols,
        revisions_detected=revisions_detected,
        oldest_unresolved_evaluation_date=oldest_unresolved,
        deferred_security_ids=tuple(task.company_id for _, task in deferred),
        fetch_plan=tuple(task for _, task in final_plan),
        cache_coverage=price_cache.coverage().as_dict(),
    )


def _prepare_evaluation_outcomes(
    snapshot: EvaluationSnapshot,
    *,
    provider_name: str,
    retrieved_at: datetime,
    existing: EvaluationOutcomeSet | None,
    horizons: tuple[HorizonDefinition, ...] | None,
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
            existing_by_key.get((row.company_id, horizon.label))
            or _initial_outcome(snapshot, row, horizon, provider_name)
            for horizon in definitions
        )
        companies.append(
            _PreparedCompanyOutcomes(
                row=row,
                outcomes=outcomes,
                refreshable=tuple(
                    outcome
                    for outcome in outcomes
                    if _should_refresh(outcome, retrieved_at)
                ),
            )
        )
    return _PreparedEvaluationOutcomes(
        snapshot=snapshot,
        definitions=tuple(definitions),
        companies=tuple(companies),
    )


def _build_outcome_set(
    prepared: _PreparedEvaluationOutcomes,
    outcomes: Iterable[MarketOutcome],
) -> EvaluationOutcomeSet:
    snapshot = prepared.snapshot
    return EvaluationOutcomeSet(
        schema_version=OUTCOME_STORE_SCHEMA_VERSION,
        evaluation_run_id=snapshot.run_id,
        evaluation_schema_version=snapshot.schema_version,
        report_date=snapshot.report_date,
        strategy=snapshot.strategy,
        scoring_model_version=snapshot.scoring_model_version,
        horizon_definitions=prepared.definitions,
        outcomes=tuple(outcomes),
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
    run_ids = [store.evaluation_run_id for store in stores]
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
    if version != OUTCOME_STORE_SCHEMA_VERSION:
        raise ValueError(f"unsupported outcome-store schema: {version}")
    raw_definitions = payload.get("horizon_definitions")
    raw_outcomes = payload.get("outcomes")
    if not isinstance(raw_definitions, list) or not isinstance(raw_outcomes, list):
        raise ValueError("malformed outcome-store collections")
    definitions = tuple(_horizon_from_payload(item) for item in raw_definitions)
    outcomes = tuple(_outcome_from_payload(item) for item in raw_outcomes)
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
    )


def _initial_outcome(
    snapshot: EvaluationSnapshot,
    row: EvaluationCompanyRow,
    horizon: HorizonDefinition,
    provider_name: str,
) -> MarketOutcome:
    market = market_for_country(row.country)
    entry = first_session_closing_after(snapshot.decision_at, market)
    target_exit = advance_market_sessions(entry.day, horizon.sessions, market)
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
    )


def _should_refresh(outcome: MarketOutcome, retrieved_at: datetime) -> bool:
    if outcome.status in {"priced", "corporate_action_unsupported"}:
        return False
    target_session = market_session(outcome.target_exit_session, outcome.market)
    if target_session is None:
        raise ValueError("stored target exit is not a valid market session")
    return target_session.closes_at <= retrieved_at


def _outcome_from_history(
    outcome: MarketOutcome,
    history: HistoricalPriceHistory,
    retrieved_at: datetime,
) -> MarketOutcome:
    if history.status != "ok":
        status = history.status
        if status not in OUTCOME_STATUSES:
            status = "provider_error"
        return replace(
            outcome,
            status=status,
            price_provider=history.provider,
            provider_symbol=outcome.provider_symbol or history.symbol,
            retrieved_at=retrieved_at,
            detail=history.detail,
        )
    entry_observation = history.observation_on(outcome.entry_session)
    exit_observation = history.observation_on(outcome.target_exit_session)
    if entry_observation is None:
        return replace(
            outcome,
            status="missing_entry",
            price_provider=history.provider,
            provider_symbol=history.symbol,
            retrieved_at=retrieved_at,
            detail="no adjusted close exists on the required entry session",
        )
    revision = _entry_revision_detail(outcome, entry_observation)
    if revision is not None:
        return replace(
            outcome,
            status="corporate_action_unsupported",
            price_provider=history.provider,
            provider_symbol=outcome.provider_symbol or history.symbol,
            retrieved_at=retrieved_at,
            detail=revision,
        )
    entry_price = outcome.entry_price or entry_observation.adjusted_close
    entry_retrieved_at = outcome.entry_retrieved_at or entry_observation.retrieved_at
    currency = outcome.currency or entry_observation.currency
    if exit_observation is None:
        return replace(
            outcome,
            status="missing_exit",
            entry_price=entry_price,
            currency=currency,
            price_provider=history.provider,
            provider_symbol=history.symbol,
            retrieved_at=retrieved_at,
            entry_retrieved_at=entry_retrieved_at,
            detail="no adjusted close exists on the required exit session",
        )
    if (
        currency is not None
        and exit_observation.currency is not None
        and currency != exit_observation.currency
    ):
        return replace(
            outcome,
            status="provider_error",
            entry_price=entry_price,
            currency=currency,
            price_provider=history.provider,
            provider_symbol=history.symbol,
            retrieved_at=retrieved_at,
            entry_retrieved_at=entry_retrieved_at,
            detail="entry and exit observations use different currencies",
        )
    forward_return = ((exit_observation.adjusted_close / entry_price) - 1.0) * 100.0
    return replace(
        outcome,
        actual_exit_session=exit_observation.session_date,
        entry_price=entry_price,
        exit_price=exit_observation.adjusted_close,
        currency=currency or exit_observation.currency,
        raw_forward_return_pct=forward_return,
        status="priced",
        price_provider=history.provider,
        provider_symbol=history.symbol,
        retrieved_at=retrieved_at,
        entry_retrieved_at=entry_retrieved_at,
        exit_retrieved_at=exit_observation.retrieved_at,
        detail=None,
    )


def _entry_revision_detail(
    outcome: MarketOutcome, observation: HistoricalPriceObservation
) -> str | None:
    if outcome.entry_price is None:
        return None
    if math.isclose(
        outcome.entry_price,
        observation.adjusted_close,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        return None
    return (
        "provider revised the established adjusted entry price from "
        f"{outcome.entry_price:.12g} to {observation.adjusted_close:.12g}; "
        "the frozen entry was preserved and this outcome was excluded"
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
        expected_entry = first_session_closing_after(snapshot.decision_at, market).day
        expected_exit = advance_market_sessions(
            expected_entry, definition.sessions, market
        ).day
        immutable_metadata = (
            outcome.isin == row.isin,
            outcome.ticker == row.ticker,
            outcome.country == row.country,
            outcome.exchange == row.exchange,
            outcome.segment == row.segment,
            outcome.original_rank == row.rank,
            outcome.decision_at == snapshot.decision_at,
            outcome.market == market,
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
    if version != OUTCOME_SCHEMA_VERSION:
        raise ValueError(f"unsupported market-outcome schema: {version}")
    horizon = value.get("horizon")
    definition = _horizon_from_payload(horizon)
    return MarketOutcome(
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
