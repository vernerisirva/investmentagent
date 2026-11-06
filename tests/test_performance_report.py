"""Public overview and Performance v2 pages: gated, labelled, fail-closed and offline."""
import copy
import json
import re
import socket
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from investmentagent.analysis_storage import save_partitioned_analysis
from investmentagent.cli import app
from investmentagent.market_calendar import are_markets_open
from investmentagent.performance_report import (
    AnalysisUnavailable, EvaluationRun, exact_difference, load_analysis_summary, production_gaps,
    render_overview_page, render_performance_page, scan_evaluations,
)
from test_analysis_storage import analysis as build_analysis
from test_challenger_experiment import _priced_outcomes, _research
from test_fixed_decision_membership import GENERATED, production_case
from investmentagent.benchmark_analysis import build_benchmark_analysis
from investmentagent.benchmarks import build_benchmark_plan

RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("reporting must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(scope="module")
def case():
    return production_case(count=60, research=[
        _research(i, country="SE" if i < 40 else "FI", pe_ratio=None) for i in range(60)])


def _as_prospective(analysis):
    analysis = copy.deepcopy(analysis)
    for row in [*analysis["run_metrics"], *analysis["groups"]]:
        if row["provenance"] == "fixture":
            row["provenance"] = "prospective"
    return analysis


def _save(tmp_path, analysis, name="analysis"):
    directory = tmp_path / name
    save_partitioned_analysis(directory, analysis)
    return directory


def _long_term_group(analysis):
    return next(g for g in analysis["groups"] if g["strategy"] == "long-term")


def _evaluations(*dates, strategy="long-term", decision="06:00:00"):
    return tuple(EvaluationRun(report_date=day, strategy=strategy, decision_at=f"{day}T{decision}Z",
                               run_id=f"evaluation-{day}", universe_size=60, public_selection_size=10,
                               scoring_model_version="nordic-ranking-v1", source_check_statuses=("ok",))
                 for day in dates)


def test_eligible_run_is_shown_but_aggregates_need_twenty_dates(tmp_path, case):
    analysis = _as_prospective(build_analysis(case))
    summary = load_analysis_summary(_save(tmp_path, analysis))
    page = render_performance_page(summary, evaluations=(), generated_at="now")
    assert page.startswith("# InvestmentAgent Performance")
    assert "**Evidence status: Insufficient evidence.**" in page
    results = page[page.index("### Results"):page.index("### Analysis-eligible decision dates")]
    assert "| Long-term | 1 session | Insufficient evidence (1 of 20) | Insufficient evidence (1 of 20) |" in results
    group_mean = _long_term_group(analysis)["portfolios"]["champion"]["mean_local_excess_vs_random_pct"]
    assert f"{group_mean:+.2f}" not in results
    eligible = page[page.index("### Analysis-eligible decision dates"):page.index("## Benchmarks")]
    assert "| 2026-08-10 | 100.0% | +5.50% |" in eligible
    assert "Long-term · 1 session · prospective · 1 eligible date(s)" in eligible


def test_aggregates_appear_exactly_at_the_frozen_minimum(tmp_path, case):
    analysis = _as_prospective(build_analysis(case))
    group = _long_term_group(analysis)
    for count, shown in ((19, False), (20, True)):
        changed = copy.deepcopy(analysis)
        target = _long_term_group(changed)
        target["analysis_eligible_run_count"] = count
        target["portfolios"]["champion"]["exact_primary_dates"] = count
        target["ranking"]["score_return_spearman_ic"]["run_count"] = count
        summary = load_analysis_summary(_save(tmp_path, changed, f"min-{count}"))
        page = render_performance_page(summary, evaluations=(), generated_at="now")
        results = page[page.index("### Results"):page.index("### Analysis-eligible decision dates")]
        value = group["portfolios"]["champion"]["mean_local_excess_vs_random_pct"]
        assert (f"{value:+.2f} (n=20)" in results) is shown
        assert (f"Insufficient evidence ({count} of 20)" in results) is not shown


def test_ineligible_run_returns_are_never_rendered(tmp_path, case):
    result, snapshot, experiment = case
    returns = [float(row.rank) * 1.2345 for row in snapshot.rows]
    # The 25 lowest-ranked companies are unpriced: the selected ten are complete (an exact
    # champion return exists) but X coverage is 58%, so the run is not analysis-eligible.
    missing = [row.company_id for row in snapshot.rows[-25:]]
    store = _priced_outcomes(snapshot, returns, missing_company_ids=missing)
    plans = {snapshot.run_id: build_benchmark_plan(snapshot, result=result, experiment=experiment)}
    analysis = _as_prospective(build_benchmark_analysis(
        [snapshot], [store], generated_at=GENERATED, data_cutoff=GENERATED,
        experiment_snapshots=[experiment], plans=plans))
    [metric] = analysis["run_metrics"]
    assert not metric["analysis_eligible"]
    champion = metric["portfolios"]["champion"]
    values = [champion["exact_mean_local_return_pct"], champion["observed_member_mean_local_return_pct"],
              metric["opportunity_universe"]["observed_member_mean_local_return_pct"]]
    assert all(value is not None for value in values)
    page = render_performance_page(load_analysis_summary(_save(tmp_path, analysis)), evaluations=(),
                                   generated_at="now")
    for value in values:
        for text in (f"{value:.2f}", f"{value:+.2f}", f"{value:.1f}%"):
            assert text not in page
    assert "_None yet._" in page


def test_tampered_or_missing_analysis_fails_closed(tmp_path, case):
    directory = _save(tmp_path, build_analysis(case))
    partition = next(directory.glob("runs/*/*/*/*.json"))
    partition.write_text(partition.read_text().replace("100.0", "99.0", 1))
    with pytest.raises(AnalysisUnavailable, match="digest"):
        load_analysis_summary(directory)
    with pytest.raises(AnalysisUnavailable, match="index"):
        load_analysis_summary(tmp_path / "nowhere")
    out = tmp_path / "site"
    result = RUNNER.invoke(app, ["evaluate", "report", "--analysis-dir", str(directory),
                                 "--evaluation-root", str(tmp_path / "x"), "--output", str(out / "p.md"),
                                 "--overview", str(out / "index.md"), "--docs-root", str(out),
                                 "--analysis-outcome", "success", "--generated-at", "now"])
    assert result.exit_code == 0, result.output
    page = (out / "p.md").read_text()
    assert "**Evidence status: unavailable.**" in page and "digest" in page
    assert "| Item | Status |" in (out / "index.md").read_text()
    assert "performance evidence unavailable" in (out / "index.md").read_text()
    assert "### Results" not in page


def test_stale_analysis_and_failed_attempt_are_visible(tmp_path, case):
    summary = load_analysis_summary(_save(tmp_path, build_analysis(case)))
    cutoff = date.fromisoformat(summary.data_cutoff[:10])
    newer = [(cutoff + timedelta(days=offset)).isoformat() for offset in (1, 2)]
    page = render_performance_page(summary, evaluations=_evaluations(*newer), generated_at="now",
                                   analysis_outcome="failure")
    assert f"**2 newer production date(s) not yet analysed** ({newer[0]}, {newer[1]})" in page
    assert "**failed in this run**" in page
    current = render_performance_page(summary, evaluations=(), generated_at="now", analysis_outcome="success")
    assert "covers every recorded production date" in current and "completed in this run" in current


def test_labels_for_currency_alpha_benchmarks_and_p_values(tmp_path, case):
    page = render_performance_page(load_analysis_summary(_save(tmp_path, build_analysis(case))),
                                   evaluations=(), generated_at="now")
    assert "SEK for Stockholm, EUR for Helsinki; no currency conversion" in page
    assert "**Risk-adjusted alpha: not yet estimable.**" in page
    assert "DEFERRED_PENDING_LICENSE" in page
    assert "**not p-values**" in page
    assert "alpha" not in page.split("## Alpha and risk-adjusted performance")[0].lower()


def test_benchmark_unavailable_runs_are_labelled(tmp_path, case):
    analysis = _as_prospective(build_analysis(case))
    for metric in analysis["run_metrics"]:
        metric["random_null"]["status"] = "unverified"
        metric["random_null"]["headline_eligible"] = False
    summary = load_analysis_summary(_save(tmp_path, analysis))
    page = render_performance_page(summary, evaluations=(), generated_at="now")
    assert f"plans verified for 0 of {len(summary.runs)} run-horizons" in page
    assert "| not eligible |" in page


def test_retrospective_samples_are_never_pooled_with_prospective(tmp_path, case):
    analysis = _as_prospective(build_analysis(case))
    page = render_performance_page(load_analysis_summary(_save(tmp_path, analysis)), evaluations=(),
                                   generated_at="now")
    main = page[page.index("## Evidence by strategy and horizon"):page.index("### Results")]
    retrospective = page[page.index("<summary>Retrospective and fixture samples"):]
    assert "retrospective" not in main.split("\n\n", 2)[2]
    assert "| Trading · retrospective (selection evidence unverified) | 1 session |" in retrospective


def test_exact_difference_requires_two_complete_returns():
    complete = {"return_status": "complete", "exact": 4.0}
    assert exact_difference(complete, {"return_status": "complete", "exact": 1.5}) == 2.5
    assert exact_difference(complete, {"return_status": "incomplete", "exact": None}) is None
    assert exact_difference({"return_status": "complete", "exact": None}, complete) is None


def test_production_gaps_use_both_market_calendars():
    days, day = [], date(2026, 10, 26)
    while len(days) < 8:
        if are_markets_open(day, ("stockholm", "helsinki")):
            days.append(day.isoformat())
        day += timedelta(days=1)
    recorded = [d for d in days if d != days[3]]
    evaluations = _evaluations(*recorded) + _evaluations(*recorded, strategy="trading")
    assert production_gaps(evaluations) == [days[3]]
    assert production_gaps(evaluations[:-1]) == [days[3], recorded[-1]]
    assert production_gaps(()) == []


def test_overview_reports_status_links_and_health(tmp_path, case):
    summary = load_analysis_summary(_save(tmp_path, _as_prospective(build_analysis(case))))
    evaluations = _evaluations(summary.data_cutoff[:10])
    page = render_overview_page(summary, evaluations=evaluations, generated_at="now",
                                report_files={"long-term": True, "trading": False, "global-ai": True},
                                analysis_outcome="success")
    assert "**Strategy status: running; investment skill not yet demonstrated.**" in page
    assert "Operating successfully is not evidence of investment skill." in page
    assert "| Methodology | nordic-ranking-v1 ranking;" in page
    assert "| External passive index | DEFERRED_PENDING_LICENSE" in page
    assert "(performance/index.html)" in page and "(performance/legacy.html)" in page
    assert f"reports/long-term/{evaluations[0].report_date}.html" in page
    assert f"reports/trading/{evaluations[0].report_date}.html" not in page
    assert "{{" not in page and "{%" not in page


def test_cli_writes_all_pages_from_headers_only_and_ignores_the_legacy_ledger(tmp_path, case):
    result, snapshot, experiment = case
    directory = _save(tmp_path, build_analysis(case))
    x_root = tmp_path / "x"
    path = x_root / "2026-08-10" / "long-term" / "run.jsonl"
    path.parent.mkdir(parents=True)
    header = json.dumps({"record_type": "run", "report_date": "2026-08-10", "strategy": "long-term",
                         "decision_at": "2026-08-10T08:00:00Z", "run_id": snapshot.run_id,
                         "universe_size": 60, "scoring_model_version": "nordic-ranking-v1",
                         "diagnostics": {"public_selection_size": 10, "source_checks": []}})
    path.write_text(header + "\nnot json: company rows are never read\n")
    outputs = []
    for with_ledger in (False, True):
        docs = tmp_path / f"docs-{with_ledger}"
        (docs / "reports" / "long-term").mkdir(parents=True)
        (docs / "reports" / "long-term" / "2026-08-10.md").write_text("report\n")
        if with_ledger:
            (docs / "data" / "performance").mkdir(parents=True)
            (docs / "data" / "performance" / "ledger.json").write_text('{"picks": [1]}')
        args = ["evaluate", "report", "--analysis-dir", str(directory), "--evaluation-root", str(x_root),
                "--output", str(docs / "performance" / "index.md"),
                "--latest", str(docs / "performance" / "latest.md"),
                "--overview", str(docs / "index.md"), "--docs-root", str(docs),
                "--analysis-outcome", "success", "--generated-at", "2026-11-06 08:20 EET"]
        run = RUNNER.invoke(app, args)
        assert run.exit_code == 0, run.output
        page = (docs / "performance" / "index.md").read_text()
        assert page == (docs / "performance" / "latest.md").read_text()
        overview = (docs / "index.md").read_text()
        for link in re.findall(r"\]\((reports/[^)]+)\.html\)", overview):
            if "latest" not in link:
                assert (docs / f"{link}.md").is_file()
        outputs.append((page, overview))
    assert outputs[0] == outputs[1]
    assert "Hit Rate" not in outputs[0][0] and "Learning" not in outputs[0][0]
    bad = RUNNER.invoke(app, ["evaluate", "report", "--analysis-dir", str(directory),
                              "--analysis-outcome", "maybe"])
    assert bad.exit_code != 0


def test_scan_evaluations_rejects_files_without_a_run_header(tmp_path):
    path = tmp_path / "2026-08-10" / "trading" / "run.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"record_type": "company"}\n')
    with pytest.raises(ValueError, match="run header"):
        scan_evaluations(tmp_path)
    assert scan_evaluations(tmp_path / "absent") == ()


def test_unexpected_index_shape_is_unavailable_not_a_crash(tmp_path, case):
    directory = _save(tmp_path, build_analysis(case))
    index = json.loads((directory / "index.json").read_text())
    del index["groups"][0]["primary_eligible_run_count"]
    (directory / "index.json").write_text(json.dumps(index))
    with pytest.raises(AnalysisUnavailable, match="unexpected shape"):
        load_analysis_summary(directory)


ALLOWED_TAGS = {"a", "details", "summary"}


def test_pages_contain_only_markdown_safe_html(tmp_path, case):
    summary = load_analysis_summary(_save(tmp_path, _as_prospective(build_analysis(case))))
    pages = [
        render_performance_page(summary, evaluations=(), generated_at="now", analysis_outcome="failure"),
        render_performance_page(None, evaluations=(), generated_at="now", unavailable_reason="missing"),
        render_overview_page(summary, evaluations=_evaluations("2026-08-10"), generated_at="now",
                             report_files={}),
    ]
    for page in pages:
        assert set(re.findall(r"</?([A-Za-z][\w-]*)", page)) <= ALLOWED_TAGS
        assert page.count("<details") == page.count("</details>")
        assert "{{" not in page and "{%" not in page


@pytest.mark.parametrize("reference", [{"path": ""}, {"path": "../index.json"}, {}, "runs/x.json"])
def test_malformed_partition_references_fail_closed(tmp_path, case, reference):
    directory = _save(tmp_path, build_analysis(case))
    index = json.loads((directory / "index.json").read_text())
    index["analysis_storage"]["run_metric_partitions"][0] = reference
    (directory / "index.json").write_text(json.dumps(index))
    with pytest.raises(AnalysisUnavailable, match="reference unusable"):
        load_analysis_summary(directory)
