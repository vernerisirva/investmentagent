"""X-only benchmark plans. No prices, provider clients, or wall-clock reconstruction."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from investmentagent.decision_membership import recorded_public_portfolio
from investmentagent.evaluation import EvaluationCompanyRow, EvaluationSnapshot, _atomic_write, serialize_evaluation_snapshot
from investmentagent.experiments import ChallengerExperimentSnapshot
from investmentagent.fundamentals_cache import company_cache_identity
from investmentagent.reports import WatchlistBuildResult
from investmentagent import selection


BENCHMARK_METHODOLOGY = "representative-benchmarks-v1"
PLAN_SCHEMA_VERSION = 1
RANDOM_METHOD = "constraint-matched-random-v1"
RANDOM_DRAWS = 1000
MIN_ALTERNATIVES = 5
EXTERNAL_STATUS = "deferred_pending_license"
HIERARCHY = {
    "primary": RANDOM_METHOD,
    "secondary": ["gate-qualified-ew-v1", "opportunity-universe-ew-v1",
                  "exposure-matched-opportunity-v1", "matched-peers-v1"],
    "external_passive_benchmark": {"status": EXTERNAL_STATUS},
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def x_hash(snapshot: EvaluationSnapshot) -> str:
    return hashlib.sha256(serialize_evaluation_snapshot(snapshot).encode()).hexdigest()


def random_seed(run_id: str) -> str:
    return canonical_hash([BENCHMARK_METHODOLOGY, RANDOM_METHOD, run_id])


def _tier(row: EvaluationCompanyRow) -> int:
    return selection.gate_order(row.long_term["gate_tier"]) if row.long_term else 0


def random_portfolios(
    rows: Iterable[EvaluationCompanyRow], policy: selection.SelectionPolicy, seed: str,
) -> tuple[tuple[str, ...], ...]:
    """SHA-256 pseudo-ranks replace score only; production gate priorities remain."""
    rows = tuple(sorted((row for row in rows if row.eligible_universe_member),
                        key=lambda row: row.company_id))
    tiers = {row.company_id: _tier(row) for row in rows}
    draws = []
    for draw in range(RANDOM_DRAWS):
        ranks = {row.company_id: hashlib.sha256(
            f"{seed}:{draw}:{row.company_id}".encode()).digest() for row in rows}
        _, selected = selection.rank_and_select(
            rows, policy=policy,
            rank_key=lambda row: (tiers[row.company_id], ranks[row.company_id], row.ticker),
            identity=lambda row: (row.ticker, row.country), country=lambda row: row.country,
        )
        draws.append(tuple(sorted(row.company_id for row in selected)))
    return tuple(draws)


def _exposure(row: EvaluationCompanyRow) -> dict[str, str | None]:
    return {"country": row.country, "venue": row.segment if row.segment in
            ("main_market", "first_north") else None, "size": row.nasdaq_size_segment}


def matched_pool(
    target: EvaluationCompanyRow, alternatives: Iterable[EvaluationCompanyRow],
) -> dict[str, Any]:
    attributes = _exposure(target)
    alternatives = tuple(alternatives)
    levels = [("country", "venue", "size"), ("country", "venue"), ("country",)]
    attempts = []
    for level in levels:
        if any(attributes[key] is None or not attributes[key] for key in level):
            attempts.append({"level": list(level), "reason": "decision-time field missing"})
            continue
        stratum = {key: attributes[key] for key in level}
        members = sorted(row.company_id for row in alternatives
                         if all(_exposure(row)[key] == value for key, value in stratum.items()))
        if len(members) >= MIN_ALTERNATIVES:
            return {"status": "available", "stratum": stratum, "member_ids": members,
                    "fallback_attempts": attempts}
        attempts.append({"level": list(level), "reason": "insufficient alternatives", "count": len(members)})
    return {"status": "unavailable", "stratum": None, "member_ids": [], "fallback_attempts": attempts}


def portfolio_plan(snapshot: EvaluationSnapshot, ids: Iterable[str] | None) -> dict[str, Any]:
    if ids is None:
        return {"status": "unverified", "reason": "decision-time selection evidence unavailable"}
    ids = tuple(sorted(ids))
    by_id = {row.company_id: row for row in snapshot.rows}
    if len(ids) != len(set(ids)) or not set(ids) <= set(by_id):
        raise ValueError("invalid benchmark portfolio membership")
    selected = tuple(by_id[key] for key in ids)
    alternatives = tuple(row for row in snapshot.rows if row.company_id not in ids)
    peers = {row.company_id: matched_pool(row, alternatives) for row in selected}
    groups: dict[str, dict[str, Any]] = {}
    for row in selected:
        pool = peers[row.company_id]
        key = canonical_hash(pool)
        if key not in groups:
            groups[key] = {**pool, "selected_member_ids": []}
        groups[key]["selected_member_ids"].append(row.company_id)
    strata = []
    for key, group in sorted(groups.items()):
        group["selected_member_ids"].sort()
        strata.append({"stratum_id": key, **group,
                       "weight": len(group["selected_member_ids"]) / len(ids)})
    return {
        "status": "recorded", "member_ids": list(ids),
        "country_counts": dict(sorted(Counter(row.country for row in selected).items())),
        "exposures": {row.company_id: _exposure(row) for row in selected},
        "excluded_from_alternatives": list(ids), "exposure_strata": strata, "peers": peers,
    }


@dataclass(frozen=True)
class BenchmarkPlan:
    payload: dict[str, Any]
    draws: tuple[tuple[str, ...], ...]


def _validate_selection(snapshot: EvaluationSnapshot, evidence: dict[str, Any]) -> selection.SelectionPolicy:
    policy = selection.SelectionPolicy.from_payload(evidence["policy"])
    by_id = {row.company_id: row for row in snapshot.rows if row.eligible_universe_member}
    input_ids = evidence["input_order"]
    if (len(input_ids) != len(set(input_ids)) or set(input_ids) != set(by_id)
            or len({(row.ticker, row.country) for row in by_id.values()}) != len(by_id)):
        raise ValueError("ambiguous or incomplete decision-time selection identity")
    if (policy.limit != snapshot.configuration.get("public_limit")
            or dict(policy.minimum_country_counts) != snapshot.configuration.get("minimum_country_counts")
            or snapshot.diagnostics.get("public_selection_size") != min(policy.limit, len(by_id))):
        raise ValueError("benchmark selection configuration differs from X")
    ordered, selected = selection.rank_and_select(
        (by_id[key] for key in input_ids), policy=policy,
        rank_key=lambda row: (_tier(row), -row.score["total"], row.ticker),
        identity=lambda row: (row.ticker, row.country), country=lambda row: row.country,
    )
    if ([row.company_id for row in ordered] != [row.company_id for row in snapshot.rows]
            or evidence["champion_ids"] != [row.company_id for row in selected]):
        raise ValueError("benchmark selection does not reproduce immutable champion")
    return policy


def _experiment_evidence(snapshot: EvaluationSnapshot, experiment: ChallengerExperimentSnapshot | None):
    if experiment is None or experiment.schema_version != 2:
        return None, None
    from investmentagent.challenger_analysis import _validate_experiment
    _validate_experiment(snapshot, experiment)
    evidence = {
        "policy": experiment.selection_configuration,
        "input_order": [row.company_id for row in sorted(experiment.rows, key=lambda row: row.selection_input_order)],
        "champion_ids": [row.company_id for row in experiment.rows if row.champion_selected],
    }
    challenger_ids = [row.company_id for row in experiment.rows if row.challenger_selected]
    return evidence, challenger_ids


def build_benchmark_plan(
    snapshot: EvaluationSnapshot, *, result: WatchlistBuildResult | None = None,
    experiment: ChallengerExperimentSnapshot | None = None,
    production_context: dict[str, str] | None = None,
) -> BenchmarkPlan:
    """Only the watchlist producer supplies result; reconstruction is retrospective."""
    evidence, challenger_ids = _experiment_evidence(snapshot, experiment)
    provenance = "retrospective"
    if result is not None:
        if result.selection_policy is None:
            raise ValueError("new benchmark plan requires production selection evidence")
        produced = {
            "policy": result.selection_policy.as_payload(),
            "input_order": [company_cache_identity(item.research.company) for item in result.selection_candidates],
            "champion_ids": [company_cache_identity(item.research.company) for item in result.selected_items],
        }
        if evidence is not None and evidence != produced:
            raise ValueError("benchmark champion/challenger selection evidence differs")
        evidence = produced
        provenance = ("prospective" if production_context else "prospective_unscheduled"
                      ) if snapshot.configuration.get("provider") == "live" else "fixture"
    return _construct_plan(snapshot, evidence=evidence, challenger_ids=challenger_ids,
                           experiment=experiment if challenger_ids is not None else None,
                           provenance=provenance, production_context=production_context)


def _construct_plan(snapshot, *, evidence, challenger_ids, experiment, provenance,
                    production_context=None) -> BenchmarkPlan:
    if production_context is not None:
        if (provenance != "prospective" or set(production_context) != {"event", "run_id", "repository", "workflow_sha"}
                or production_context["event"] != "schedule"
                or production_context["repository"] != "vernerisirva/investmentagent"
                or not re.fullmatch(r"[0-9]+", production_context["run_id"])
                or not re.fullmatch(r"[0-9a-f]{40}", production_context["workflow_sha"])):
            raise ValueError("invalid natural production benchmark context")
    elif provenance == "prospective":
        raise ValueError("prospective frozen evidence requires natural production context")
    if any(not row.eligible_universe_member for row in snapshot.rows):
        raise ValueError("Performance v2 X must contain eligible decision-time members")
    policy = _validate_selection(snapshot, evidence) if evidence is not None else None
    public = recorded_public_portfolio(snapshot, {})
    champion_ids = (evidence["champion_ids"] if evidence is not None else
                    public.get("member_ids") if public["membership_status"] == "recorded" else None)
    seed = random_seed(snapshot.run_id)
    draws = random_portfolios(snapshot.rows, policy, seed) if policy is not None else ()
    ids = sorted(row.company_id for row in snapshot.rows)
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION, "benchmark_methodology": BENCHMARK_METHODOLOGY,
        "evaluation_run_id": snapshot.run_id, "decision_at": snapshot.header_payload()["decision_at"],
        "x_sha256": x_hash(snapshot), "provenance": provenance, "hierarchy": HIERARCHY,
        "production_context": production_context,
        "opportunity_member_ids": ids, "gate_qualified_member_ids": ids,
        "gate_boundary": "X is post-hard-eligibility; long-term gate tiers are priorities, not exclusions",
        "selection_evidence": evidence,
        "challenger_identity": ({"experiment_run_id": experiment.experiment_run_id,
                                 "sha256": canonical_hash(experiment.as_payload())} if experiment else None),
        "portfolios": {"champion": portfolio_plan(snapshot, champion_ids),
                       "challenger": portfolio_plan(snapshot, challenger_ids)},
        "random": {"methodology": RANDOM_METHOD, "draw_count": RANDOM_DRAWS, "seed": seed,
                   "seed_derivation": "SHA256 canonical JSON [benchmark version, random version, evaluation ID]",
                   "ordering": "gate priority, SHA256(seed:draw_index:company_id), ticker; canonical ID input order",
                   "membership_sha256": canonical_hash(draws) if draws else None,
                   "status": "verified" if policy else "unverified",
                   "exact_eligibility": "complete nonempty underlying eligible X universe plus existing analysis guards"},
        "matching": {"hierarchy": ["country+venue+size", "country+venue", "country"],
                     "minimum_alternatives": MIN_ALTERNATIVES, "exclude": "entire compared portfolio",
                     "sector": "not used", "fallback": "X-only missing fields or insufficient alternatives"},
        "weighting": "equal selected-security weights; equal within each fixed alternative pool; no missing-Y renormalization",
        "return_label": "mean_local_return_pct",
    }
    payload["plan_id"] = canonical_hash(payload)
    return BenchmarkPlan(payload, draws)


def validate_benchmark_plan(snapshot: EvaluationSnapshot, plan: BenchmarkPlan,
                            experiment: ChallengerExperimentSnapshot | None = None) -> BenchmarkPlan:
    value = plan.payload
    provenance = value.get("provenance")
    if provenance not in ("prospective", "prospective_unscheduled", "fixture", "retrospective"):
        raise ValueError("invalid benchmark provenance")
    if provenance in ("prospective", "prospective_unscheduled") and snapshot.configuration.get("provider") != "live":
        raise ValueError("fixture cannot claim prospective benchmark evidence")
    if provenance != "retrospective" and value.get("selection_evidence") is None:
        raise ValueError("new benchmark plan requires selection evidence")
    _, challenger_ids = _experiment_evidence(snapshot, experiment)
    if value.get("challenger_identity") is None:
        # A later-recorded experiment must not change an existing plan.
        experiment, challenger_ids = None, None
    expected = _construct_plan(snapshot, evidence=value.get("selection_evidence"),
                               challenger_ids=challenger_ids, experiment=experiment, provenance=provenance,
                               production_context=value.get("production_context"))
    if value != expected.payload:
        raise ValueError("benchmark plan conflicts with X, experiment, or frozen methodology")
    return expected


def benchmark_plan_path(root: Path, snapshot: EvaluationSnapshot) -> Path:
    return root / snapshot.report_date.isoformat() / snapshot.strategy / "benchmarks" / BENCHMARK_METHODOLOGY / f"{snapshot.run_id}.json"


def save_benchmark_plan(root: Path, snapshot: EvaluationSnapshot, plan: BenchmarkPlan) -> Path:
    path = benchmark_plan_path(root, snapshot)
    if "docs" in path.resolve().parts:
        raise ValueError("benchmark plans must stay outside docs/")
    content = json.dumps(plan.payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text() != content:
            raise ValueError("immutable benchmark plan identity conflict")
        return path
    _atomic_write(path, content)
    return path


def load_benchmark_plan(root: Path, snapshot: EvaluationSnapshot,
                        experiment: ChallengerExperimentSnapshot | None = None) -> BenchmarkPlan:
    path = benchmark_plan_path(root, snapshot)
    if not path.exists():
        return build_benchmark_plan(snapshot, experiment=experiment)
    try:
        plan = BenchmarkPlan(json.loads(path.read_text()), ())
        return validate_benchmark_plan(snapshot, plan, experiment)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed benchmark plan") from exc
