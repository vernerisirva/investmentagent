"""Public overview and Performance v2 pages (presentation only).

The pages display values the frozen Performance v2 analysis already computed and add counts,
coverage summaries and evidence labels. They never compute a new return aggregate, never
read prices or providers, and never present a figure from an analysis-ineligible run as a
performance result. Inconsistent analysis files make the pages say "unavailable" instead of
showing stale or partial numbers as current.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from investmentagent.analysis_eligibility import DEFAULT_ANALYSIS_ELIGIBILITY
from investmentagent.analysis_storage import (
    ANALYSIS_INDEX_NAME,
    STORAGE_KEY,
    _partition_path,
    _read_index,
    _relative_path,
)
from investmentagent.benchmarks import BENCHMARK_METHODOLOGY, RANDOM_DRAWS
from investmentagent.challenger_analysis import MIN_RELIABLE_PAIRED_DATES
from investmentagent.evaluation_analysis import MIN_RELIABLE_EVALUATION_DATES
from investmentagent.market_calendar import are_markets_open


DISCLAIMER = "Research triage only. Not financial advice."
REPOSITORY_URL = "https://github.com/vernerisirva/investmentagent"
ANALYSIS_SOURCE_PATH = (
    "data/evaluation-analysis/fixed-decision-membership-v1/cutoff-maturity-v1/"
    "representative-benchmarks-v1/performance-v2"
)
STRATEGY_LABELS = {"long-term": "Long-term", "trading": "Trading"}
SECONDARY_BENCHMARKS = (
    ("gate_qualified", "Gate-qualified equal weight"),
    ("opportunity", "Opportunity-universe equal weight"),
    ("exposure_matched", "Exposure-matched (country + venue)"),
)
MAX_ELIGIBLE_ROWS_PER_GROUP = 20
GROUP_KEYS = ("strategy", "horizon", "provenance", "selection_configuration_id", "evaluation_run_count",
              "analysis_eligible_run_count", "primary_eligible_run_count")
GAP_LOOKBACK_MARKET_DAYS = 60


class AnalysisUnavailable(ValueError):
    """The published analysis cannot be read consistently; show no figures from it."""


@dataclass(frozen=True)
class RunHorizon:
    evaluation_run_id: str
    decision_at: str
    strategy: str
    horizon_label: str
    sessions: int
    provenance: str
    selection_configuration_id: str
    is_due: bool
    analysis_eligible: bool
    outcome_coverage_pct: float | None
    x_size: int | None
    ineligibility_reasons: tuple[str, ...]
    random_status: str | None
    random_headline_eligible: bool
    champion: Mapping[str, Any]
    challenger: Mapping[str, Any]
    score_ic: float | None
    rank_ic: float | None


@dataclass(frozen=True)
class AnalysisSummary:
    generated_at: str
    data_cutoff: str
    schema_version: int
    benchmark_methodology: str
    analysis_methodology: str
    outcome_status_methodology: str
    return_methodology: str
    lifecycle: Mapping[str, Any]
    groups: tuple[Mapping[str, Any], ...]
    runs: tuple[RunHorizon, ...]
    warnings: tuple[str, ...]
    external_status: str


@dataclass(frozen=True)
class EvaluationRun:
    report_date: str
    strategy: str
    decision_at: str
    run_id: str
    universe_size: int
    public_selection_size: int | None
    scoring_model_version: str
    source_check_statuses: tuple[str, ...] = field(default_factory=tuple)


def load_analysis_summary(directory: Path) -> AnalysisSummary:
    """Read the partitioned analysis one partition at a time, verifying every digest."""
    try:
        index = _read_index(directory / ANALYSIS_INDEX_NAME)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AnalysisUnavailable(f"analysis index unreadable: {exc}") from exc
    if index.get("schema_version") != 4 or index.get("benchmark_methodology") != BENCHMARK_METHODOLOGY:
        raise AnalysisUnavailable("analysis is not a representative-benchmarks-v1 schema-4 analysis")
    storage = index[STORAGE_KEY]
    references = storage.get("run_metric_partitions")
    if not isinstance(references, list) or len(references) != storage.get("run_metric_count"):
        raise AnalysisUnavailable("analysis index partition count mismatch")
    runs = []
    for reference in references:
        relative = reference.get("path", "")
        try:
            if relative != _relative_path(relative):
                raise ValueError("unsafe analysis partition path")
            raw = (directory / relative).read_bytes()
        except (OSError, ValueError) as exc:
            raise AnalysisUnavailable(f"analysis partition unavailable: {relative}") from exc
        if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
            raise AnalysisUnavailable(f"analysis partition does not match its index digest: {relative}")
        try:
            partition = json.loads(raw.decode("utf-8"))
            if (partition.get("analysis_storage_layout"), partition.get("schema_version"),
                    partition.get("evaluation_run_id"), partition.get("horizon_label")) != (
                    storage["layout"], index["schema_version"], reference["evaluation_run_id"],
                    reference["horizon_label"]):
                raise AnalysisUnavailable(f"analysis partition identity mismatch: {relative}")
            metric = partition["run_metric"]
            if _partition_path(metric) != relative:
                raise AnalysisUnavailable(f"analysis partition stored at an unexpected path: {relative}")
            runs.append(_run_horizon(metric))
        except AnalysisUnavailable:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisUnavailable(f"analysis partition has an unexpected shape: {relative}") from exc
    try:
        methodology = index.get("methodology") or {}
        groups = tuple(index.get("groups") or ())
        for group in groups:
            missing = [key for key in GROUP_KEYS if key not in group]
            missing += [f"horizon.{key}" for key in ("label", "sessions") if key not in group.get("horizon", {})]
            if missing:
                raise KeyError(", ".join(missing))
        return AnalysisSummary(
            generated_at=index["generated_at"],
            data_cutoff=methodology.get("analysis_data_cutoff") or index["lifecycle"]["status_cutoff"],
            schema_version=index["schema_version"],
            benchmark_methodology=index["benchmark_methodology"],
            analysis_methodology=index.get("analysis_methodology", ""),
            outcome_status_methodology=index.get("outcome_status_methodology", ""),
            return_methodology=methodology.get("return_methodology", ""),
            lifecycle=index["lifecycle"],
            groups=groups,
            runs=tuple(runs),
            warnings=tuple(index.get("warnings") or ()),
            external_status=(index.get("external_passive_benchmark") or {}).get("status", "unknown"),
        )
    except (KeyError, TypeError) as exc:
        raise AnalysisUnavailable(f"analysis index has an unexpected shape: {exc}") from exc


def _run_horizon(metric: Mapping[str, Any]) -> RunHorizon:
    portfolios = metric.get("portfolios") or {}
    random_null = metric.get("random_null") or {}
    return RunHorizon(
        evaluation_run_id=metric["evaluation_run_id"],
        decision_at=metric["decision_at"],
        strategy=metric["strategy"],
        horizon_label=metric["horizon"]["label"],
        sessions=int(metric["horizon"]["sessions"]),
        provenance=metric["provenance"],
        selection_configuration_id=metric.get("selection_configuration_id", "unverified"),
        is_due=bool(metric.get("is_due")),
        analysis_eligible=bool(metric.get("analysis_eligible")),
        outcome_coverage_pct=metric.get("outcome_coverage_pct"),
        x_size=(metric.get("analysis_eligibility") or {}).get("original_company_count"),
        ineligibility_reasons=tuple(metric.get("analysis_ineligibility_reasons") or ()),
        random_status=random_null.get("status"),
        random_headline_eligible=bool(random_null.get("headline_eligible")),
        champion=_portfolio_view(portfolios.get("champion") or {}),
        challenger=_portfolio_view(portfolios.get("challenger") or {}),
        score_ic=metric.get("score_return_spearman_ic"),
        rank_ic=metric.get("final_rank_return_spearman_ic"),
    )


def _portfolio_view(portfolio: Mapping[str, Any]) -> dict[str, Any]:
    comparisons = portfolio.get("comparisons") or {}
    random_comparison = portfolio.get("random_comparison") or {}
    return {
        "status": portfolio.get("status"),
        "return_status": portfolio.get("return_status"),
        "exact": portfolio.get("exact_mean_local_return_pct"),
        "coverage_pct": portfolio.get("coverage_pct"),
        "members": portfolio.get("decision_time_member_count"),
        "headline_excess": {
            name: (comparisons.get(name) or {}).get("headline_local_excess_pct")
            for name, _ in SECONDARY_BENCHMARKS
        },
        "random_percentile": random_comparison.get("percentile_pct"),
        "excess_vs_random_mean": random_comparison.get("exact_local_excess_vs_mean_pct"),
    }


def exact_difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> float | None:
    """Simple difference in percentage points, only between two exact (complete) returns."""
    if left.get("return_status") != "complete" or right.get("return_status") != "complete":
        return None
    if left.get("exact") is None or right.get("exact") is None:
        return None
    return left["exact"] - right["exact"]


def scan_evaluations(root: Path) -> tuple[EvaluationRun, ...]:
    """Read only the header line of each persisted X; never the company rows."""
    runs = []
    if not root.is_dir():
        return ()
    for path in sorted(root.glob("*/*/*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
        if header.get("record_type") != "run":
            raise ValueError(f"evaluation snapshot has no run header: {path}")
        diagnostics = header.get("diagnostics") or {}
        runs.append(EvaluationRun(
            report_date=header["report_date"], strategy=header["strategy"],
            decision_at=header["decision_at"], run_id=header["run_id"],
            universe_size=int(header["universe_size"]),
            public_selection_size=diagnostics.get("public_selection_size"),
            scoring_model_version=header["scoring_model_version"],
            source_check_statuses=tuple(
                str(check.get("status")) for check in diagnostics.get("source_checks") or ()),
        ))
    return tuple(sorted(runs, key=lambda run: (run.report_date, run.strategy, run.decision_at)))


def production_gaps(evaluations: Sequence[EvaluationRun], *, lookback: int = GAP_LOOKBACK_MARKET_DAYS) -> list[str]:
    """Market days (Stockholm and Helsinki both open) with no X for at least one strategy."""
    if not evaluations:
        return []
    recorded: dict[str, set[str]] = {}
    for run in evaluations:
        recorded.setdefault(run.report_date, set()).add(run.strategy)
    strategies = {run.strategy for run in evaluations}
    last = date.fromisoformat(max(recorded))
    first = date.fromisoformat(min(recorded))
    gaps, day, checked = [], last, 0
    while day >= first and checked < lookback:
        if are_markets_open(day, ("stockholm", "helsinki")):
            checked += 1
            if recorded.get(day.isoformat(), set()) != strategies:
                gaps.append(day.isoformat())
        day -= timedelta(days=1)
    return sorted(gaps)


# --- rendering -------------------------------------------------------------------------

def render_performance_page(summary: AnalysisSummary | None, *, evaluations: Sequence[EvaluationRun],
                            generated_at: str, analysis_outcome: str | None = None,
                            unavailable_reason: str | None = None) -> str:
    lines = [
        "# InvestmentAgent Performance",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    if summary is None:
        lines.extend([
            "**Evidence status: unavailable.** The Performance v2 analysis could not be read "
            f"consistently ({unavailable_reason or 'no analysis found'}), so no performance "
            "figures are shown. Decision-time evidence is unaffected.",
            "",
            *_analysis_status_table(None, evaluations, analysis_outcome),
            "",
            *_methodology_lines(),
            *_legacy_lines(),
        ])
        return "\n".join(_strip_trailing(lines))
    groups = _group_views(summary)
    lines.extend([
        _evidence_headline(groups),
        "",
        *_analysis_status_table(summary, evaluations, analysis_outcome),
        "",
        "## Evidence by strategy and horizon",
        "",
        "Prospective decisions only (recorded before outcomes existed). A figure is shown only "
        f"when the frozen minimum of {MIN_RELIABLE_EVALUATION_DATES} analysis-eligible decision "
        "dates is met; a decision date is analysis-eligible when at least "
        f"{DEFAULT_ANALYSIS_ELIGIBILITY.minimum_coverage_pct:g}% of its eligible universe "
        f"(X) and at least {DEFAULT_ANALYSIS_ELIGIBILITY.minimum_valid_companies} companies have "
        "priced outcomes.",
        "",
        *_group_table([view for view in groups if view["provenance"] == "prospective"]),
        "",
        *_results_section([view for view in groups if view["provenance"] == "prospective"]),
        *_eligible_runs_section(groups),
        *_benchmark_section(summary, groups),
        *_alpha_section(),
        *_evidence_quality_section(summary, groups),
        *_retrospective_section([view for view in groups if view["provenance"] != "prospective"]),
        *_methodology_lines(),
        *_legacy_lines(),
    ])
    return "\n".join(_strip_trailing(lines))


def render_overview_page(summary: AnalysisSummary | None, *, evaluations: Sequence[EvaluationRun],
                         generated_at: str, report_files: Mapping[str, bool],
                         analysis_outcome: str | None = None,
                         unavailable_reason: str | None = None) -> str:
    latest_date = max((run.report_date for run in evaluations), default=None)
    latest_runs = {run.strategy: run for run in evaluations if run.report_date == latest_date}
    lines = [
        "# InvestmentAgent",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    groups = _group_views(summary) if summary is not None else []
    lines.extend([_overview_status(summary, groups, unavailable_reason), ""])
    lines.extend(["| Item | Status |", "| --- | --- |"])
    if latest_date is not None:
        decisions = "; ".join(
            f"{STRATEGY_LABELS.get(strategy, strategy).lower()} decision "
            f"{_parse(run.decision_at).astimezone(timezone.utc).strftime('%H:%M UTC')}"
            for strategy, run in sorted(latest_runs.items())
        )
        lines.append(f"| Latest production date | {latest_date} ({decisions}) |")
    else:
        lines.append("| Latest production date | No evaluation snapshots recorded |")
    model_versions = sorted({run.scoring_model_version for run in evaluations})
    lines.append(
        f"| Methodology | {', '.join(model_versions) or 'n/a'} ranking; selection "
        "production-country-minimum-v1; challenger relative-valuation-v2 (shadow); frozen — see "
        f"[METHODOLOGY_FREEZE.json]({REPOSITORY_URL}/blob/main/METHODOLOGY_FREEZE.json) |"
    )
    if summary is not None:
        prospective_dates = _decision_dates(summary, "prospective")
        lines.append(
            "| Prospective decision dates analysed | "
            + " · ".join(f"{STRATEGY_LABELS.get(s, s).lower()} {n}" for s, n in sorted(prospective_dates.items()))
            + " |"
        )
        lifecycle = summary.lifecycle
        lines.append(
            "| Mature / analysis-eligible run-horizons | "
            f"{lifecycle.get('mature_horizon_runs', 0)} of {lifecycle.get('horizon_runs', 0)} mature; "
            f"{lifecycle.get('analysis_eligible_horizon_runs', 0)} analysis-eligible |"
        )
        lines.append(f"| Price coverage of mature outcomes | {_coverage_text(lifecycle)} |")
        verified = sum(1 for run in summary.runs if run.random_status == "verified")
        headline = sum(1 for run in summary.runs if run.random_headline_eligible)
        lines.append(
            f"| Primary benchmark ({RANDOM_DRAWS:,} constrained random portfolios) | "
            f"recorded for {verified} of {len(summary.runs)} run-horizons; headline-eligible for {headline} |"
        )
        lines.append(f"| Champion vs relative-valuation-v2 | {_challenger_availability(summary, groups)} |")
        lines.append(f"| External passive index | {_external_text(summary.external_status)} |")
        lines.append(f"| Latest analysis | {_freshness_text(summary, evaluations)} |")
    else:
        lines.append(f"| Performance v2 analysis | unavailable ({unavailable_reason or 'not found'}) |")
    lines.append(f"| Latest analysis attempt | {_attempt_text(analysis_outcome)} |")
    gaps = production_gaps(evaluations)
    lines.append(
        f"| Production gaps (last {GAP_LOOKBACK_MARKET_DAYS} market days) | "
        + (", ".join(gaps) + " (no evaluation recorded)" if gaps else "none") + " |"
    )
    checks = [status for run in latest_runs.values() for status in run.source_check_statuses]
    if checks:
        warnings = sum(status != "ok" for status in checks)
        lines.append(
            f"| Data source checks (latest runs) | {len(checks) - warnings} ok, {warnings} not ok "
            f"across {len(latest_runs)} run(s); details in each report's run diagnostics |"
        )
    lines.extend(["", "## Today's ideas", ""])
    for strategy, title, path in (
        ("long-term", "Top 10 Long-Term Investment Ideas", "reports/long-term/latest.html"),
        ("trading", "Top 10 Trading Ideas", "reports/trading/latest.html"),
    ):
        run = latest_runs.get(strategy)
        if run is None:
            note = "no evaluation recorded for the latest date"
        elif run.universe_size == 0 or not run.public_selection_size:
            note = "no candidates at decision time"
        else:
            note = f"{run.public_selection_size} ideas from {run.universe_size} eligible companies"
        lines.append(f"- [{title}]({path}) — {note}")
    lines.extend([
        "- [Top 5 Global AI Candidates](reports/global-ai/latest.html) · [Global AI overview](global-ai.html)",
        "",
        "## Performance and methodology",
        "",
        "- [Performance v2 — authoritative evidence, benchmarks and limitations](performance/index.html)",
        "- [Legacy Performance v1 scorecard — non-authoritative archive](performance/legacy.html)",
        "",
    ])
    if latest_date is not None:
        dated = [
            (f"Trading Ideas {latest_date}", f"reports/trading/{latest_date}.html", "trading"),
            (f"Long-Term Investment Ideas {latest_date}", f"reports/long-term/{latest_date}.html", "long-term"),
            (f"Global AI Top 5 {latest_date}", f"reports/global-ai/{latest_date}.html", "global-ai"),
        ]
        available = [(title, path) for title, path, key in dated if report_files.get(key)]
        if available:
            lines.extend(["## Dated reports", "", *[f"- [{title}]({path})" for title, path in available], ""])
    lines.append("Reports are research triage only. Not financial advice.")
    return "\n".join(lines)


def _overview_status(summary: AnalysisSummary | None, groups, unavailable_reason) -> str:
    if summary is None:
        return (
            "**Strategy status: running; performance evidence unavailable.** The daily pipeline "
            "publishes ranked ideas, but the Performance v2 analysis could not be read "
            f"consistently ({unavailable_reason or 'not found'}). Operating the pipeline is not "
            "evidence of investment skill."
        )
    ready = [view for view in groups if view["provenance"] == "prospective"
             and view["eligible"] >= MIN_RELIABLE_EVALUATION_DATES]
    if not ready:
        best = max((view["eligible"] for view in groups if view["provenance"] == "prospective"), default=0)
        return (
            "**Strategy status: running; investment skill not yet demonstrated.** The daily "
            "pipeline publishes ranked ideas, but no strategy and horizon has the "
            f"{MIN_RELIABLE_EVALUATION_DATES} analysis-eligible decision dates needed for a "
            f"performance conclusion (best: {best}). Operating successfully is not evidence of "
            "investment skill."
        )
    labels = ", ".join(f"{STRATEGY_LABELS.get(v['strategy'], v['strategy'])} {_horizon(v['horizon_label'])}"
                       for v in ready)
    return (
        "**Strategy status: running; descriptive evidence available for "
        f"{labels}.** See the performance page for benchmark-relative results and their "
        "limitations. Benchmark differences are not risk-adjusted alpha."
    )


def _evidence_headline(groups) -> str:
    ready = [view for view in groups if view["provenance"] == "prospective"
             and view["eligible"] >= MIN_RELIABLE_EVALUATION_DATES]
    if not ready:
        return (
            "**Evidence status: Insufficient evidence.** No strategy and horizon has "
            f"{MIN_RELIABLE_EVALUATION_DATES} analysis-eligible decision dates yet, so this page "
            "reports how evidence is accumulating, not whether the strategy works. Operating the "
            "pipeline successfully is not the same as demonstrating investment skill."
        )
    return (
        "**Evidence status: descriptive results available for some horizons.** Figures below "
        "are mean local returns relative to internal benchmarks built from the same decision-time "
        "universe. They are not risk-adjusted alpha and not significance tests."
    )


def _analysis_status_table(summary, evaluations, analysis_outcome) -> list[str]:
    lines = ["| Analysis | Value |", "| --- | --- |"]
    if summary is not None:
        lines.extend([
            f"| Source | Performance v2 · {summary.benchmark_methodology} · analysis schema "
            f"{summary.schema_version} · {summary.analysis_methodology} · {summary.outcome_status_methodology} |",
            f"| Return convention | {summary.return_methodology or 'n/a'}: mean local returns (SEK for "
            "Stockholm, EUR for Helsinki; no currency conversion), gross of costs |",
            f"| Data cutoff | {_time(summary.data_cutoff)} |",
            f"| Freshness | {_freshness_text(summary, evaluations)} |",
        ])
    lines.append(f"| Latest analysis attempt | {_attempt_text(analysis_outcome)} |")
    return lines


def _attempt_text(outcome: str | None) -> str:
    if not outcome:
        return "not reported by this run"
    if outcome == "success":
        return "completed in this run"
    if outcome == "failure":
        return ("**failed in this run** — figures come from the last consistent published "
                "analysis (see data cutoff)")
    return f"{outcome} in this run"


def _freshness_text(summary: AnalysisSummary, evaluations: Sequence[EvaluationRun]) -> str:
    cutoff = _parse(summary.data_cutoff)
    newer = sorted({run.report_date for run in evaluations if _parse(run.decision_at) > cutoff})
    base = f"cutoff {_time(summary.data_cutoff)}"
    if not newer:
        return base + "; covers every recorded production date"
    shown = ", ".join(newer[:5]) + (" …" if len(newer) > 5 else "")
    return f"{base}; **{len(newer)} newer production date(s) not yet analysed** ({shown})"


def _coverage_text(lifecycle: Mapping[str, Any]) -> str:
    mature = int(lifecycle.get("mature") or 0)
    priced = int(lifecycle.get("mature_priced") or 0)
    if not mature:
        return "no mature outcomes yet"
    return (f"{priced:,} of {mature:,} ({100 * priced / mature:.1f}%); "
            f"{int(lifecycle.get('not_mature') or 0):,} outcomes not yet due")


def _external_text(status: str) -> str:
    if status == "deferred_pending_license":
        return "DEFERRED_PENDING_LICENSE — no proprietary passive index is used"
    return status


def _challenger_availability(summary: AnalysisSummary, groups) -> str:
    recorded_dates = sorted({run.decision_at[:10] for run in summary.runs
                             if run.strategy == "long-term" and run.challenger.get("status") == "recorded"})
    prospective = [view for view in groups if view["strategy"] == "long-term"
                   and view["provenance"] == "prospective"]
    comparable = max((view["challenger_dates"] for view in prospective), default=0)
    return (f"challenger recorded on {len(recorded_dates)} long-term decision date(s); "
            f"{comparable} comparable (need {MIN_RELIABLE_PAIRED_DATES})")


def _decision_dates(summary: AnalysisSummary, provenance: str) -> dict[str, int]:
    dates: dict[str, set[str]] = {}
    for run in summary.runs:
        if run.provenance == provenance:
            dates.setdefault(run.strategy, set()).add(run.evaluation_run_id)
    return {strategy: len(ids) for strategy, ids in dates.items()}


def _group_views(summary: AnalysisSummary | None) -> list[dict[str, Any]]:
    if summary is None:
        return []
    configurations: dict[tuple[str, str], set[str]] = {}
    for group in summary.groups:
        configurations.setdefault((group["strategy"], group["provenance"]), set()).add(
            group["selection_configuration_id"])
    views = []
    for group in summary.groups:
        key = (group["strategy"], group["horizon"]["label"], group["provenance"],
               group["selection_configuration_id"])
        runs = [run for run in summary.runs
                if (run.strategy, run.horizon_label, run.provenance, run.selection_configuration_id) == key]
        due = [run for run in runs if run.is_due]
        coverages = [run.outcome_coverage_pct for run in due if run.outcome_coverage_pct is not None]
        sizes = [run.x_size for run in runs if run.x_size is not None]
        champion = (group.get("portfolios") or {}).get("champion") or {}
        challenger = (group.get("portfolios") or {}).get("challenger") or {}
        ranking = group.get("ranking") or {}
        views.append({
            "strategy": group["strategy"], "horizon_label": group["horizon"]["label"],
            "sessions": group["horizon"]["sessions"], "provenance": group["provenance"],
            "configuration": group["selection_configuration_id"],
            "show_configuration": len(configurations[(group["strategy"], group["provenance"])]) > 1,
            "median_x_size": statistics.median(sizes) if sizes else None,
            "decision_dates": group["evaluation_run_count"], "due": len(due),
            "covered": sum(1 for value in coverages if value >= DEFAULT_ANALYSIS_ELIGIBILITY.minimum_coverage_pct),
            "median_coverage": statistics.median(coverages) if coverages else None,
            "eligible": group["analysis_eligible_run_count"],
            "primary_eligible": group["primary_eligible_run_count"],
            "champion_dates": champion.get("exact_primary_dates", 0),
            "champion_excess": champion.get("mean_local_excess_vs_random_pct"),
            "challenger_dates": challenger.get("exact_primary_dates", 0),
            "challenger_excess": challenger.get("mean_local_excess_vs_random_pct"),
            "score_ic": ranking.get("score_return_spearman_ic") or {},
            "rank_ic": ranking.get("final_rank_return_spearman_ic") or {},
            "eligible_runs": sorted((run for run in runs if run.analysis_eligible),
                                    key=lambda run: run.decision_at, reverse=True),
        })
    return sorted(views, key=lambda v: (v["strategy"] != "long-term", v["provenance"], v["sessions"], v["configuration"]))


def _group_label(view) -> str:
    label = f"{STRATEGY_LABELS.get(view['strategy'], view['strategy'])}"
    if view["provenance"] != "prospective":
        label += f" · {view['provenance']}"
    if view["configuration"] == "unverified":
        label += " (selection evidence unverified)"
    elif view["show_configuration"]:
        label += f" (selection {view['configuration'][:8]})"
    return label


def _group_table(views) -> list[str]:
    if not views:
        return ["_No prospective decision dates have been analysed yet._"]
    lines = [
        "| Strategy | Horizon | Decision dates | Median X size | Due | Due with ≥70% coverage | "
        f"Median coverage of due dates | Analysis-eligible (need {MIN_RELIABLE_EVALUATION_DATES}) | "
        "Random-null eligible |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for view in views:
        lines.append(
            f"| {_group_label(view)} | {_horizon(view['horizon_label'])} | {view['decision_dates']} | "
            f"{_count(view['median_x_size'])} | {view['due']} | {view['covered']} | {_pct(view['median_coverage'])} | {view['eligible']} | "
            f"{view['primary_eligible']} |"
        )
    return lines


def _gated(value: float | None, count: int, minimum: int, *, signed: bool = True, digits: int = 2) -> str:
    if count < minimum or value is None:
        return f"Insufficient evidence ({count} of {minimum})"
    return (f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}") + f" (n={count})"


def _results_section(views) -> list[str]:
    lines = [
        "### Results",
        "",
        "Excess return vs random = champion exact return minus the mean of the "
        f"{RANDOM_DRAWS:,} constrained random portfolios, in percentage points, averaged over "
        "random-null-eligible dates. IC = Spearman correlation between the decision-time score "
        "(or rank) and the forward return across X.",
        "",
        "| Strategy | Horizon | Champion excess vs random (pp) | Challenger excess vs random (pp) | Mean score IC | Mean rank IC |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for view in views:
        challenger = (_gated(view["challenger_excess"], view["challenger_dates"], MIN_RELIABLE_PAIRED_DATES)
                      if view["strategy"] == "long-term" else "not applicable")
        lines.append(
            f"| {_group_label(view)} | {_horizon(view['horizon_label'])} | "
            f"{_gated(view['champion_excess'], view['champion_dates'], MIN_RELIABLE_EVALUATION_DATES)} | "
            f"{challenger} | "
            f"{_gated(view['score_ic'].get('mean'), view['score_ic'].get('run_count', 0), MIN_RELIABLE_EVALUATION_DATES, digits=3)} | "
            f"{_gated(view['rank_ic'].get('mean'), view['rank_ic'].get('run_count', 0), MIN_RELIABLE_EVALUATION_DATES, digits=3)} |"
        )
    lines.append("")
    return lines


def _eligible_runs_section(groups) -> list[str]:
    eligible_views = [view for view in groups if view["eligible_runs"]]
    lines = ["### Analysis-eligible decision dates", ""]
    if not eligible_views:
        return lines + [
            "_None yet._ Run-level returns of ineligible dates are partial diagnostics; they are "
            "kept in the [full analysis]"
            f"({REPOSITORY_URL}/tree/main/{ANALYSIS_SOURCE_PATH}) and are not shown here as results.",
            "",
        ]
    for view in eligible_views:
        rows = view["eligible_runs"][:MAX_ELIGIBLE_ROWS_PER_GROUP]
        lines.extend([
            '<details markdown="1">',
            f"<summary>{_group_label(view)} · {_horizon(view['horizon_label'])} · "
            f"{view['provenance']} · {len(view['eligible_runs'])} eligible date(s)</summary>",
            "",
            "| Decision date | X coverage | Champion exact return | Excess vs gate-qualified | "
            "Excess vs opportunity | Excess vs exposure-matched | Random percentile | Excess vs random mean | "
            "Score IC | Rank IC | Champion − challenger |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for run in rows:
            champion = run.champion
            excess = champion.get("headline_excess") or {}
            difference = exact_difference(champion, run.challenger)
            lines.append(
                f"| {run.decision_at[:10]} | {_pct(run.outcome_coverage_pct)} | {_signed_pct(champion.get('exact'))} | "
                + " | ".join(_signed_pp(excess.get(name)) for name, _ in SECONDARY_BENCHMARKS)
                + f" | {_pct(champion.get('random_percentile')) if run.random_headline_eligible else 'not eligible'}"
                + f" | {_signed_pp(champion.get('excess_vs_random_mean'))}"
                + f" | {_number(run.score_ic, 3)} | {_number(run.rank_ic, 3)} | {_signed_pp(difference)} |"
            )
        if len(view["eligible_runs"]) > len(rows):
            lines.append("")
            lines.append(f"_Showing the {len(rows)} most recent of {len(view['eligible_runs'])} eligible dates; "
                         f"see the [full analysis]({REPOSITORY_URL}/tree/main/{ANALYSIS_SOURCE_PATH})._")
        lines.extend(["", "</details>", ""])
    return lines


def _benchmark_section(summary: AnalysisSummary, groups) -> list[str]:
    verified = sum(1 for run in summary.runs if run.random_status == "verified")
    return [
        "## Benchmarks",
        "",
        "| Benchmark | Role | Status |",
        "| --- | --- | --- |",
        f"| Constraint-matched random portfolios ({RANDOM_DRAWS:,} deterministic draws per decision) | "
        "Primary: same eligible universe, gate priority and country minimum as production | "
        f"plans verified for {verified} of {len(summary.runs)} run-horizons |",
        "| Gate-qualified equal weight | Secondary | in every run; coincides with the opportunity "
        "universe because X is recorded after the hard gates |",
        "| Opportunity-universe equal weight | Secondary | in every run |",
        "| Exposure-matched (country + venue strata) | Secondary | in every run; size is not "
        "retained in X, sector is not used |",
        "| Matched peers per selected company | Secondary, per security | in every run "
        "(minimum 5 alternatives, otherwise unavailable) |",
        f"| Champion vs relative-valuation-v2 | Shadow challenger | {_challenger_availability(summary, groups)} |",
        f"| External passive index (Nasdaq) | Not used | {_external_text(summary.external_status)} |",
        "",
        "Excess return is computed only when both returns are exact: every fixed decision-time "
        "member priced, no imputation, no replacement of missing stocks, no survivor-based "
        "membership. Random percentiles describe where the champion falls among the draws; they "
        "are **not p-values**.",
        "",
    ]


def _alpha_section() -> list[str]:
    return [
        "## Alpha and risk-adjusted performance",
        "",
        "**Risk-adjusted alpha: not yet estimable.** It needs a licensed market or factor "
        "benchmark (the external passive index is deferred pending licence), a risk-free "
        "series, a coherent periodic portfolio return series and enough independent "
        "observations. None of these exists yet, so no Jensen, CAPM, factor or annualized "
        "alpha is reported. Internal benchmark differences are reported as *excess return* "
        "against a named benchmark, never as alpha.",
        "",
        "| Metric | Status | Why |",
        "| --- | --- | --- |",
        "| Absolute return (exact, per decision date) | Shown for analysis-eligible dates | frozen analysis field |",
        "| Excess / active return vs internal benchmarks | Shown for analysis-eligible dates | frozen analysis field; same universe, date and horizon |",
        "| Volatility, downside deviation, maximum drawdown | Deferred | fixed-horizon returns of overlapping daily cohorts are not a portfolio value path |",
        "| Sharpe, Sortino, information ratio | Deferred | need a periodic return series, a risk-free rate and an authorized annualization convention |",
        "| Beta, CAPM / Jensen / factor alpha | Deferred | need licensed market or factor series |",
        "| Hit rate and win/loss vs benchmarks | Deferred | overlapping, dependent dates need a pre-registered dependence-aware convention |",
        "",
    ]


def _evidence_quality_section(summary: AnalysisSummary, groups) -> list[str]:
    lifecycle = summary.lifecycle
    statuses = lifecycle.get("status_counts") or {}
    status_text = ", ".join(f"{name.replace('_', ' ')} {count:,}" for name, count in sorted(statuses.items()))
    return [
        "## Evidence quality",
        "",
        f"- **Outcome records:** {int(lifecycle.get('total') or 0):,} (one per company, decision "
        f"date and horizon): {status_text or 'none'}.",
        f"- **Price coverage of mature outcomes:** {_coverage_text(lifecycle)}. Missing prices may be "
        "non-random (symbol resolution, country, segment), so low-coverage dates are diagnostics only.",
        f"- **Mature run-horizons:** {lifecycle.get('mature_horizon_runs', 0)} of "
        f"{lifecycle.get('horizon_runs', 0)}; analysis-eligible: "
        f"{lifecycle.get('analysis_eligible_horizon_runs', 0)}.",
        "- **Independence:** decisions are made on consecutive market days, so holding periods "
        "overlap for every horizon longer than one session and the same companies recur. Decision "
        "dates are not independent experiments, and no significance test is reported.",
        "- **Exact vs partial:** an exact return needs every fixed decision-time member priced; "
        "partial (observed-member) means are diagnostics and are never shown as results.",
        "- **Prospective vs retrospective:** samples are never pooled; retrospective and fixture "
        "dates are listed separately below.",
        "",
    ]


def _retrospective_section(views) -> list[str]:
    if not views:
        return []
    return [
        '<details markdown="1">',
        "<summary>Retrospective and fixture samples (never pooled with prospective decisions)</summary>",
        "",
        *_group_table(views),
        "",
        "</details>",
        "",
    ]


def _methodology_lines() -> list[str]:
    docs = f"{REPOSITORY_URL}/blob/main"
    return [
        "## Methodology and limitations",
        "",
        "- **What is tested:** whether the frozen ranking (nordic-ranking-v1 with the production "
        "country minimum) selects better than alternatives drawn from the same decision-time "
        "universe. It does not test beating the market index.",
        "- **Returns:** first exchange close strictly after the decision to the close a fixed number "
        "of market sessions later; split- and dividend-adjusted; mean local returns; gross of costs.",
        "- **Missing data:** missing stocks are never replaced or imputed; a decision date with "
        "incomplete prices has no exact return.",
        "- **What cannot be concluded yet:** whether the strategy has skill, any risk-adjusted "
        "alpha, any base-currency wealth return, or statistical significance.",
        f"- Details: [benchmark methodology]({docs}/BENCHMARK_METHODOLOGY.md) · "
        f"[fixed decision membership]({docs}/FIXED_DECISION_MEMBERSHIP.md) · "
        f"[outcome maturity]({docs}/OUTCOME_MATURITY_STATUS.md) · "
        f"[full analysis]({REPOSITORY_URL}/tree/main/{ANALYSIS_SOURCE_PATH})",
        "",
        '<a id="metric-definitions"></a>',
        "",
        "### Metric definitions",
        "",
        "- **Final rank / score percentile in X:** position in the decision-time eligible universe "
        "(X); percentile = share of the other X members with a lower score, ties counted half.",
        "- **Listing peers:** other X members with the same country and listing venue. They span "
        "many industries; size and sector peers are not used because X does not retain them.",
        "- **Peer position:** share of peers with a less favourable value, ties counted half "
        "(for P/E, P/B, EV/EBIT and debt/equity lower is better). Zero or negative multiples are "
        "excluded as not meaningful; fewer than 5 usable peers shows *Unavailable*.",
        "- **Exact return:** equal-weight mean local return of every fixed decision-time member. "
        "**Excess return vs X:** exact return minus the benchmark's exact return, in percentage points.",
        f"- **Random percentile:** share of the {RANDOM_DRAWS:,} random portfolios below the champion, "
        "ties counted half. Descriptive, not a p-value.",
        "- **Analysis-eligible date:** at least 70% of X and at least 50 companies priced for that horizon.",
        "",
    ]


def _legacy_lines() -> list[str]:
    return [
        "## Legacy Performance v1",
        "",
        "The earlier scorecard pooled overlapping daily picks and used benchmarks that "
        "representative-benchmarks-v1 retired. It is kept as a "
        "[non-authoritative archive](legacy.html) and is not evidence of skill or alpha.",
    ]


# --- small formatting helpers ----------------------------------------------------------

def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _time(value: str | None) -> str:
    if not value:
        return "n/a"
    return _parse(value).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _horizon(label: str) -> str:
    sessions = label.split("_", 1)[0]
    return f"{sessions} session" + ("" if sessions == "1" else "s")


def _count(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _signed_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _signed_pp(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f} pp"


def _number(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _strip_trailing(lines: list[str]) -> list[str]:
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def report_files_for(docs_root: Path, report_date: str | None) -> dict[str, bool]:
    if report_date is None:
        return {}
    return {kind: (docs_root / "reports" / kind / f"{report_date}.md").is_file()
            for kind in ("trading", "long-term", "global-ai")}
