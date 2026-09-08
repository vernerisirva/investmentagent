"""Cutoff-relative lifecycle views; never rewrite recorded outcome evidence."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, Iterable

from investmentagent.market_calendar import (
    MarketSession, advance_market_sessions, first_session_closing_after, market_for_country,
)

if TYPE_CHECKING:
    from investmentagent.evaluation_outcomes import MarketOutcome


OUTCOME_STATUS_METHODOLOGY = "cutoff-maturity-v1"
BUDGET_DEFERRED_DETAIL = "coherent history pending: API-call budget exhausted"


def status_cutoff(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("outcome status cutoff must be timezone-aware")
    return value.astimezone(timezone.utc)


@lru_cache(maxsize=4096)
def fixed_sessions(
    decision_at: datetime, market: str, horizon_sessions: int,
) -> tuple[MarketSession, MarketSession]:
    entry = first_session_closing_after(decision_at, market)
    return entry, advance_market_sessions(entry.day, horizon_sessions, market)


def is_mature(outcome: MarketOutcome, cutoff: datetime) -> bool:
    cutoff = status_cutoff(cutoff)
    market = market_for_country(outcome.country)
    entry, target = fixed_sessions(outcome.decision_at, market, outcome.horizon_sessions)
    if (outcome.market, outcome.entry_session, outcome.target_exit_session) != (market, entry.day, target.day):
        raise ValueError("outcome maturity sessions conflict with decision-time information")
    return target.closes_at <= cutoff


def evidence_visible_at(outcome: MarketOutcome) -> datetime:
    return max(value for value in (
        outcome.decision_at, outcome.calculated_at, outcome.retrieved_at,
        outcome.entry_retrieved_at, outcome.exit_retrieved_at,
        outcome.history_metadata.completed_at if outcome.history_metadata else None,
        outcome.history_evidence.metadata.completed_at if outcome.history_evidence else None,
    ) if value is not None)


def status_as_of(outcome: MarketOutcome, cutoff: datetime) -> str:
    if not is_mature(outcome, cutoff):
        return "not_due"
    if evidence_visible_at(outcome) > cutoff or outcome.status == "not_due":
        return "coherent_history_pending"
    return outcome.status


def analysis_view(outcome: MarketOutcome, cutoff: datetime) -> MarketOutcome:
    """An ephemeral metric input, never an outcome-store revision or price observation."""
    status = status_as_of(outcome, cutoff)
    if (status == outcome.status and evidence_visible_at(outcome) <= cutoff
            and (status == "priced" or outcome.raw_forward_return_pct is None)):
        return outcome
    return replace(
        outcome, status=status, entry_price=None, exit_price=None, actual_exit_session=None,
        raw_forward_return_pct=None, net_forward_return_pct=None, provider_symbol=None,
        retrieved_at=None, entry_retrieved_at=None, exit_retrieved_at=None,
        calculated_at=None, history_metadata=None, history_evidence=None,
        prior_revision_id=None, revision_reason=None, return_difference_pct=None,
        detail="derived status at analysis cutoff; coherent price evidence not available",
    )


def lifecycle_counts(outcomes: Iterable[MarketOutcome], cutoff: datetime) -> dict:
    outcomes = tuple(outcomes)
    statuses = Counter(status_as_of(outcome, cutoff) for outcome in outcomes)
    pending = statuses["coherent_history_pending"]
    deferred = sum(
        status_as_of(outcome, cutoff) == "coherent_history_pending"
        and evidence_visible_at(outcome) <= cutoff and outcome.detail == BUDGET_DEFERRED_DETAIL
        for outcome in outcomes
    )
    return {
        "outcome_status_methodology": OUTCOME_STATUS_METHODOLOGY,
        "status_cutoff": status_cutoff(cutoff).isoformat().replace("+00:00", "Z"),
        "total": len(outcomes),
        "not_mature": statuses["not_due"],
        "mature": len(outcomes) - statuses["not_due"],
        "mature_priced": statuses["priced"],
        "mature_pending": pending,
        "mature_budget_deferred": deferred,
        "mature_awaiting_retrieval": pending - deferred,
        "mature_failed": statuses["provider_error"],
        "mature_unavailable": sum(statuses[name] for name in (
            "missing_entry", "missing_exit", "symbol_unresolved", "corporate_action_unsupported",
        )),
        "status_counts": dict(sorted(statuses.items())),
    }
